import contextlib
import logging
import os
import re
import sys
from importlib.util import find_spec

import numpy as np
import pandas as pd

from analyzers.llm_client import run_llm_dataframe
from config import BASE_DIR
from i18n import t

logger = logging.getLogger(__name__)

#: The three values this operation ever writes. Downstream charts group on the column, so
#: a fourth spelling from a model would read as a real category with one row in it.
LABELS = ('positive', 'negative', 'neutral')

#: Every mode, and the only ones that answer the question 「这条文本是正面的吗」 with a
#: probability the thresholds can be applied to. ``ml`` and ``llm`` answer with a label
#: they were trained or prompted to choose, and re-deciding it from a number the reader
#: cannot interpret would be a second opinion about the model's own answer.
SCORE_MODES = ('snownlp', 'bert')

#: Rows handed to the transformer in one forward pass. The old path called the pipeline
#: once per row — a Python-level round trip for every comment — which on a real Weibo
#: table (10^5 rows) is the difference between minutes and an hour. 32 keeps a 110M
#: model's activations far inside an 8 GB card while still filling it.
BERT_BATCH = 32


class PolarityError(ValueError):
    """The reader cannot answer THIS column at all, as opposed to one row of it.

    The per-row guard in ``_score_dataframe`` leaves a text it cannot read blank and
    carries on — the right answer when one string trips a model up, and completely wrong
    when the answer it is producing is from a vocabulary this column cannot hold. A
    refusal of that kind has to travel, or the node settles DONE over a table of blanks
    with one warning line in the log file as the only trace.
    """


def bert_backend() -> str:
    """What this machine does not have for ``bert``, or ``''`` when it can run one of the runtimes.

    ``find_spec`` rather than an ``import``: this runs on the path that decides whether to REFUSE,
    and importing torch to discover it is absent costs seconds and a couple of hundred MB of
    resident memory to learn a fact a directory listing already answers.
    """
    return '' if bert_runtime() else t('sentiment.bert_need_runtime')


def bert_device() -> int:
    """``0`` when this machine has a CUDA device, ``-1`` (CPU) otherwise.

    The transformer path was written for a CPU-only machine and stayed there, which is
    the wrong default for the one machine this actually runs on: a laptop with a small
    GPU answers the same column an order of magnitude faster, and nothing in the node
    asked to be slow. A machine without torch answers -1, which is the pipeline's own
    CPU default, so the no-GPU case is not a special case here.
    """
    try:
        import torch
    except Exception:
        return -1
    with contextlib.suppress(Exception):
        if torch.cuda.is_available():
            return 0
    return -1


def _importable(name: str) -> bool:
    """Would ``import name`` work here — answered without importing it.

    ``find_spec`` is the cheap answer for a module that has not been touched yet (importing torch
    to learn it is missing costs seconds and a couple of hundred MB). It is the wrong answer for a
    module already in ``sys.modules``: one placed there by another loader can be missing
    ``__spec__``, and ``find_spec`` then raises ``ValueError`` rather than reporting what looking
    the name up already told you.
    """
    if name in sys.modules:
        return True
    with contextlib.suppress(ValueError):
        return find_spec(name) is not None
    return False


def bert_runtime() -> str:
    """``'torch'`` / ``'onnx'`` / ``''`` — which BERT runtime this machine can actually run.

    torch first, because the machine that has it is the one the models were trained on and it may
    answer on a GPU. ``onnxruntime`` + ``tokenizers`` is what the packaged Windows app ships: an
    ONNX graph needs neither torch nor transformers, and the standalone ``tokenizers`` crate reads
    the same ``tokenizer.json`` the training script wrote. A machine with neither answers ``''``,
    which is what makes the node refuse (or degrade, with the mode that ran printed).
    """
    if _importable('torch') and _importable('transformers'):
        return 'torch'
    if _importable('onnxruntime') and _importable('tokenizers'):
        return 'onnx'
    return ''


#: The ONNX graph is fed the padding mask as an additive ``[batch, 1, query, key]`` tensor and the
#: position ids read off that mask, instead of letting the model build them inside the traced
#: forward. Measured with the plain 2D mask, the exporter froze transformers' padding branch into
#: a constant and the same text answered up to 1.0 logit apart depending on how its batch happened
#: to be padded; with these two as inputs the graph matches the torch model to 3e-07 with 243
#: padding cells. ``ml_train/scripts/export_onnx_bert.py`` writes graphs in exactly this shape.
ONNX_MASK_VALUE = -1e9
ONNX_GRAPH_INPUTS = ('input_ids', 'position_ids', 'attention_mask_4d', 'token_type_ids')

