"""The ``strip_whitespace`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd


@staticmethod
def strip_whitespace(df: pd.DataFrame, columns: list = None) -> pd.DataFrame:
    work = df.copy()
    # is_string_dtype() instead of select_dtypes('object'): pandas 3 stores
    # text as 'str' (not 'object') and the old call is deprecated.
    text_cols = [c for c in work.columns if pd.api.types.is_string_dtype(work[c])]
    cols = [c for c in (columns or []) if c in work.columns] or text_cols
    for c in cols:
        # Strip only real strings: astype(str) would rewrite every missing
        # value as the text 'None'/'nan'.
        work[c] = work[c].map(lambda v: v.strip() if isinstance(v, str) else v)
    return work
