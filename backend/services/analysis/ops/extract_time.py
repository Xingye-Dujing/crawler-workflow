"""The ``extract_time`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import TIME_PARTS, UnknownOperationError, _to_datetime

logger = logging.getLogger(__name__)


def extract_time(df: pd.DataFrame, column: str, new_col: str = '日期', part: str = 'date') -> pd.DataFrame:
    """Derive one calendar part of a timestamp column.

    ``date`` answers with ``YYYY-MM-DD`` text rather than a date object: the value is
    grouped, exported and charted, and a lexical sort of ISO dates IS a chronological
    sort, so the text form costs nothing and survives every serialisation in this
    pipeline. The other parts answer with a number.

    A timestamp the site handed back as a relative label ("09月26日 21:00" is what Weibo
    shows when it has no year) cannot be turned into a calendar day, and guessing this
    year for it would move rows between phases. Those rows are left EMPTY and counted
    in the console — an empty is not a date, and pandas' own ``groupby`` then drops them
    instead of inventing a 1970 bucket for them.
    """
    if column not in df.columns:
        return df
    if part not in TIME_PARTS:
        raise UnknownOperationError(
            t('analysis.bad_option', op='extract_time', param='part', value=part, allowed=', '.join(TIME_PARTS))
        )
    work = df.copy()
    stamps = _to_datetime(work[column])
    unparsed = int(stamps.isna().sum())
    if part == 'date':
        work[new_col] = stamps.dt.strftime('%Y-%m-%d')
        # strftime answers 'NaT' for a missing stamp, and a column whose missing value
        # is the text "NaT" groups those rows together as if they were one day.
        work.loc[stamps.isna(), new_col] = pd.NA
    else:
        work[new_col] = getattr(stamps.dt, part)
    if unparsed:
        logger.warning(t('analysis.time_unparsed', col=column, n=unparsed))
    return work