#: Live classifier sessions are the model in memory — 98 MB quantised, 390 MB unquantised — and a
#: multi-model comparison can name four of them. Two at a time, oldest dropped, and the drop is
#: printed: silently releasing a model the next batch will reload is a slow run nobody can explain.
SESSION_LIMIT = 2
_SESSIONS: dict = {}
_SESSION_ORDER: list = []


class BertClassifier:
    """One loaded bert classifier: ``predict(texts)`` answers ``{'label', 'score'}`` per text.

    The three operations that read a transformer (sentiment, emotion, tendency) used to build their
    own ``pipeline`` inside their own ``_analyze_bert`` — which meant a fresh model load per call,
    three copies of the same availability dance, and no answer to "which runtime produced this
    column". All of it lives here. The answer shape is the pipeline's own, so ``_signed_polarity``
    and each operation's label vocabulary are unchanged: a torch answer and an ONNX answer are
    interchangeable values, not two dialects.
    """

    def __init__(self, model_path: str, *, task: str = 'text-classification', runtime: str = '', max_length: int = 128):
        self.model_path = model_path
        self.task = task
        self.runtime = runtime or bert_runtime()
        self.max_length = max_length
        self.precision = ''
        self.device = ''
        if self.runtime == 'torch':
            self._init_torch()
        elif self.runtime == 'onnx':
            self._init_onnx()
        else:
            raise ValueError(t('sentiment.bert_missing', need=bert_backend()))

    def _init_torch(self) -> None:
        from transformers import pipeline

        device = bert_device()
        self.device = 'cuda' if device >= 0 else 'cpu'
        self.precision = 'fp32'
        self._call = pipeline(self.task, model=self.model_path, device=device)

    def _init_onnx(self) -> None:
        """Load the graph, the tokenizer and the label vocabulary the export wrote beside it."""
        import json

        import onnxruntime as ort
        from tokenizers import Tokenizer

        folder = self.model_path if os.path.isdir(self.model_path) else os.path.dirname(self.model_path)
        graph = os.path.join(folder, 'model.onnx')
        if not os.path.isfile(graph):
            raise ValueError(t('sentiment.bert_no_onnx', path=folder))
        sidecar = {}
        for name in ('cixi_bert.json', 'config.json'):
            holder = os.path.join(folder, name)
            if os.path.isfile(holder):
                with open(holder, encoding='utf-8') as handle:
                    sidecar = json.load(handle)
                break
        self.precision = str(sidecar.get('precision') or 'fp32')
        self.device = 'cpu'
        self._labels = {str(key): str(value) for key, value in (sidecar.get('id2label') or {}).items()}
        if not self._labels:
            raise ValueError(t('sentiment.bert_no_labels', path=folder))
        self._session = ort.InferenceSession(graph, providers=['CPUExecutionProvider'])
        names = [item.name for item in self._session.get_inputs()]
        if tuple(names) != ONNX_GRAPH_INPUTS:
            # A graph in another shape is not this code path's contract; answering it wrong is a
            # silent numeric change, so name the inputs it expects instead of guessing at them.
            raise ValueError(t('sentiment.bert_onnx_inputs', found=', '.join(names)))
        self._tokenizer = Tokenizer.from_file(os.path.join(folder, 'tokenizer.json'))
        self._tokenizer.enable_truncation(self.max_length)
        self._tokenizer.enable_padding()  # to the longest row of this batch: the key dims are dynamic

    def predict(self, texts: list) -> list:
        if self.runtime == 'torch':
            return list(self._call(list(texts), batch_size=len(texts), truncation=True, max_length=self.max_length))
        return self._predict_onnx(list(texts))

    def _predict_onnx(self, texts: list) -> list:
        encodings = self._tokenizer.encode_batch(texts)
        ids = np.asarray([item.ids for item in encodings], dtype=np.int64)
        mask = np.asarray([item.attention_mask for item in encodings], dtype=np.int64)
        # ``type_ids`` is what the crate calls token_type_ids — measured, not assumed: a stub that
        # invents the friendlier name ships an AttributeError in the packaged app instead.
        types = np.asarray([item.type_ids for item in encodings], dtype=np.int64)
        # Padded cells get position 0 — not the last real index — because that is what
        # ``ml_train/scripts/export_onnx_bert.py`` builds when it traces and verifies the graph. The
        # two differ only on rows the mask already ignores, but a runtime that computes positions its
        # own way is a number nobody measured, and the parity against torch was proven with this one.
        positions = np.where(mask == 0, 0, np.cumsum(mask, axis=1) - 1)
        additive = (1.0 - mask[:, None, None, :].astype(np.float32)) * ONNX_MASK_VALUE
        logits = self._session.run(
            None,
            {
                'input_ids': ids,
                'position_ids': positions.astype(np.int64),
                'attention_mask_4d': additive.astype(np.float32),
                'token_type_ids': types,
            },
        )[0]
        return [
            {'label': self._label_of(row), 'score': float(value)}
            for row, value in zip(logits, _softmax(logits), strict=True)
        ]

    def _label_of(self, row) -> str:
        return self._labels[str(int(row.argmax()))]


