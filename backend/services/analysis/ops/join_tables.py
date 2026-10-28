"""The ``join_tables`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError


def join_tables(
    df: pd.DataFrame, other_df: pd.DataFrame, how: str = 'left', left_on: str = '', right_on: str = ''
) -> pd.DataFrame:
    """Merge with the right-hand table.

    Every way this can fail used to return the left table unchanged, so a
    mistyped column name looked exactly like a successful join. Each case
    now raises a message naming what is missing.
    """
    if other_df is None or len(other_df) == 0:
        raise UnknownOperationError(t('analysis.join_no_right'))
    if not left_on or not right_on:
        raise UnknownOperationError(t('analysis.join_need_keys'))
    missing = []
    if left_on not in df.columns:
        missing.append(f'{left_on} (left)')
    if right_on not in other_df.columns:
        missing.append(f'{right_on} (right)')
    if missing:
        raise UnknownOperationError(t('analysis.join_missing_cols', cols=', '.join(missing)))
    return df.merge(other_df, how=how, left_on=left_on, right_on=right_on)
