"""The ``compare_platform`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError

logger = logging.getLogger(__name__)


def compare_platform(
    df: pd.DataFrame,
    platform_col: str = 'platform',
    value_col: str = '',
    agg: str = 'mean',
) -> pd.DataFrame:
    """One row per platform: how much was collected, and (optionally) its mean score.

    A table merged at a save node carries the ``platform`` the C1 stamp wrote on every
    parent's rows, so this reads it and groups. The count is always there; ``value_col`` is
    opt-in — name a numeric column (a sentiment score, a like count) and it appears as an
    aggregate per platform. Refusing a ``value_col`` that is not in the table, rather than
    dropping it silently, is the same rule the rest of the module obeys: a mistyped column
    must not produce a complete-looking table missing the one number that mattered.
    """
    if df.empty:
        return pd.DataFrame()
    if platform_col not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='compare_platform', col=platform_col))
    groups = df.groupby(platform_col, dropna=False)
    rows = []
    unmeasured = []
    for name, sub in groups:
        row = {platform_col: ('' if name is None else str(name)), 'n': int(len(sub))}
        if value_col:
            if value_col not in df.columns:
                raise UnknownOperationError(t('analysis.step_col_missing', op='compare_platform', col=value_col))
            # The column is named ``{value_col}_{agg}``, so the number under it MUST be that
            # aggregate. Only sum and mean are computed here; anything else (a typed 'median')
            # used to fall through to mean while still claiming 'median' in its name — a score
            # whose label misdescribes how it was produced. Refuse it by name, like value_col.
            if agg not in ('sum', 'mean'):
                raise UnknownOperationError(t('analysis.compare_agg', op='compare_platform', agg=agg))
            series = pd.to_numeric(sub[value_col], errors='coerce').dropna()
            if len(series):
                value = float(series.sum() if agg == 'sum' else series.mean())
                row[f'{value_col}_{agg}'] = round(value, 6)
            else:
                # No numeric row in this platform's group: that is "not measured", never a
                # measured zero. Writing 0.0 here made a platform with no scores look like a
                # perfect 0 and sorted to the bottom of a bar chart as if it were a finding.
                row[f'{value_col}_{agg}'] = None
                unmeasured.append(str(row[platform_col]))
        rows.append(row)
    rows.sort(key=lambda r: r['n'], reverse=True)
    if unmeasured:
        logger.warning(t('analysis.compare_unmeasured', col=value_col, platforms='、'.join(unmeasured)))
    logger.info(t('analysis.compare_done', platforms=len(rows), value=value_col or '-'))
    return pd.DataFrame(rows)
