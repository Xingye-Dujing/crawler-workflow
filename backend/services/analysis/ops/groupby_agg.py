"""The ``groupby_agg`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError


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
        return df
    metrics = list(agg_metrics or [])
    for column, _func in metrics:
        if column not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='groupby_agg', col=column))
    if order_col and order_col not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='groupby_agg', col=order_col))
    try:
        agg_map = {agg_col: (agg_col, agg_func)}
        for column, func in metrics:
            name = f'{column}_{func}'
            if name in agg_map:
                name = f'{name}_2'
            agg_map[name] = (column, func)
        if order_col:
            agg_map['_group_rank'] = (order_col, 'min')
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
            grouped = grouped.sort_values(group_col, kind='stable')
    except (TypeError, ValueError) as e:
        # e.g. sum() over a text column: report the operation instead of a
        # raw pandas error deeper in the pipeline.
        raise UnknownOperationError(f'groupby_agg({agg_func}) failed on "{agg_col}": {e}') from e
    return grouped.reset_index(drop=True)
