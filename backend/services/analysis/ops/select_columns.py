"""The ``select_columns`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError


def select_columns(df: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Keep exactly the named columns; a name the table does not hold is refused.

    The subset used to be silently intersected with the frame, so asking for 阶段 + a typo'd
    column returned a table without the typo AND without saying so — the export then looked
    like a complete answer. A partial match is still a mistake the user can fix.
    """
    wanted = [str(column) for column in (columns or [])]
    missing = [column for column in wanted if column not in df.columns]
    if missing:
        raise UnknownOperationError(t('analysis.step_col_missing', op='select_columns', col='、'.join(missing)))
    return df[wanted] if wanted else df
