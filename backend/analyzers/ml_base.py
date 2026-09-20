import logging
import os

import jieba
import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from i18n import t

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'models')
os.makedirs(MODEL_DIR, exist_ok=True)


def _tokenize(text: str) -> str:
    return ' '.join(jieba.cut(str(text)))


def build_tfidf_pipeline(classifier=None, max_features: int = 5000):
    if classifier is None:
        classifier = LogisticRegression(max_iter=1000)
    return Pipeline(
        [
            (
                'tfidf',
                TfidfVectorizer(
                    tokenizer=lambda t: t.split(),
                    preprocessor=lambda t: t,
                    token_pattern=None,
                    max_features=max_features,
                    ngram_range=(1, 2),
                ),
            ),
            ('clf', classifier),
        ]
    )


class MLClassifier:
    def __init__(self, model_name: str = 'default', pipeline=None):
        self.model_name = model_name
        self.pipeline = pipeline or build_tfidf_pipeline()
        self._fitted = False
        self._label_map = {}
        self._path = os.path.join(MODEL_DIR, f'{model_name}.pkl')

    def fit(self, texts: list[str], labels: list[str]):
        tokenized = [_tokenize(t) for t in texts]
        unique = sorted(set(labels))
        self._label_map = {lb: i for i, lb in enumerate(unique)}
        y = np.array([self._label_map[lb] for lb in labels])
        self.pipeline.fit(tokenized, y)
        self._fitted = True
        joblib.dump({'pipeline': self.pipeline, 'label_map': self._label_map}, self._path)
        return self

    def predict(self, texts: list[str]) -> list[tuple[str, float]]:
        if not self._fitted:
            if os.path.exists(self._path):
                data = joblib.load(self._path)
                self.pipeline = data['pipeline']
                self._label_map = data['label_map']
                self._fitted = True
            else:
                logger.warning(t('ml.model_missing', name=self.model_name))
                return [('Neutral', 0.5) for _ in texts]
        tokenized = [_tokenize(t) for t in texts]
        probs = self.pipeline.predict_proba(tokenized)
        indices = np.argmax(probs, axis=1)
        rev_map = {i: lb for lb, i in self._label_map.items()}
        return [(rev_map[idx], float(probs[i, idx])) for i, idx in enumerate(indices)]


_shared_classifiers: dict[str, MLClassifier] = {}


def get_classifier(name: str) -> MLClassifier:
    if name not in _shared_classifiers:
        _shared_classifiers[name] = MLClassifier(model_name=name)
    return _shared_classifiers[name]


def build_training_data(df: pd.DataFrame, text_col: str, label_col: str) -> tuple[list[str], list[str]]:
    mask = df[text_col].notna() & (df[text_col].astype(str).str.strip() != '') & df[label_col].notna()
    valid = df[mask]
    texts = valid[text_col].astype(str).tolist()
    labels = valid[label_col].astype(str).tolist()
    return texts, labels
