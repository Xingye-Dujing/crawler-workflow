"""The ``forecast`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.contracts import FORECAST_METHODS
from services.analysis.kernels import UnknownOperationError, _to_datetime
from services.analysis.topic_kernels import _forecast_row, _standard_deviation

logger = logging.getLogger(__name__)


def forecast(
    df: pd.DataFrame,
    column: str = 'period',
    value_col: str = 'sentiment_index',
    method: str = 'moving_average',
    horizon: int = 3,
    window: int = 3,
    alpha: float = 0.5,
    beta: float = 0.3,
    min_periods: int = 4,
    season: int = 7,
    gamma: float = 0.35,
) -> pd.DataFrame:
    """Extrapolate the sentiment CURVE a few periods ahead.

    The study's closing argument is that a curve like this one could have been used to
    intervene before the second flare-up, so the question worth asking of
    :meth:`sentiment_evolution` is what the next few periods look like if nothing changes.
    This is an extrapolation of a SHAPE, not a prediction of events: no model here knows
    about a police notification, and the honest reading of the band is "where this curve's
    own momentum and wobble put the next points", not "what will happen".

    Two methods, both computed here rather than imported:

    ``moving_average`` repeats the mean of the last ``window`` observations and keeps the
    band FLAT, because a moving average has no trend to add and no more uncertainty the
    further out it goes — a widening band here would be theatre.

    ``holt`` is Holt's two-parameter linear method (level + trend), written out rather than
    taken from a statsmodels dependency, and its band grows with ``sqrt(horizon)`` because a
    trend extrapolated further really is less certain. The band uses the standard deviation
    of the fitted one-step errors, which is the only uncertainty this model measured.

    Two seasonal methods, also hand-written (no statsmodels): ``seasonal_naive`` repeats the
    value ``season`` periods back (a flat seasonal carry, band = the spread of those seasonal
    errors), and ``holt_winters`` is additive Holt-Winters (level + trend + a length-``season``
    cycle), its band growing with ``sqrt(horizon)`` like Holt. Both need ``season`` periods of
    history to say anything, so a series shorter than that is refused by name.

    History is kept in the same table: every past period comes back with its ``actual`` and
    the one-step-ahead ``predicted`` the model would have made from the period before it, at
    ``horizon`` 0, so a chart shows the fit and the forecast as one line rather than two
    tables the user has to join. A future row has ``actual`` empty — it has not happened.

    Equal spacing is checked, not assumed: with missing days the "next period" the step
    names on the axis is not the next day, so the modal gap is used for the labels and the
    deviating count is logged. The input has to be dates for any of that to mean anything,
    which is why a phase NAME column (发酵期…) is refused instead of being numbered 1, 2, 3.
    """
    steps = int(horizon)
    for name in (column, value_col):
        # Refused by name rather than reaching pandas, which answers a missing column with a
        # bare KeyError: the gate catches this on both doors, but a hand-called step should
        # still say which of its own inputs is gone.
        if name not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='forecast', col=name))
    if steps < 1:
        raise UnknownOperationError(t('analysis.forecast_horizon', value=horizon))
    look = int(window)
    if look < 2:
        raise UnknownOperationError(t('analysis.forecast_window', value=window))
    for name, value in (('alpha', alpha), ('beta', beta)):
        number = float(value)
        if not 0.0 < number < 1.0:
            raise UnknownOperationError(t('analysis.forecast_smooth', name=name, value=value))
    season_len = int(season)
    if method in ('seasonal_naive', 'holt_winters') and season_len < 2:
        raise UnknownOperationError(t('analysis.forecast_season', value=season))
    if method == 'holt_winters':
        g = float(gamma)
        if not 0.0 < g < 1.0:
            raise UnknownOperationError(t('analysis.forecast_smooth', name='gamma', value=gamma))
    floor = int(min_periods)

    stamps = _to_datetime(df[column])
    if stamps.isna().all():
        raise UnknownOperationError(t('analysis.forecast_dates', col=column))
    work = pd.DataFrame({'stamp': stamps, 'actual': pd.to_numeric(df[value_col], errors='coerce')})
    work = work[work['stamp'].notna() & work['actual'].notna()].sort_values('stamp', kind='stable')
    if len(work) < floor:
        raise UnknownOperationError(t('analysis.forecast_rows', rows=len(work), least=floor))
    if len(work) < look + 1:
        raise UnknownOperationError(t('analysis.forecast_window_rows', rows=len(work), window=look))
    doubled = work['stamp'].duplicated()
    if doubled.any():
        # Two rows for one day would be read as two steps of a trend and quietly flatten or
        # steepen it, so the duplicate is the finding here, not something to average away.
        raise UnknownOperationError(
            t(
                'analysis.forecast_duplicate',
                col=column,
                days='、'.join(str(value.date()) for value in work.loc[doubled, 'stamp'].head(5)),
            )
        )
    gaps = work['stamp'].diff().dropna()
    sizes = gaps.dt.days.value_counts()
    modal = int(sizes.index[0])
    uneven = int(sizes.drop(index=modal).sum()) if len(sizes) > 1 else 0
    if uneven:
        logger.warning(t('analysis.forecast_uneven', steps=uneven, gap=modal, rows=len(work)))
    stamps_in = work['stamp'].tolist()
    values = [float(value) for value in work['actual'].tolist()]
    centres: list = []
    spreads: list = []
    future: list = []
    if method == 'moving_average':
        for position in range(len(values)):
            if position < look:
                # Nothing is claimed for the first ``window`` points: the estimator has not
                # seen enough of the curve yet, and a value here would be a guess wearing
                # the same column heading as the forecasts.
                centres.append(None)
                spreads.append(None)
                continue
            past = values[position - look : position]
            centres.append(sum(past) / look)
            spreads.append(1.96 * _standard_deviation(past))
        tail = values[-look:]
        centre = sum(tail) / look
        band = 1.96 * _standard_deviation(tail)
        # A moving average has no trend, so the forecast is flat and the band stays the same
        # width: widening it here would be theatre about a model that adds nothing each step.
        future = [(offset, centre, band) for offset in range(1, steps + 1)]
    elif method == 'holt':
        level, slope = values[0], 0.0
        errors: list = []
        a = float(alpha)
        b = float(beta)
        for position, value in enumerate(values):
            if position == 0:
                centres.append(None)
                spreads.append(None)
                continue
            predicted = level + slope
            errors.append(value - predicted)
            centres.append(predicted)
            # No band on a fitted point: an interval around a value already observed would
            # be a second, wider answer to a question this table answers once.
            spreads.append(None)
            previous = level
            level = a * value + (1.0 - a) * (level + slope)
            slope = b * (level - previous) + (1.0 - b) * slope
        spread = 1.96 * _standard_deviation(errors)
        # The band grows with the square root of the horizon because a trend carried further
        # really is less certain, and the only uncertainty this model measured is the
        # standard deviation of its own one-step errors.
        future = [(offset, level + offset * slope, spread * (offset**0.5)) for offset in range(1, steps + 1)]
    elif method == 'seasonal_naive':
        m = season_len
        if len(values) < m:
            raise UnknownOperationError(t('analysis.forecast_season_rows', rows=len(values), season=m))
        s_errors = [values[i] - values[i - m] for i in range(m, len(values))]
        s_spread = 1.96 * _standard_deviation(s_errors) if s_errors else 0.0
        for position in range(len(values)):
            if position < m:
                centres.append(None)
                spreads.append(None)
            else:
                # The seasonal naive forecast of a period is simply the value one season back.
                centres.append(values[position - m])
                spreads.append(s_spread)
        tail_season = values[-m:]
        future = [(offset, tail_season[(offset - 1) % m], s_spread) for offset in range(1, steps + 1)]
    elif method == 'holt_winters':
        m = season_len
        if len(values) < 2 * m:
            raise UnknownOperationError(t('analysis.forecast_season_rows', rows=len(values), season=m))
        hw_a, hw_b, hw_g = float(alpha), float(beta), float(gamma)
        level = sum(values[:m]) / m
        slope = (sum(values[m : 2 * m]) - sum(values[:m])) / (m * m)
        seasonal = [values[j] - level for j in range(m)]
        hw_errors: list = []
        for position, value in enumerate(values):
            si = position % m
            predicted = level + slope + seasonal[si]
            if position < m:
                # The first cycle only seeds the seasonal components; nothing is claimed as fit.
                centres.append(None)
                spreads.append(None)
            else:
                centres.append(predicted)
                hw_errors.append(value - predicted)
                spreads.append(None)
            prev_seasonal = seasonal[si]
            new_level = hw_a * (value - prev_seasonal) + (1.0 - hw_a) * (level + slope)
            new_slope = hw_b * (new_level - level) + (1.0 - hw_b) * slope
            seasonal[si] = hw_g * (value - new_level) + (1.0 - hw_g) * prev_seasonal
            level, slope = new_level, new_slope
        hw_spread = 1.96 * _standard_deviation(hw_errors) if hw_errors else 0.0
        future = []
        for offset in range(1, steps + 1):
            si = (len(values) + offset - 1) % m
            centre = level + offset * slope + seasonal[si]
            future.append((offset, centre, hw_spread * (offset**0.5)))
    else:
        raise UnknownOperationError(
            t(
                'analysis.bad_option',
                op='forecast',
                param='method',
                value=method,
                allowed=', '.join(FORECAST_METHODS),
            )
        )

    rows = [
        _forecast_row(stamps_in[position], values[position], centres[position], spreads[position], 0)
        for position in range(len(values))
    ]
    final = stamps_in[-1]
    for offset, centre, band in future:
        rows.append(_forecast_row(final + pd.Timedelta(days=modal * offset), None, centre, band, offset))
    logger.info(
        t(
            'analysis.forecast_done',
            method=method,
            rows=len(work),
            horizon=steps,
            gap=modal,
            last=str(work['stamp'].iloc[-1].date()),
        )
    )
    return pd.DataFrame(rows)
