"""The ``sort_rows`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd
from core.refs import as_bool

from i18n import t
from services.analysis.kernels import UnknownOperationError


def sort_rows(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
    if column not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='sort_rows', col=column))
    # A workflow file (or an executor-shaped ``/api/analysis/run`` body) may carry the switch as
    # ``'true'``/``'false'``: pandas 3 rejects that string outright, and the panel door already
    # normalises it. Reading it here makes both doors mean the same thing.
    order = as_bool(ascending, True)
    try:
        return df.sort_values(by=column, ascending=order).reset_index(drop=True)
    except TypeError as e:
        # ``sort_values`` compares cells with ``<``: a column holding 5 beside "10万" answered a bare
        # "not supported between instances of 'str' and 'int'", naming pandas' comparison instead of
        # the box the user has to fix. Every other step in this package turns the library exception
        # into a refusal that names its own parameter.
        raise UnknownOperationError(t('analysis.sort_mixed_types', op='sort_rows', col=column)) from e
