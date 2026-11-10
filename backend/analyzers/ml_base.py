import logging
import os
import threading

import jieba
import numpy as np
import pandas as pd
from core.config import Config
from core.refs import sanitize_filename

from analyzers.stopwords import STOPWORDS
from i18n import t

logger = logging.getLogger(__name__)

# sklearn and joblib are imported inside the functions that train or load a model, never here:
# this module sits on the boot path (``analyzers`` is imported by ``app``), and pulling in all of
# sklearn to answer a request that never trains an ML classifier cost 5.4 s of process start.
# ``tests/unit/foundation/test_boot_import_budget.py`` fails if a top-level import comes back.


class ModelNotTrainedError(ValueError):
    """No model to predict with. Distinct so a caller can tell "nothing to load" apart from
    "the load broke", and raised instead of the answer being manufactured."""


# Derived from ``Config.DATA_DIR`` rather than from this file's location: the test harness
# redirects Config before anything is imported, and a path computed here would be a second,
# unredirectable answer to "where do trained models live".
MODEL_DIR = os.path.join(Config.DATA_DIR, 'models')
os.makedirs(MODEL_DIR, exist_ok=True)


def _tokenize(text: str) -> str:
    return ' '.join(jieba.cut(str(text)))


# Module level, not lambdas: MLClassifier.fit() joblib-dumps the pipeline, and
# a lambda has no importable path to pickle by — the whole "train ML from
# labelled rows" feature died with PicklingError while these were inline.
def _whitespace_tokenizer(text: str) -> list:
    return str(text).split()


def _no_preprocessing(text: str) -> str:
    return text


