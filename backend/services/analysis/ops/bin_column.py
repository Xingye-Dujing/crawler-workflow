"""The ``bin_column`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError


@staticmethod
def bin_column(
    df: pd.DataFrame, column: str, bins: list = None, labels: list = None, new_col: str = ''
) -> pd.DataFrame:
    if column not in df.columns:
        return df
    work = df.copy()
    bin_col = new_col or f'{column}_bin'
    if bins is None:
        bins = 4
    try:
        work[bin_col] = pd.cut(pd.to_numeric(work[column], errors='coerce'), bins=bins, labels=labels)
    except Exception as e:
        # Same rule as ``column_calc`` above: a refusal, never a silent no-op. The
        # inputs that reach here are real — edges given in the wrong order, a label
        # list that does not match the number of buckets — and each of them used to
        # settle the node DONE with no new column and one line in the log file.
        raise UnknownOperationError(t('analysis.bin_failed', col=column, err=e)) from e
    return work


# ── Time dimension ──────────────────────────────────────────
#
# An event study is a study of WHEN, and nothing above answers that: `评论时间` holds
# "2024-05-02 13:45", so grouping by it groups by the minute, and a line chart of a
# per-minute series is noise. These two steps are the floor the whole analysis stands
# on — daily post counts, the phase split, and the sentiment curve are all defined
# over a calendar day rather than over a timestamp.
