"""The ``topic_salience`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging
import math

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import _prepare_topic_model

logger = logging.getLogger(__name__)


def topic_salience(
    df: pd.DataFrame,
    column: str,
    n_topics: int = 5,
    max_features: int = 2000,
    topn: int = 30,
    relevance: float = 1.0,
    method: str = 'lda',
    embedding_model: str = '',
) -> pd.DataFrame:
    """The figure's right-hand panel: the terms a topic is ABOUT, with both counts.

    Two bars per term, exactly as the study prints them — the corpus-wide frequency (blue)
    and the frequency this topic alone would produce (red). Which terms belong on the list
    at all is decided by the relevance weighting of Sievert & Shirley (2014):
    ``λ·log p(w|t) + (1−λ)·log(p(w|t)/p(w))``. λ=1 ranks by the topic's own probability, so
    a common word can win; λ=0 ranks by over-representation, so rare-but-diagnostic words
    surface and a topic of nothing but 「的」 becomes impossible to read. The paper's figure
    has a slider for this; here it is a parameter, and the number used is printed with the
    rows because two λs give two different answers from one model.
    """
    import numpy as np

    if column not in df.columns:
        return df
    topics = int(n_topics)
    lam = float(relevance)
    if not 0.0 <= lam <= 1.0:
        raise UnknownOperationError(t('analysis.topic_lambda', value=relevance))
    texts, model, matrix, _doc_topic, vocabulary = _prepare_topic_model(
        df, column, topics, max_features, method, embedding_model
    )
    counts = np.asarray(matrix.sum(axis=0), dtype=float).ravel()
    total_tokens = float(counts.sum())
    if not total_tokens:
        raise UnknownOperationError(t('analysis.topic_features', err='the corpus has no tokens left to count'))
    p_w = counts / total_tokens
    word_topic = np.asarray(model.components_, dtype=float)
    word_topic = word_topic / word_topic.sum(axis=1, keepdims=True)
    prior = word_topic.sum(axis=1) / len(word_topic)
    rows = []
    for index in range(topics):
        own = word_topic[index]
        within = own * float(prior[index]) * total_tokens
        scored = []
        for position in range(len(vocabulary)):
            probability = float(own[position])
            if probability <= 0.0:
                continue  # a term this topic never uses has no relevance to rank
            share = float(p_w[position])
            lift = probability / share if share > 0 else 0.0
            if lift <= 0.0:
                continue
            value = lam * math.log2(probability) + (1.0 - lam) * math.log2(lift)
            # Ties break on the term itself so two runs of one table list the same words
            # in the same order; numpy's argsort would leave the order to floating point.
            scored.append((value, str(vocabulary[position]), position))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        for rank, (value, term, position) in enumerate(scored[: max(1, int(topn))]):
            rows.append(
                {
                    'topic': f'Topic-{index + 1}',
                    'rank': rank + 1,
                    'term': term,
                    'overall_freq': int(counts[position]),
                    'within_freq': round(float(within[position]), 2),
                    'relevance': round(value, 4),
                }
            )
    logger.info(t('analysis.topic_salience_done', n=topics, rows=len(texts), terms=len(rows), value=lam))
    return pd.DataFrame(rows)


# ── What the phases did to each other ───────────────────────
