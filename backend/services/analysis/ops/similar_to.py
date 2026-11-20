"""The ``similar_to`` step: rank table rows by cosine similarity to one short query.

A small Chinese sentence encoder answers this in one forward pass over the column and is the right
tool for "find the comments closest to this one", a job a keyword match answers badly. The output is
a FIXED four-column table, so a chart or a downstream step always knows what it reads.
"""

import logging

import numpy as np
import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.ops.semantic_dedupe import _validate

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = ('rank', 'row_index', 'text', 'similarity')


def similar_to(
    df: pd.DataFrame,
    column: str,
    query: str,
    top_k: int = 10,
    model: str = 'BAAI/bge-small-zh-v1.5',
) -> pd.DataFrame:
    """Return the ``top_k`` rows whose text is semantically closest to ``query``."""
    from analyzers.backends.encoder import encode

    if column not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='similar_to', col=column))
    if not str(query or '').strip():
        raise UnknownOperationError(t('analysis.step_col_missing', op='similar_to', col='query'))
    count = max(1, int(top_k or 10))
    mask = df[column].notna() & (df[column].astype(str).str.strip() != '')
    indices = df[mask].index.tolist()
    if not indices:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    texts = [str(df.at[idx, column]).strip() for idx in indices]
    _, name = _validate(0.5, model)
    vectors = encode([str(query).strip(), *texts], model_name=name)
    scores = (vectors[1:] @ vectors[0]).astype(float)
    order = np.argsort(-scores)[:count]
    rows = [
        {
            'rank': rank,
            'row_index': indices[int(pos)],
            'text': texts[int(pos)],
            'similarity': round(float(scores[int(pos)]), 6),
        }
        for rank, pos in enumerate(order, start=1)
    ]
    logger.info(t('analysis.similar_to', n=len(rows), column=column, model=name))
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
