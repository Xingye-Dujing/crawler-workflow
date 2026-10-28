"""The ``topic_map`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.topic_kernels import _jsd_matrix, _mds_2d, _prepare_topic_model

logger = logging.getLogger(__name__)


def topic_map(
    df: pd.DataFrame,
    column: str,
    n_topics: int = 5,
    max_features: int = 2000,
    topn: int = 6,
    method: str = 'lda',
    embedding_model: str = '',
) -> pd.DataFrame:
    """The intertopic distance map's DATA: where each topic sits, and how big it is.

    pyLDAvis draws topics as bubbles placed by multidimensional scaling of the distance
    between their word distributions, sized by how much of the corpus each one claims. It
    is a picture of the MODEL rather than of the words, and it answers the question the
    exported topic list cannot: are these five subjects actually distinct, or is one of
    them a slightly louder copy of another? Overlapping bubbles say the split was not in
    the text.

    Prevalence is the model's own document mass (``doc_topic.sum(axis=0)``), not the argmax
    count :meth:`topic_by_stage` files as ``doc_n``: a post that leans 40/60 between two
    topics belongs to both here, because the map shows what the model is unsure about while
    the table records what it decided. ``doc_n`` is still reported beside it so the two
    readings can be compared rather than confused.
    """
    if column not in df.columns:
        return df
    topics = int(n_topics)
    texts, model, matrix, doc_topic, vocabulary = _prepare_topic_model(
        df, column, topics, max_features, method, embedding_model
    )
    mass = doc_topic.sum(axis=0)
    total = float(mass.sum())
    claimed = [int(owner) for owner in doc_topic.argmax(axis=1)]
    points = _mds_2d(_jsd_matrix(model.components_))
    rows = []
    for index in range(topics):
        component = model.components_[index]
        best = component.argsort()[::-1][: max(1, int(topn))]
        rows.append(
            {
                'topic': f'Topic-{index + 1}',
                'pc1': round(float(points[index][0]), 6),
                'pc2': round(float(points[index][1]), 6),
                'prevalence_pct': round(float(mass[index]) / total * 100, 2) if total else 0.0,
                'doc_n': claimed.count(index),
                'feature_words': '、'.join(str(vocabulary[position]) for position in best),
            }
        )
    logger.info(
        t(
            'analysis.topic_map_done',
            n=topics,
            rows=len(texts),
            perplexity=round(float(model.perplexity(matrix)), 2),
        )
    )
    return pd.DataFrame(rows)