def build_tfidf_pipeline(
    classifier=None, max_features: int = 20000, stop_words=None, ngram_range=(1, 2), char_features: bool = False
):
    """TF-IDF over jieba-tokenised text + a logistic classifier.

    Two settings raised from the naive default because they are what a Chinese micro-text
    classifier needs:  the shared stopword table is applied (the rest of the text stack already
    denoises with it, and leaving the ML path to see 的/了/是 unfiltered was a real accuracy gap),
    and  the classifier is class-weight-balanced (the labelled sets are imbalanced — one class
    of 1-clean alone is ~60%), so the minority sentiment is not flattened by the majority.
    `sublinear_tf` tames long posts' term counts. All three are overridable; passing
    `stop_words=[]` restores the old no-filter behaviour, and a caller can still hand its own
    `classifier`/`max_features`. The tokenizer stays whitespace-only because `fit`/`predict`
    already jieba-split upstream (see `_tokenize`), so the vectorizer must not re-tokenise.

    Set `char_features=True` to ALSO feed a character n-gram view of the same text through a
    FeatureUnion. Chinese micro-text sentiment leans on characters, sub-words and emoji that a
    jieba word vocabulary misses; a char_wb (2,4) branch unions with the word branch and is the
    strongest no-deep-learning feature here. Default off keeps the plain word pipeline — and the
    already-saved word-model .pkl files — byte-for-byte unchanged.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    if stop_words is None:
        stop_words = sorted(STOPWORDS)
    if classifier is None:
        classifier = LogisticRegression(max_iter=2000, class_weight='balanced')

    word_tfidf = TfidfVectorizer(
        tokenizer=_whitespace_tokenizer,
        preprocessor=_no_preprocessing,
        token_pattern=None,
        max_features=max_features,
        ngram_range=ngram_range,
        sublinear_tf=True,
        stop_words=stop_words,
    )
    if not char_features:
        return Pipeline([('tfidf', word_tfidf), ('clf', classifier)])

    char_tfidf = TfidfVectorizer(
        analyzer='char_wb',
        ngram_range=(2, 4),
        max_features=100000,
        sublinear_tf=True,
    )
    return Pipeline(
        [
            ('features', FeatureUnion([('word', word_tfidf), ('char', char_tfidf)])),
            ('clf', classifier),
        ]
    )


class MLClassifier:
    def __init__(self, model_name: str = 'default', pipeline=None):
        # ``model_name`` reaches the filesystem: ``fit`` joblib-dumps to this path and
        # ``predict`` joblib-loads it back. A value that is not one safe component would
        # let ``../x`` escape MODEL_DIR — a write anywhere, then an arbitrary pickle read
        # on the next predict (code execution). Collapse it to a single safe name and
        # refuse anything the sanitizer had to change, so the containment cannot be bypassed
        # even if an upstream caller forgets its own allow-list.
        safe = sanitize_filename(model_name)
        if not safe or safe != str(model_name):
            raise ValueError(t('ml.bad_model_name', name=model_name))
        self.model_name = safe
        self.pipeline = pipeline or build_tfidf_pipeline()
        self._fitted = False
        self._label_map = {}
        self._path = os.path.join(MODEL_DIR, f'{safe}.pkl')
        # One classifier instance is shared by every workflow thread (``get_classifier``), so the
        # lazy load and the prediction read the same ``pipeline``/``_fitted`` pair. Without this a
        # 训练 request and a parallel canvas could interleave a half-fitted pipeline into a predict.
        self._lock = threading.RLock()

    def fit(self, texts: list[str], labels: list[str]):
        import joblib

        if not texts:
            raise ValueError(t('ml.no_training_rows'))
        unique = sorted(set(labels))
        if len(unique) < 2:
            # A logistic regression needs two classes; without this guard the
            # failure surfaces as a bare sklearn ValueError hundreds of frames
            # deep (and as an HTTP 500).
            raise ValueError(t('ml.need_two_labels', label=unique[0] if unique else ''))
        tokenized = [_tokenize(t) for t in texts]
        # Built locally and PUBLISHED inside the lock, together with the pipeline it describes. It was
        # assigned here, outside: a concurrent ``predict`` (which takes the lock) could then read the
        # new label map against the still-unfitted pipeline — answering a class index the old model
        # never produced, or an IndexError when the new map has fewer labels than the old pipeline.
        label_map = {lb: i for i, lb in enumerate(unique)}
        y = np.array([label_map[lb] for lb in labels])
        with self._lock:
            self.pipeline.fit(tokenized, y)
            self._label_map = label_map
            self._fitted = True
            # Atomic: a crash halfway through a direct dump left a truncated pickle that every
            # later ``predict`` failed to load — and, because the failure was an UnpicklingError,
            # it read as a broken install rather than "this model was never finished training".
            temporary = f'{self._path}.tmp'
            joblib.dump({'pipeline': self.pipeline, 'label_map': label_map}, temporary)
            os.replace(temporary, self._path)
        return self

    def predict(self, texts: list[str], _neutral: str = 'Neutral') -> list[tuple[str, float]]:
        import joblib

        with self._lock:
            if not self._fitted:
                if os.path.exists(self._path):
                    try:
                        data = joblib.load(self._path)
                        self.pipeline = data['pipeline']
                        self._label_map = data['label_map']
                    except Exception as exc:
                        # A truncated/corrupt checkpoint is a named refusal, not a traceback that
                        # names no model: the file exists but is not a model this program wrote.
                        raise ModelNotTrainedError(t('ml.model_unreadable', name=self.model_name)) from exc
                    self._fitted = True
                else:
                    # REFUSED, not manufactured. Handing back the caller's neutral for every row read
                    # as a finished analysis: the node settled DONE, the table printed a column that
                    # was 100% one class at 0.5, and the study's charts treated it as measured opinion.
                    # (An untrained model still must not leak a fixed 'Neutral' into a label set that
                    # has no such class — that is why the refusal names the model rather than guessing
                    # a label.) A degradation is allowed only when it is SANCTIONED and PRINTED, which
                    # is the executor's job one level up (``_resolve_bert_mode``), not this class's.
                    raise ModelNotTrainedError(t('ml.model_untrained_refused', name=self.model_name))
            tokenized = [_tokenize(t) for t in texts]
            probs = self.pipeline.predict_proba(tokenized)
            indices = np.argmax(probs, axis=1)
            rev_map = {i: lb for lb, i in self._label_map.items()}
            return [(rev_map[idx], float(probs[i, idx])) for i, idx in enumerate(indices)]


_shared_classifiers: dict[str, MLClassifier] = {}
#: ``check-then-create`` on a module dict: two parallel workflows both constructing (and both
#: dumping) the same ``.pkl`` was the race. The lock guards the map; construction itself is cheap
#: (the pipeline is built in memory) and happens under it so one instance is shared, never two.
_CLASSIFIER_LOCK = threading.Lock()


def get_classifier(name: str) -> MLClassifier:
    with _CLASSIFIER_LOCK:
        if name not in _shared_classifiers:
            _shared_classifiers[name] = MLClassifier(model_name=name)
        return _shared_classifiers[name]


def build_training_data(df: pd.DataFrame, text_col: str, label_col: str) -> tuple[list[str], list[str]]:
    mask = df[text_col].notna() & (df[text_col].astype(str).str.strip() != '') & df[label_col].notna()
    valid = df[mask]
    texts = valid[text_col].astype(str).tolist()
    labels = valid[label_col].astype(str).tolist()
    return texts, labels
