"""The ``rename_columns`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd


@staticmethod
def rename_columns(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    return df.rename(columns=mapping)
