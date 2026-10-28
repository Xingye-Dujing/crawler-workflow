"""The ``alert`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError, _to_datetime

logger = logging.getLogger(__name__)


def alert(
    df: pd.DataFrame,
    column: str = 'period',
    index_col: str = 'sentiment_index',
    intensity_col: str = '',
    volume_col: str = '',
    streak: int = 2,
    swing: float = 0.2,
    heating: float = 0.15,
    volume_floor: float = 0.6,
) -> pd.DataFrame:
    """Say which periods look like the start of another flare-up — and why each one qualifies.

    提前干预 in the study is an operational claim: someone has to be told while there is
    still time. The rule here is deliberately plain and every row states the number it
    checked, so a reader can disagree with the threshold rather than with a black box:

    * **转向** — ``streak`` consecutive steps each moved the sentiment index by at least
      ``swing``, in the same direction. One big jump is a reaction to an event; a run of
      them in one direction is a crowd moving.
    * **升温** — the sentiment INTENSITY rose by at least ``heating`` per step over the last
      ``streak`` steps. The index can sit near zero while both sides get louder, which is the
      二次爆发期 shape the paper describes, so the signed curve alone would miss it.
    * Both are suppressed unless the volume is still holding: ``volume`` has to be at least
      ``volume_floor`` times the mean of the previous ``streak`` periods, because a swing in
      a period with almost nobody posting is a handful of people, not a flare-up. A
      suppressed candidate is still reported as a row saying it was suppressed and by how
      much — "nothing fired" and "the swing fired but the crowd had left" are different
      answers, and only one of them is a reason to act.

    ``intensity_col`` and ``volume_col`` are read exactly like ``score_col`` on
    :meth:`sentiment_evolution`: left blank on the panel, that half of the rule is simply not
    asked for (升温 never fires, and nothing is suppressed on volume); a name that is typed
    and missing is refused, because a signal that silently stopped firing would make the
    table look like a reading of both.

    An empty result is never returned: when nothing fired the table answers with one row of
    ``未触发`` carrying the strongest value that was measured. An empty table would read as
    "not checked" — and in a monitoring step, that is the difference between calm and blind.
    """
    run = int(streak)
    if run < 1:
        raise UnknownOperationError(t('analysis.alert_streak', value=streak))
    for name, value in (('swing', swing), ('heating', heating), ('volume_floor', volume_floor)):
        number = float(value)
        if number <= 0:
            raise UnknownOperationError(t('analysis.alert_threshold', name=name, value=value))
    if volume_floor > 1.0:
        raise UnknownOperationError(t('analysis.alert_floor', value=volume_floor))
    if len(df) < run + 1:
        raise UnknownOperationError(t('analysis.alert_rows', rows=len(df), least=run + 1))
    # A name typed here that the table does not hold is refused rather than dropped: the
    # 升温 half of the rule would simply stop firing, and the table would look like a calm
    # reading of both signals.
    for name in (column, index_col, intensity_col, volume_col):
        if name and name not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='alert', col=name))

    stamps = _to_datetime(df[column])
    if stamps.isna().all():
        raise UnknownOperationError(t('analysis.forecast_dates', col=column))
    usable = [(stamp, number) for number, stamp in enumerate(stamps.tolist()) if pd.notna(stamp)]
    skipped = len(df) - len(usable)
    if skipped:
        logger.warning(t('analysis.alert_skipped', col=column, n=skipped))
    if len(usable) < run + 1:
        raise UnknownOperationError(t('analysis.alert_rows', rows=len(usable), least=run + 1))
    positions = [number for _stamp, number in sorted(usable, key=lambda pair: pair[0])]
    periods = [str(df[column].iloc[position]) for position in positions]
    indexes = [
        float(value) if pd.notna(value) else None
        for value in pd.to_numeric(df[index_col], errors='coerce').iloc[positions].tolist()
    ]
    intensities = (
        [
            float(value) if pd.notna(value) else None
            for value in pd.to_numeric(df[intensity_col], errors='coerce').iloc[positions].tolist()
        ]
        if intensity_col and intensity_col in df.columns
        else [None] * len(positions)
    )
    volumes = (
        [
            float(value) if pd.notna(value) else 0.0
            for value in pd.to_numeric(df[volume_col], errors='coerce').iloc[positions].tolist()
        ]
        if volume_col and volume_col in df.columns
        else [None] * len(positions)
    )

    rows = []
    best_swing = (None, 0.0)
    for position in range(run, len(positions)):
        if indexes[position] is None or indexes[position - run] is None:
            continue
        moves = []
        for step in range(position - run + 1, position + 1):
            here, before = indexes[step], indexes[step - 1]
            if here is None or before is None:
                moves.append(None)
                continue
            moves.append(here - before)
        if any(move is None for move in moves):
            continue
        biggest = max(abs(move) for move in moves)
        if biggest >= abs(best_swing[1]):
            best_swing = (periods[position], biggest)
        same_direction = all(move > 0 for move in moves) or all(move < 0 for move in moves)
        turned = same_direction and all(abs(move) >= float(swing) for move in moves)
        heated = False
        rise = None
        if intensities[position] is not None and intensities[position - run] is not None:
            rise = (intensities[position] - intensities[position - run]) / run
            heated = rise >= float(heating)
        if not (turned or heated):
            continue
        signal = '转向' if turned and not heated else ('升温' if heated and not turned else '转向+升温')
        value = sum(abs(move) for move in moves) / run if turned else rise
        held = True
        if volumes[position] is not None:
            previous = [volumes[step] for step in range(position - run, position) if volumes[step] is not None]
            if previous:
                baseline = sum(previous) / len(previous)
                held = volumes[position] >= float(volume_floor) * baseline
        rows.append(
            {
                'period': periods[position],
                'signal': signal if held else f'{signal}（已抑制）',
                'value': round(float(value), 4) if value is not None else None,
                'threshold': round(float(swing), 4) if turned else round(float(heating), 4),
                'reason': t(
                    'analysis.alert_reason',
                    streak=run,
                    moves='、'.join(f'{move:+.4f}' for move in moves),
                    intensity='—' if rise is None else f'{rise:+.4f}',
                    volume='未提供' if volumes[position] is None else f'{volumes[position]:.0f}',
                    held='仍在线' if held else f'低于前 {run} 期均量的 {float(volume_floor):.2f} 倍',
                ),
            }
        )
    if not rows:
        rows.append(
            {
                'period': periods[-1] if periods else '',
                'signal': '未触发',
                'value': round(float(best_swing[1]), 4) if best_swing[1] else None,
                'threshold': round(float(swing), 4),
                'reason': t(
                    'analysis.alert_none',
                    streak=run,
                    period=best_swing[0] or '—',
                    swing=float(swing),
                    heating=float(heating),
                ),
            }
        )
        logger.info(t('analysis.alert_none_log', checked=len(positions), streak=run, swing=float(swing)))
    else:
        for row in rows:
            logger.info(t('analysis.alert_fired', period=row['period'], signal=row['signal'], value=row['value']))
    return pd.DataFrame(rows)
