"""The ``sort_rows`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd


@staticmethod
def sort_rows(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
    if column not in df.columns:
        return df
    return df.sort_values(by=column, ascending=ascending).reset_index(drop=True)
