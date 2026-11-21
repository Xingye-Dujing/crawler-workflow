"""The ``fill_null`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError


def fill_null(df: pd.DataFrame, columns: list = None, value=None, method: str = None) -> pd.DataFrame:
    work = df.copy()
    wanted = [str(column) for column in (columns or [])]
    missing = [column for column in wanted if column not in work.columns]
    if missing:
        # The dangerous variant: when EVERY named column was missing, the old intersection fell
        # back to ``list(work.columns)`` and filled the whole table — a typo in 填充列 rewrote
        # every cell the user had not asked about. 留空 still means "every column", deliberately.
        raise UnknownOperationError(t('analysis.step_col_missing', op='fill_null', col='、'.join(missing)))
    cols = wanted or list(work.columns)
    # Forward/backward filling is its own method now — pandas 3 removed the
    # ``fillna(method=…)`` keyword the original code relied on.
    filler = {'ffill': 'ffill', 'pad': 'ffill', 'bfill': 'bfill', 'backfill': 'bfill'}.get(str(method or ''))
    if value is None and not filler:
        # With nothing to fill with this is a NO-OP, and it must not touch the table. ``fillna(None)``
        # is a no-op in pandas 3, but the loop below still turned every '' into NA, so a node saved
        # before the 填充值 box existed MUTATED rows (and a downstream drop_null then deleted them)
        # while the console said 填充完成. An untouched form is legal — the contract test requires
        # "may be a no-op, never a filter" — so it answers the input unchanged.
        return work
    for c in cols:
        work[c] = work[c].replace('', pd.NA)
        if filler == 'ffill':
            work[c] = work[c].ffill()
        elif filler == 'bfill':
            work[c] = work[c].bfill()
        else:
            work[c] = work[c].fillna(value)
    return work
