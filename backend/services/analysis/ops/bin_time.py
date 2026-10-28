"""The ``bin_time`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError, _blank, _to_datetime

logger = logging.getLogger(__name__)


@staticmethod
def bin_time(
    df: pd.DataFrame,
    column: str,
    edges: list = None,
    labels: list = None,
    new_col: str = '阶段',
    order_new_col: str = '',
) -> pd.DataFrame:
    """Cut a timestamp column into named windows — the event's lifecycle phases.

    ``edges`` are the boundaries, left-closed and right-open: five phases need SIX
    edges, and the last one is the day after the final phase ends. That is stated
    rather than smoothed over because the alternative reading ("edges are the phase
    ends") silently shifts every row on a boundary day into the neighbouring phase —
    and those are exactly the days an event study is about.

    Which is why the comparison runs on the calendar DAY: a row stamped 23:59 on the
    day before a boundary belongs to the earlier phase, not to the next one by two
    minutes.

    ``order_new_col`` adds the phase's POSITION as a number (first phase = 1). The label
    column alone cannot survive the node boundary — ``pd.DataFrame(records)`` turns the
    ordered categorical into plain strings, and the code-point order of Chinese phase
    names puts 二次爆发期 first, so every 各阶段 chart and table would read the lifecycle
    backwards. A number is the only spelling of the order that survives the round trip;
    分阶段 LDA writes its own ``stage_order`` for the same reason. Left blank, no column is
    added and this step behaves exactly as it always did.
    """
    if column not in df.columns:
        return df
    work = df.copy()
    bounds = [value for value in (edges or []) if not _blank(value)]
    names = [str(name).strip() for name in (labels or []) if str(name).strip()]
    if len(bounds) < 2:
        raise UnknownOperationError(t('analysis.need_param', op='bin_time', param='edges'))
    if len(names) != len(bounds) - 1:
        raise UnknownOperationError(t('analysis.time_bin_labels', edges=len(bounds), labels=len(names)))
    parsed = pd.to_datetime(pd.Series(bounds), errors='coerce', format='mixed')
    if parsed.isna().any():
        bad = [bounds[index] for index, ok in enumerate(parsed.notna()) if not ok]
        raise UnknownOperationError(t('analysis.time_bin_edges', edges=', '.join(str(x) for x in bad)))
    if not parsed.is_monotonic_increasing:
        # pd.cut would raise on unsorted bins with pandas' own wording; naming the
        # parameter is what lets the user find the box that holds it.
        raise UnknownOperationError(t('analysis.time_bin_order', op='bin_time'))
    stamps = _to_datetime(work[column])
    unparsed = int(stamps.isna().sum())
    work[new_col] = pd.cut(stamps.dt.normalize(), bins=parsed, labels=names, right=False)
    if order_new_col and str(order_new_col).strip():
        order_name = str(order_new_col).strip()
        # The numeric position survives what the label cannot: pandas gives an unbinned row
        # no category at all, so a missing phase stays missing here instead of being ranked.
        positions = {name: number + 1 for number, name in enumerate(names)}
        work[order_name] = pd.Series(
            [
                positions.get(str(value).strip()) if str(value).strip() in positions else None
                for value in work[new_col].tolist()
            ],
            index=work.index,
            dtype='object',
        )
    if unparsed:
        logger.warning(t('analysis.time_unparsed', col=column, n=unparsed))
    counts = work[new_col].value_counts()
    detail = '、'.join(f'{name} {int(counts.get(name, 0))} 行' for name in names)
    logger.info(t('analysis.time_binned', col=new_col, detail=detail))
    return work


# ── Topic modelling ─────────────────────────────────────────
