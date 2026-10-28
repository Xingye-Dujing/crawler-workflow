"""The ``column_calc`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError


@staticmethod
def column_calc(df: pd.DataFrame, new_col: str, expr: str) -> pd.DataFrame:
    """Add a computed column, or refuse with the expression that could not run.

    This used to log a warning and hand the table back UNCHANGED, which is the one
    outcome this project forbids everywhere else: the node settled DONE, the column the
    user named was never created, and the only trace was a line in ``logs/``. A
    mistyped column name then surfaced two nodes later as a chart with nothing in it —
    on a run that had already paid for its crawl.

    The column name inside an expression is the reason this could not simply be added
    to :data:`STEP_PARAMS`: no table of column names can validate a formula, so the
    check has to be the evaluation itself. Which means the refusal has to BE the
    evaluation's failure, carrying the expression the user typed.
    """
    if not new_col or not expr:
        return df
    work = df.copy()
    try:
        work[new_col] = work.eval(expr)
    except Exception as e:
        raise UnknownOperationError(t('analysis.calc_failed', col=new_col, expr=expr, err=e)) from e
    return work
