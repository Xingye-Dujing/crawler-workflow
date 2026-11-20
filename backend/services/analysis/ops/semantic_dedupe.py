"""The ``semantic_dedupe`` step: collapse near-identical text by encoder cosine similarity.

SimHash (``dedupe_similar``) compares the *tokens* of a repost. A small sentence encoder also catches
a rewrite that keeps the meaning and drops every word, which is the case a hash cannot see. The two
steps are separate on purpose: they measure different things and a chart must not silently mix their
counts. A missing encoder refuses BY NAME -- a lexical fallback would be a different measurement
printed under this step's label.
"""

import logging

import numpy as np
import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError

logger = logging.getLogger(__name__)

#: Rows compared against the kept set in one matrix multiply. 1,000 x 384 floats is a few MB even on
#: the 16 GB laptop, and it keeps the greedy pass out of Python's per-row loop for the common case.
BLOCK = 1000


def _validate(threshold, model_name: str) -> tuple[float, str]:
    try:
        value = float(threshold)
    except (TypeError, ValueError) as exc:
        raise UnknownOperationError(t('analysis.semantic_threshold', value=threshold)) from exc
    if not 0.0 <= value <= 1.0:
        raise UnknownOperationError(t('analysis.semantic_threshold', value=threshold))
    return value, str(model_name or '').strip()


def semantic_dedupe(
    df: pd.DataFrame,
    column: str,
    model: str = 'BAAI/bge-small-zh-v1.5',
    threshold: float = 0.92,
    batch_size: int = 64,
) -> pd.DataFrame:
    """Drop a row whose meaning is already present; keep the first of each group."""
    from analyzers.backends.encoder import encode

    if column not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='semantic_dedupe', col=column))
    limit, name = _validate(threshold, model)
    work = df.copy()
    mask = work[column].notna() & (work[column].astype(str).str.strip() != '')
    indices = work[mask].index.tolist()
    if not indices:
        return work.reset_index(drop=True)
    texts = [str(work.at[idx, column]).strip() for idx in indices]
    vectors = encode(texts, model_name=name, batch_size=batch_size)

    kept = np.empty((0, vectors.shape[1]), dtype=np.float32)
    dropped: list[object] = []
    for start in range(0, len(indices), BLOCK):
        chunk = vectors[start : start + BLOCK]
        # Compare each row with the already-kept set AND with earlier rows of this same block:
        # without the second half, a duplicate pair inside the first block would both survive.
        saved = chunk @ kept.T if len(kept) else np.zeros((len(chunk), 0), dtype=np.float32)
        local = chunk @ chunk.T
        local_kept: list[int] = []
        for offset in range(len(chunk)):
            duplicate = bool(saved[offset].max(initial=-1.0) >= limit) if saved.shape[1] else False
            if not duplicate:
                duplicate = any(local[offset, previous] >= limit for previous in local_kept)
            if duplicate:
                dropped.append(indices[start + offset])
            else:
                local_kept.append(offset)
        if local_kept:
            kept = np.vstack([kept, chunk[local_kept]])
    if dropped:
        work = work.drop(index=dropped)
    logger.info(t('analysis.semantic_dedupe', n=len(dropped), column=column, model=name, threshold=limit))
    return work.reset_index(drop=True)
