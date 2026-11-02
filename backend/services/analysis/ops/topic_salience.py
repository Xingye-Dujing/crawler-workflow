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
    surface and a topic of nothing but “的” becomes impossible to read. The paper's figure
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
    texts, model, matrix, doc_topic, vocabulary = _prepare_topic_model(
        df, column, topics, max_features, method, embedding_model
    )
    counts = np.asarray(matrix.sum(axis=0), dtype=float).ravel()
    total_tokens = float(counts.sum())
    if not total_tokens:
        raise UnknownOperationError(t('analysis.topic_features', err='the corpus has no tokens left to count'))
    p_w = counts / total_tokens
    word_topic = np.asarray(model.components_, dtype=float)
    row_sums = word_topic.sum(axis=1, keepdims=True)
    # Dividing an all-zero row (an empty embedding cluster) is 0/0 — NaN that would flow
    # into within_freq/relevance and poison every row the topic still manages to print.
    # A topic with no words lists no terms, so a zero row stays a zero row.
    word_topic = np.divide(word_topic, row_sums, out=np.zeros_like(word_topic), where=row_sums > 0)
    # The share of the corpus each topic actually carries, from the model's own
    # document-topic assignments (LDA: summed responsibilities; embedding: one-hot cluster
    # sizes — the same prevalence the map prints). The weight this used to apply divided a
    # NORMALISED row's sum by K — a constant 1/K wearing the name ``prior``, which scaled
    # every within_freq by the wrong topic weight and read as "the topic owns 1/K of the
    # corpus" whatever the model had actually learned.
    doc_mass = np.asarray(doc_topic, dtype=float).sum(axis=0)
    mass_total = float(doc_mass.sum())
    shares = doc_mass / mass_total if mass_total > 0 else np.full(topics, 1.0 / topics)
    rows = []
    for index in range(topics):
        own = word_topic[index]
        within = own * float(shares[index]) * total_tokens
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
