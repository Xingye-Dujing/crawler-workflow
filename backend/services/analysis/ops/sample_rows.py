"""The ``sample_rows`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from services.analysis.kernels import _stable_seed


@staticmethod
def sample_rows(df: pd.DataFrame, n: int = None, frac: float = None, seed: int = None) -> pd.DataFrame:
    # Neither bound configured: pandas' own default is n=1, which silently
    # threw away every other row. Ask for nothing, change nothing.
    if n is None and frac is None:
        return df
    # An explicit seed is authoritative; a blank one (the settings panel
    # stores every field as a string, so '' is "left empty") is treated as
    # absent. Without either, the frame's own hash decides — see
    # ``_stable_seed``: the sample stays reproducible for the same input.
    raw_seed = str(seed).strip() if seed is not None else ''
    state = int(float(raw_seed)) if raw_seed else _stable_seed(df)
    # Both configured: an explicit row count is the more specific request.
    if n is not None:
        n = max(0, int(n))
        if n >= len(df):
            return df
        return df.sample(n=n, random_state=state).reset_index(drop=True)
    frac = min(max(float(frac), 0.0), 1.0)
    if frac >= 1.0:
        return df
    return df.sample(frac=frac, random_state=state).reset_index(drop=True)
