"""The ``sort_rows`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError


def sort_rows(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
    if column not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='sort_rows', col=column))
    return df.sort_values(by=column, ascending=ascending).reset_index(drop=True)
