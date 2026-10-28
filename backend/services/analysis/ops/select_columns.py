"""The ``select_columns`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd


@staticmethod
def select_columns(df: pd.DataFrame, columns: list) -> pd.DataFrame:
    cols = [c for c in columns if c in df.columns]
    return df[cols] if cols else df