def _softmax(logits):
    """Row-wise maximum probability, in the order the logits arrived.

    The torch pipeline reports the winning label's probability; this is the same number, so a
    score column means the same thing whichever runtime produced the row.
    """
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return (exp / exp.sum(axis=1, keepdims=True)).max(axis=1)


def bert_classifier(model_path: str, *, task: str, runtime: str = '', max_length: int = 128) -> BertClassifier:
    """A loaded classifier for this model, reused across the batches of a run.

    Cache key is ``(path, task, runtime, max_length)``: the same folder answers a different question
    under a different task, the torch and ONNX builds of one model are different answers on paper,
    and the truncation length is baked into the tokenizer the loader configured — two nodes with
    different 截断长度 sharing one session would silently truncate one of them wrong.
    """
    key = (str(model_path), str(task), runtime or bert_runtime(), int(max_length))
    if key in _SESSIONS:
        _SESSION_ORDER.remove(key)
        _SESSION_ORDER.append(key)
        return _SESSIONS[key]
    holder = BertClassifier(model_path, task=task, runtime=runtime, max_length=max_length)
    _SESSIONS[key] = holder
    _SESSION_ORDER.append(key)
    while len(_SESSION_ORDER) > SESSION_LIMIT:
        dropped = _SESSION_ORDER.pop(0)
        _SESSIONS.pop(dropped, None)
        logger.info(t('sentiment.bert_session_dropped', model=dropped[0]))
    return holder


def resolve_bert_model(name: str) -> str:
    """Turn a node's ``bert_model`` field into a path the pipeline can load on THIS machine.

    A workflow is authored work and is versioned, but the models it names are not inside it —
    so a stored absolute ``F:/Users/…/ml_train/bert_…`` is a dead reference the moment the
    canvas is opened on another device or checkout location. A relative ``ml_train/bert_…``
    resolves against the project root here, so the same canvas runs wherever the repo lives,
    provided the (gitignored) model folder was copied next to it. An existing absolute/cwd path
    wins first, a bare folder name is looked up under ``ml_train/``, and anything else is handed
    through untouched so ``transformers`` treats it as a hub id — an unreachable one still
    refuses BY NAME at the pipeline, never silently substitutes another model.
    """
    raw = (name or '').strip()
    if not raw:
        return ''
    if os.path.isdir(raw) or os.path.isfile(raw):  # absolute, or already cwd-relative and real
        return raw
    rel = raw.replace('\\', '/').lstrip('/')
    joined = os.path.normpath(os.path.join(BASE_DIR, rel))
    if os.path.isdir(joined):  # relative to the project root — the portable form
        return joined
    under_ml = os.path.normpath(os.path.join(BASE_DIR, 'ml_train', os.path.basename(rel)))
    if os.path.isdir(under_ml):  # a bare folder name
        return under_ml
    return raw  # assume an HF hub id; the pipeline refuses by name if it cannot load it


def _signed_polarity(answer: dict) -> float:
    """One pipeline answer as a polarity probability, or a refusal.

    The pipeline reports its own label plus a confidence; the three-value column needs a
    polarity probability, so the confidence is signed by the label it came with. A model
    that says 负面 0.93 is a text 0.07 positive, and that is the one number the
    thresholds mean anything against.
    """
    name = str(answer.get('label') or '').lower()
    score = float(answer.get('score') or 0.0)
    if any(word in name for word in ('pos', '正面', '积极', 'good', '支持')):
        return score
    if any(word in name for word in ('neg', '负面', '消极', 'bad', '批评')):
        return 1.0 - score
    raise PolarityError(t('sentiment.bert_bad_label', label=answer.get('label')))


