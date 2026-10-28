"""The ``drop_null`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd


@staticmethod
def drop_null(df: pd.DataFrame, columns: list = None, how: str = 'any') -> pd.DataFrame:
    subset = [c for c in (columns or []) if c in df.columns] or None
    work = df.copy()
    if subset:
        work[subset] = work[subset].replace('', pd.NA)
    else:
        work = work.replace('', pd.NA)
    return work.dropna(subset=subset, how=how).reset_index(drop=True)
