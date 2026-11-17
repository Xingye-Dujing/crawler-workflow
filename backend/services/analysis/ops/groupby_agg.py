"""The ``groupby_agg`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError, _to_datetime

logger = logging.getLogger(__name__)

#: The position column a phase step writes for its own labels (``topic_by_stage``, ``bin_time``).
#: Named here as a vocabulary, never as a guess about VALUES: when one is present it IS the
#: lifecycle order, and a group-by should not make the user repeat it in 排序依据.
STAGE_ORDER_COLUMNS = ('阶段序号', 'stage_order', '阶段排序')


def groupby_agg(
    df: pd.DataFrame,
    group_col: str,
    agg_col: str,
    agg_func: str = 'sum',
    order_col: str = '',
    agg_metrics: list | None = None,
) -> pd.DataFrame:
    """One row per group with the aggregate(s) beside it.

    ``agg_col``/``agg_func`` is the primary metric and its output column keeps ``agg_col``'s own
    name (the contract existing charts read). ``agg_metrics`` — a list of (column, func) pairs —
    adds one column apiece named ``column_func``, without disturbing the primary one.

    ``order_col`` says which column decides the result's ROW ORDER. Left blank, groups come
    back sorted by their own name — right for 'YYYY-MM-DD' days, wrong for Chinese phase
    labels, where 二次爆发期 sorts before 发酵期 by code point and a 各阶段 table then reads
    the lifecycle backwards while looking complete. The number 划分阶段's 阶段序号 writes is
    what fixes it, and it is dropped afterwards: a helper column left in the export would be
    a second opinion about the same group.
    """
    if group_col not in df.columns or agg_col not in df.columns:
        # A missing key used to hand the row-level table back as if it were the aggregate,
        # so every downstream chart read un-grouped rows under a grouped label.
        missing = group_col if group_col not in df.columns else agg_col
        raise UnknownOperationError(t('analysis.step_col_missing', op='groupby_agg', col=missing))
    metrics = list(agg_metrics or [])
    for column, _func in metrics:
        if column not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='groupby_agg', col=column))
    if order_col and order_col not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='groupby_agg', col=order_col))
    if not order_col:
        # The phase marker the 分阶段 step writes (AGENTS: a phase-table step must emit its
        # position column) is the order, so the group-by does not need the user to name it
        # again — and a phase table that crossed a node boundary keeps its lifecycle.
        order_col = next((name for name in STAGE_ORDER_COLUMNS if name in df.columns and name != group_col), '')
    try:
        agg_map = {agg_col: (agg_col, agg_func)}
        for column, func in metrics:
            name = f'{column}_{func}'
            if name in agg_map:
                name = f'{name}_2'
            agg_map[name] = (column, func)
        if order_col:
            agg_map['_group_rank'] = (order_col, 'min')
        dropped_blank = int(df[group_col].isna().sum())
        if dropped_blank:
            # ``dropna=True`` drops them without a word, and the table that loses a phase reads
            # as if the corpus had no such rows. One named line, not a silent hole.
            logger.warning(t('analysis.groupby_dropped_blank', op='groupby_agg', col=group_col, n=dropped_blank))
        grouped = df.groupby(group_col, dropna=True).agg(**agg_map).reset_index()
        if order_col:
            ranks = pd.to_numeric(grouped['_group_rank'], errors='coerce')
            adrift = [str(name) for name, rank in zip(grouped[group_col], ranks, strict=True) if pd.isna(rank)]
            if adrift:
                # A group whose every row lacks a rank has no position; appending it at the
                # end would invent one.
                raise UnknownOperationError(
                    t('analysis.stage_order_unranked', op='groupby_agg', col=order_col, stages='、'.join(adrift))
                )
            grouped = grouped.assign(_group_rank=ranks).sort_values('_group_rank', kind='stable')
            grouped = grouped.drop(columns=['_group_rank'])
        else:
            grouped = _in_phase_order(df, grouped, group_col)
    except UnknownOperationError:
        # A refusal this module already worded must not be relabelled as "groupby_agg failed":
        # the reason (an unranked phase, a group column with no order) is the actionable half.
        raise
    except (TypeError, ValueError) as e:
        # e.g. sum() over a text column: report the operation instead of a
        # raw pandas error deeper in the pipeline.
        raise UnknownOperationError(f'groupby_agg({agg_func}) failed on "{agg_col}": {e}') from e
    return grouped.reset_index(drop=True)


def _in_phase_order(df: pd.DataFrame, grouped: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Sort the grouped table by what the group column MEANS where it can be known.

    Sorting by the raw name is right for days and for a number, and wrong for Chinese phase
    labels: code points put 二次爆发期 before 发酵期, so a complete-looking 各阶段 table ran the
    lifecycle backwards. A column that parses WHOLE as a date or a number sorts itself; a phase
    column takes the ordered categorical the same-node 分阶段 step wrote (``df``, not
    ``grouped`` — the categorical is the source's). What is left is either an ordinary group
    (作者, 城市), where a name sort IS the answer, or a phase column that lost its categorical
    at the node boundary — indistinguishable from here, so the fallback is announced with the
    fix instead of refusing, which would take every ordinary group-by down with it.
    """
    if len(grouped) <= 1:
        return grouped
    values = grouped[group_col]
    stamps = _to_datetime(values)
    if stamps.notna().all():
        return grouped.assign(_sort=stamps).sort_values('_sort', kind='stable').drop(columns=['_sort'])
    ranks = pd.to_numeric(values, errors='coerce')
    if ranks.notna().all():
        return grouped.assign(_sort=ranks).sort_values('_sort', kind='stable').drop(columns=['_sort'])
    from services.analysis.topic_kernels import _stage_order

    try:
        order = _stage_order(df, group_col, '', op='groupby_agg')
    except UnknownOperationError:
        # An ordinary group (作者, 城市) has no lifecycle to honour and a name sort IS the answer.
        return grouped.sort_values(group_col, kind='stable')
    positions = {str(name): index for index, name in enumerate(order)}
    unknown = [str(name) for name in values if str(name) not in positions]
    if unknown:
        raise UnknownOperationError(
            t('analysis.stage_order_unranked', op='groupby_agg', col=group_col, stages='、'.join(unknown))
        )
    return grouped.assign(_sort=values.map(positions)).sort_values('_sort', kind='stable').drop(columns=['_sort'])
