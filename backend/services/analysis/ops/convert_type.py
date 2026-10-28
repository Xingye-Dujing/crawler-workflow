"""The ``convert_type`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import _to_bool, _to_datetime

logger = logging.getLogger(__name__)


@staticmethod
def convert_type(df: pd.DataFrame, column: str, dtype: str) -> pd.DataFrame:
    if column not in df.columns:
        return df
    work = df.copy()
    try:
        if dtype == 'int':
            work[column] = pd.to_numeric(work[column], errors='coerce').astype('Int64')
        elif dtype == 'float':
            work[column] = pd.to_numeric(work[column], errors='coerce')
        elif dtype == 'bool':
            work[column] = work[column].map(_to_bool)
        elif dtype == 'datetime':
            # ``format='mixed'`` is not a fix for a wrong guess, it is the guess being *said out
            # loud*: without a format pandas tries one for the whole column, fails on a table
            # whose rows came from different sources, and then parses every element individually
            # with dateutil anyway — while warning that it did. Declaring the per-element path
            # keeps the behaviour identical and removes the noise the user cannot act on
            # (pandas >= 2.0; the project venv carries 3.x).
            # ``format='mixed'`` is not a fix for a wrong guess, it is the guess being *said out
            # loud*: without a format pandas tries one for the whole column, fails on a table
            # whose rows came from different sources, and then parses every element individually
            # with dateutil anyway — while warning that it did. Measured, the undeclared path was
            # worse than noisy: on ``['2024-01-01', '2024-01-02 03:04:05']`` it inferred
            # ``%Y-%m-%d`` from row one and coerced row two to ``NaT``, so the timestamps simply
            # disappeared from the user's table. Declaring the per-element path keeps every row
            # and removes the noise the user cannot act on (pandas >= 2.0; the venv has 3.x).
            #
            # Through ``_to_datetime`` rather than pandas directly: this is the second door onto
            # the same column, and a 发布时间 that parses in ``extract_time`` while ``convert_type``
            # answers NaT for it is the same defect wearing a different control.
            work[column] = _to_datetime(work[column])
        else:
            work[column] = work[column].astype(str)
    except (ValueError, TypeError) as e:
        logger.warning(t('analysis.type_convert_failed', col=column, dtype=dtype, err=e))
    return work


# ── New operations (Phase 2) ────────────────────────────────