class SentimentAnalyzer:
    """Text polarity — four ways to answer 正面 / 负面 / 中性 for one column of text.

    The two operations this sits beside already answer "which emotion" and "what kind of
    coverage", and both need a label set the traditional libraries cannot produce:
    SnowNLP and a Chinese sentiment BERT answer a single question, whether the text reads
    positive, so they get their own operation and their own three-value column instead of
    being squashed into five Ekman labels or six tendency classes and guessing at the rest.

    Mode ``snownlp``: the bundled naive-Bayes polarity model (no download, no GPU).
    Mode ``ml``: the locally trained sklearn classifier, like ``emotion`` and
    ``tendency`` — trained from labelled rows already in the table.
    Mode ``llm``: row-by-row via an LLM (local Ollama or an OpenRouter API model),
    batched and checkpointed so an interrupted run keeps everything it already answered.
    Mode ``bert``: a transformer pipeline, when this machine can actually run one.
    """

    ML_MODEL_NAME = 'sentiment'

    def __init__(
        self,
        mode: str = 'snownlp',
        model_name: str = 'qwen3.5:9b',
        pos_threshold: float = 0.6,
        neg_threshold: float = 0.4,
        bert_model: str = '',
        batch_size: int = BERT_BATCH,
        max_length: int = 512,
    ):
        self.mode = mode
        self.model_name = model_name
        self.pos_threshold = pos_threshold
        self.neg_threshold = neg_threshold
        self.bert_model = bert_model
        # A configured 0 would make the chunking loop below step zero times and score an
        # empty column while reporting success, so the floor is one row.
        self.batch_size = max(1, int(batch_size or BERT_BATCH))
        # Tokenizer per-sequence truncation for the bert path; configurable so a long post's
        # tail is not silently dropped (floor one token; the caller clamps the range).
        self.max_length = max(1, int(max_length or 512))
        # Lazily built, exactly as the other two classifiers build theirs: a run that
        # asks for SnowNLP must not touch sklearn, and one that asks for sklearn must not
        # pay for a model file it will never read.
        self._ml_instance = None

    @property
    def _ml(self):
        if self._ml_instance is None:
            from analyzers.ml_base import get_classifier

            self._ml_instance = get_classifier(self.ML_MODEL_NAME)
        return self._ml_instance

    # ── score-shaped modes ────────────────────────────────────────────

    def label_for_score(self, score: float) -> str:
        """Which of the three labels a polarity probability is called.

        The bounds are inclusive on purpose: ``score == pos_threshold`` is the strongest
        reading the user's own figure still accepts as positive, and a table whose default
        is 0.6 answering 0.6 as 中性 would look like the threshold had been ignored.
        """
        if score >= self.pos_threshold:
            return 'positive'
        if score <= self.neg_threshold:
            return 'negative'
        return 'neutral'

    def _analyze_snownlp(self, df: pd.DataFrame, text_column: str) -> pd.DataFrame:
        from snownlp import SnowNLP

        def read(text: str) -> float:
            return float(SnowNLP(text).sentiments)

        return self._score_dataframe(df, text_column, read=read, failure_key='sentiment.snownlp_failed')

    def _analyze_bert(self, df: pd.DataFrame, text_column: str) -> pd.DataFrame:
        """A transformer sentiment pipeline, or the reason there is not one here.

        Every answer refuses BY NAME. Silently falling back to SnowNLP would put one
        model's verdict in a column the node said another model produced, which is the
        exact shape of bug this project has already paid for twice. (The node executor
        degrades an unrunnable explicit ``bert`` to the op's general mode BEFORE reaching
        here, and prints which mode actually ran — so a real run never aborts on a missing
        torch stack, while this method still refuses any direct bert call.)

        The whole column goes through in batches. That is the difference between a node
        that finishes a 100k-comment table in minutes and one that spends an hour in
        Python between forward passes — see :data:`BERT_BATCH`.
        """
        missing = bert_backend()
        if missing:
            raise ValueError(t('sentiment.bert_missing', need=missing))
        model = resolve_bert_model(self.bert_model)
        if not model:
            raise ValueError(t('sentiment.bert_no_model'))

        classifier = bert_classifier(model, task='sentiment-analysis', max_length=self.max_length)
        # Said out loud, because "did this use my GPU, or the ONNX runtime, or the quantised
        # weights" is otherwise only answerable by timing the run. The executor's degradation prints
        # the MODE that ran; this prints which build of the model answered.
        logger.info(
            t(
                'sentiment.bert_loaded',
                model=model,
                device=classifier.device,
                runtime=classifier.runtime,
                precision=classifier.precision,
            )
        )

        def read_many(texts: list) -> list:
            """One forward pass per chunk, one answer per text, failures as values.

            A batch that raises answers every row of that batch with the same exception
            rather than ending the column: the per-row contract of this operation is that
            the rows that read are answered and the ones that did not stay blank.
            Truncation lives in the classifier so the tokenizer's own limit is applied to
            the batch, instead of this module guessing at a character count.
            """
            try:
                answers = classifier.predict(list(texts))
            except Exception as e:
                return [e] * len(texts)
            out = []
            for answer in answers:
                try:
                    out.append(_signed_polarity(answer))
                except PolarityError as e:
                    # A label this mapping does not know is a question about the MODEL,
                    # not about one row: it travels, as it did before batching existed.
                    out.append(e)
            return out

        return self._score_dataframe(df, text_column, failure_key='sentiment.bert_failed', read_many=read_many)

    def _score_dataframe(
        self, df: pd.DataFrame, text_column: str, read=None, failure_key: str = '', read_many=None
    ) -> pd.DataFrame:
        """Apply one polarity reader down a column, and write the two result columns.

        A row that fails to read is left BLANK, not answered 中性: 「没有判断」 and
        「判断为中性」 are different statements, and the second one is a claim about the
        text that nothing in fact established. ``failure_key`` is the catalogue KEY and
        not a finished sentence, because the reason has to be interpolated into it — a
        rendered string handed in here printed the template back with a literal ``{err}``
        in the console and no error at all.

        Exactly one of ``read`` (one text) and ``read_many`` (a batch, answering with a
        float or an Exception per text) is given. Both funnel into the same per-row
        settlement, so a batched model and a looped one cannot disagree about what a
        failure means.
        """
        df['sentiment'] = ''
        df['score'] = None
        if text_column not in df.columns:
            logger.error(t('ml.missing_col', col=text_column))
            return df
        mask = df[text_column].notna() & (df[text_column].astype(str).str.strip() != '')
        indices = df[mask].index.tolist()
        if not indices:
            logger.info(t('ml.no_rows'))
            return df
        failed = 0
        scored = 0
        step = self.batch_size if read_many is not None else 1
        for start in range(0, len(indices), step):
            chunk = indices[start : start + step]
            texts = [str(df.at[idx, text_column]).strip() for idx in chunk]
            if read_many is not None:
                answers = list(read_many(texts))
            else:
                answers = []
                for text in texts:
                    try:
                        answers.append(read(text))
                    except Exception as e:
                        answers.append(e)
            for idx, answer in zip(chunk, answers, strict=False):
                if isinstance(answer, PolarityError):
                    raise answer
                if isinstance(answer, Exception):
                    failed += 1
                    logger.warning(t(failure_key, err=answer))
                    continue
                score = max(0.0, min(1.0, float(answer)))
                df.at[idx, 'score'] = score
                df.at[idx, 'sentiment'] = self.label_for_score(score)
                scored += 1
        logger.info(t('sentiment.scored', n=scored, mode=self.mode))
        if failed:
            logger.warning(t('sentiment.scored_failed', n=failed))
        return df

    # ── label-shaped modes ────────────────────────────────────────────

    def build_sentiment_prompt(self, text: str) -> str:
        return (
            """
Role: Sentiment Polarity Analyst

Goal: Decide whether the given text reads POSITIVE, NEGATIVE or NEUTRAL toward the thing
it talks about. This is polarity only — do not name an emotion, do not grade the writing.

Rules:
- Ignore hashtags, @mentions, URLs and `##` markers; judge the words around them.
- A factual statement, a question, a number or a report of an event is NEUTRAL, even when
  the event itself is bad news.
- Sarcasm counts as the feeling it expresses: praise that clearly means the opposite is
  NEGATIVE.
- "Not good", "doesn't work" and a complaint are NEGATIVE. "Could be better" is NEGATIVE
  too, but weakly — lower the score.
- Score is the probability that the text is positive, 0 to 1: 0.95 certain praise, 0.05
  certain complaint, and NEUTRAL sits near 0.5.

Output Format:
Strictly output ONLY a plain string, no JSON and no code block:
`Sentiment: {label}, Score: {score}` where label is one of ['positive','negative','neutral']
and score is a number between 0 and 1.

Input Text:
"""
            + text
            + """

Analyze strictly and output only the required plain string."""
        )

    def parse_sentiment_response(self, content: str):
        content = str(content or '').strip()
        label = re.search(r'Sentiment:\s*([A-Za-z]+)', content)
        score = re.search(r'Score:\s*([0-9.]+)', content)
        if not label:
            return None, None
        name = label.group(1).lower()
        if name not in LABELS:
            return None, None
        value = None
        if score:
            try:
                value = max(0.0, min(1.0, float(score.group(1))))
            except ValueError:
                value = None
        return name, value

    def _analyze_ml(self, df: pd.DataFrame, text_column: str) -> pd.DataFrame:
        df['sentiment'] = ''
        df['score'] = None
        if text_column not in df.columns:
            logger.error(t('ml.missing_col', col=text_column))
            return df
        mask = df[text_column].notna() & (df[text_column].astype(str).str.strip() != '')
        indices = df[mask].index.tolist()
        if not indices:
            logger.info(t('ml.no_rows'))
            return df
        texts = [str(df.at[idx, text_column]).strip() for idx in indices]
        try:
            # 'neutral' is this operation's own neutral word: MLClassifier answers an
            # untrained model with the CALLER's neutral, and a leaked 'Neutral' from the
            # emotion label set would be a class these charts have never seen.
            predictions = self._ml.predict(texts, _neutral='neutral')
        except Exception as e:
            # Refused, not manufactured — see the same guard in emotion.py. The caller's neutral is
            # still the right WORD for a real prediction (a leaked 'Neutral' from the emotion label
            # set would be a class these charts have never seen); it is no longer an ANSWER when
            # there is no model behind it.
            from analyzers.ml_base import ModelNotTrainedError

            if isinstance(e, ModelNotTrainedError):
                raise
            logger.error(t('sentiment.ml_failed', err=e))
            predictions = [('neutral', 0.5)] * len(texts)
        for idx, (label, score) in zip(indices, predictions, strict=False):
            df.at[idx, 'sentiment'] = str(label).strip().lower()
            df.at[idx, 'score'] = score
        logger.info(t('sentiment.scored', n=len(texts), mode='ml'))
        return df

    def _analyze_llm(self, df: pd.DataFrame, text_column: str, ctx: dict) -> pd.DataFrame:
        return run_llm_dataframe(
            df,
            text_column,
            op='sentiment',
            result_columns=['sentiment', 'score'],
            blank=['', None],
            fail_value=('neutral', None),
            build_prompt=self.build_sentiment_prompt,
            parse=self.parse_sentiment_response,
            ctx=ctx,
            label=t('label.sentiment'),
            default_model=self.model_name,
        )

    def fit_training(self, df: pd.DataFrame, text_column: str = '正文', label_column: str = 'sentiment'):
        """Fit this operation's own classifier from rows the table already labels.

        The route the 训练模型 button takes: the labels are the same three words this
        column will later hold, so a table judged once by the LLM can train the fast
        path for the next thousand rows.
        """
        from analyzers.ml_base import build_training_data

        texts, labels = build_training_data(df, text_column, label_column)
        self._ml.fit(texts, labels)
        return self

    # ── entry ─────────────────────────────────────────────────────────

    def analyze_dataframe(
        self,
        df: pd.DataFrame,
        text_column: str = '正文',
        ctx: dict = None,
    ) -> pd.DataFrame:
        # Named one at a time, never branched on "not this one". An ``!= 'ml'`` test is how
        # ``mode='ML'`` came to pay for the row-by-row LLM pass the user had just declined,
        # and this node has four answers to choose between now.
        if self.mode == 'snownlp':
            return self._analyze_snownlp(df, text_column)
        if self.mode == 'ml':
            return self._analyze_ml(df, text_column)
        if self.mode == 'llm':
            return self._analyze_llm(df, text_column, ctx)
        if self.mode == 'bert':
            return self._analyze_bert(df, text_column)
        raise ValueError(t('sentiment.unknown_mode', mode=self.mode))
