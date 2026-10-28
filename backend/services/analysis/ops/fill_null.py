"""The ``fill_null`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd


@staticmethod
def fill_null(df: pd.DataFrame, columns: list = None, value=None, method: str = None) -> pd.DataFrame:
    work = df.copy()
    cols = [c for c in (columns or []) if c in work.columns] or list(work.columns)
    # Forward/backward filling is its own method now — pandas 3 removed the
    # ``fillna(method=…)`` keyword the original code relied on.
    filler = {'ffill': 'ffill', 'pad': 'ffill', 'bfill': 'bfill', 'backfill': 'bfill'}.get(str(method or ''))
    for c in cols:
        work[c] = work[c].replace('', pd.NA)
        if filler == 'ffill':
            work[c] = work[c].ffill()
        elif filler == 'bfill':
            work[c] = work[c].bfill()
        else:
            work[c] = work[c].fillna(value)
    return work
