"""The ``suggest_stages`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError, _to_datetime
from services.analysis.topic_kernels import _whole

logger = logging.getLogger(__name__)


def suggest_stages(
    df: pd.DataFrame,
    column: str,
    min_days: int = 3,
    max_windows: int = 6,
    peak_ratio: float = 2.0,
) -> pd.DataFrame:
    """Candidate 舆情阶段 boundaries, read off the daily post-count curve.

    The study this exists for cut its five phases two ways at once: by eye on its 图 2
    (posts per day) and on the dates the police issued a notice. Only the first is
    something a table can answer, and it answers it as a PROPOSAL — the rows out of this
    step are windows to consider and the console holds the ``edges``/``labels`` text that
    pastes into :meth:`bin_time`. Nothing is applied, because a boundary this step
    invented is a boundary the researcher did not take, and 「官方通报」 is not in the
    post counts.

    Three rules make the paste safe. The last edge is the day AFTER the final window,
    because ``bin_time`` is left-closed/right-open and an edge list ending on the last
    observed day would silently lose it. A new window opens the day AFTER the valley
    between two peaks, not on the valley itself: the quietest day belongs to the phase
    that is winding down, and putting it at the head of the next one would make every
    phase look like it began in silence. And a window shorter than ``min_days`` is folded
    into the neighbour that carries more rows, because one day that happened to clear the
    floor is not a phase.

    Peak heights are reported as the RAW count of that day, not the smoothed one the
    boundary search used — 349/7624/1038/8029/2286 are the numbers the paper prints, and
    a proposal has to be comparable with them.
    """
    if column not in df.columns:
        return df
    stamps = _to_datetime(df[column])
    unparsed = int(stamps.isna().sum())
    if unparsed:
        # The same rows :meth:`bin_time` will leave blank: said once, here, rather than
        # discovered later as a phase table with fewer rows than the crawl reported.
        logger.warning(t('analysis.time_unparsed', col=column, n=unparsed))
    days = stamps.dt.normalize().value_counts().sort_index()
    if days.empty:
        raise UnknownOperationError(t('analysis.stages_sparse', days=0, least=int(min_days) * 2))
    span = pd.date_range(days.index.min(), days.index.max(), freq='D')
    counts = days.reindex(span, fill_value=0)
    if len(counts) < int(min_days) * 2:
        raise UnknownOperationError(t('analysis.stages_sparse', days=len(counts), least=int(min_days) * 2))
    ratio = float(peak_ratio)
    if ratio < 1:
        # "twice the usual day" is what a peak means here. Below 1 every ordinary day
        # clears the bar, and the curve would be cut at its own noise.
        raise UnknownOperationError(t('analysis.stages_ratio', value=peak_ratio))
    # The floor is put on the RAW day. What groups two tall days into ONE summit is the
    # smoothed curve — and the summit is then the tallest raw day inside that run, because
    # asking the raw day to be a local maximum as well is what made the real 刘学州 curve
    # answer "one phase": 01-24 (3439) and 01-25 (3183) are adjacent, so the flattened summit
    # sits between them, its own raw value is the only one tested, and every other tall day
    # of the event cancelled the same way. A run of days that clear the floor is the phase;
    # the smoothing only decides whether two neighbouring runs are really one.
    daily = counts.to_numpy()
    live = float(counts[counts > 0].median())
    floor = live * ratio
    smoothed = counts.rolling(3, center=True, min_periods=1).mean().to_numpy()
    runs: list = []
    for position in [index for index, value in enumerate(daily) if value >= floor]:
        joined = bool(runs) and position - runs[-1][1] <= 2
        if joined and any(smoothed[q] < floor for q in range(runs[-1][1], position + 1)):
            joined = False  # the curve really did fall back to an ordinary day between them
        if joined:
            runs[-1][1] = position
        else:
            runs.append([position, position])
    peak_positions = [max(range(first, last + 1), key=lambda index: daily[index]) for first, last in runs]
    if len(peak_positions) < 2:
        raise UnknownOperationError(t('analysis.stages_no_peak', ratio=peak_ratio, floor=round(floor, 1)))
    if len(peak_positions) > int(max_windows):
        # The tallest peaks are the phases; folding the rest into their neighbours is a
        # decision the user can reverse by raising the ceiling, so it is said out loud.
        folded = len(peak_positions) - int(max_windows)
        peak_positions = sorted(
            sorted(peak_positions, key=lambda position: daily[position], reverse=True)[: int(max_windows)]
        )
        logger.warning(t('analysis.stages_folded', kept=int(max_windows), dropped=folded))

    # A window's start carries the valley day that closed the previous one, so 依据 can
    # name it: a parallel list would go out of step the moment a boundary is dropped.
    starts = [(span[0], None)]
    last_open = span[-1] + pd.Timedelta(days=1)
    for left, right in zip(peak_positions[:-1], peak_positions[1:], strict=True):
        between = range(left + 1, right)
        if not between:
            continue  # two adjacent peaks share no valley, so they stay in one window
        valley = min(between, key=lambda position: smoothed[position])
        boundary = span[valley] + pd.Timedelta(days=1)
        if starts[-1][0] < boundary < last_open:
            starts.append((boundary, span[valley]))
    starts.append((last_open, None))

    # 最短窗口 is enforced here, not in the peak search: a single day that happened to clear
    # the floor is not a phase, and the proposal that keeps it would be five windows of which
    # three are one day long. Each too-short window goes to the neighbour that carries more
    # rows, and the count is printed — a proposal that quietly lost a boundary is one the
    # user cannot audit.
    shortest_allowed = _whole(min_days, 'suggest_stages', 'min_days')
    folded_windows = 0
    while len(starts) > 2 and shortest_allowed > 1:
        lengths = [(starts[k + 1][0] - starts[k][0]).days for k in range(len(starts) - 1)]
        candidate = min(range(len(lengths)), key=lambda k: (lengths[k], k))
        if lengths[candidate] >= shortest_allowed:
            break
        previous = lengths[candidate - 1] if candidate > 0 else -1
        following = lengths[candidate + 1] if candidate + 1 < len(lengths) else -1
        # Drop the boundary on the side of the smaller neighbour, so the short window joins
        # the larger one; boundary index ``candidate`` opens this window, ``candidate + 1``
        # closes it.
        drop = candidate if previous >= following and candidate > 0 else candidate + 1
        if drop >= len(starts) - 1:
            drop = candidate
        starts.pop(drop)
        folded_windows += 1
    if folded_windows:
        logger.warning(t('analysis.stages_folded_windows', n=folded_windows, days=shortest_allowed))

    rows = []
    for index in range(len(starts) - 1):
        window = counts[(counts.index >= starts[index][0]) & (counts.index < starts[index + 1][0])]
        peak_day = window.idxmax()
        valley = starts[index][1]
        rows.append(
            {
                '序号': index + 1,
                '起点': starts[index][0].strftime('%Y-%m-%d'),
                '终点': (starts[index + 1][0] - pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                '天数': len(window),
                '行数': int(window.sum()),
                '峰值日': peak_day.strftime('%Y-%m-%d'),
                '峰值计数': int(window.max()),
                '依据': (
                    t('analysis.stages_basis_first', day=starts[index][0].strftime('%Y-%m-%d'))
                    if valley is None
                    else t('analysis.stages_basis_valley', valley=valley.strftime('%Y-%m-%d'))
                ),
            }
        )
    logger.info(
        t(
            'analysis.stages_done',
            n=len(rows),
            rows=int(counts.sum()),
            span=f'{span[0].date()} … {span[-1].date()}',
        )
    )
    # Two lines because the panel holds two boxes; a merged line cannot be pasted into
    # either without editing, and the editing is where a boundary gets lost.
    logger.info(t('analysis.stages_edges', edges=', '.join(start.strftime('%Y-%m-%d') for start, _ in starts)))
    logger.info(t('analysis.stages_labels', labels=', '.join(f'阶段{number}' for number in range(1, len(rows) + 1))))
    return pd.DataFrame(rows)
