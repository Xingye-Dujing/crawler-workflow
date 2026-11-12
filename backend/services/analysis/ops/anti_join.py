"""The ``anti_join`` step, one module of the analysis op registry (see ops/__init__.py).

内容去重: the left table's rows whose key does NOT appear in the right table's column stay;
the ones that do are dropped. ``keep='keep'`` answers the mirror question (semi-join) with
the same machinery, so "哪些内容重复了" and "哪些内容还没出现过" are one operation with a
switch rather than two half-implementations.

The second table is the node's second incoming connection (see
``services.analysis.matching.STEP_TWO_TABLE``). ``swap_tables`` exchanges the two sides
inside this step, because the interesting choice — WHICH table is filtered — is a property
of the question, not of the order the wires happen to be recorded in.
"""

import logging

import pandas as pd
from core.refs import as_bool, split_names

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.matching import (
    KEEP_MODES,
    MATCH_MODES,
    SIMILAR_DEFAULT_DISTANCE,
    clean_cell,
    match_mask,
    row_key,
)

logger = logging.getLogger(__name__)


def _distance(value) -> int:
    if value is None or str(value).strip() == '':
        return SIMILAR_DEFAULT_DISTANCE
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise UnknownOperationError(t('analysis.match_distance_type', value=value)) from exc


def _similar_key(row: dict, columns) -> str:
    """One row's composite text for ``similar`` matching, or ``''`` when any part is blank.

    The same identity rule :func:`row_key` applies to every other mode: a partially blank
    tuple is incomplete, not a weaker key. ``clean_cell`` also folds ``None``/``NaN`` to ``''``
    — ``str(nan)`` would otherwise become the literal token 'nan', a fingerprint every empty
    cell would share.
    """
    parts = [clean_cell(row.get(name)) for name in columns]
    return ' '.join(parts) if parts and all(parts) else ''


def anti_join(
    df: pd.DataFrame,
    other_df: pd.DataFrame = None,
    left_on: str = '',
    right_on: str = '',
    mode: str = 'trim',
    keep: str = 'exclude',
    ignore_case: bool = False,
    max_distance=SIMILAR_DEFAULT_DISTANCE,
    swap_tables: bool = False,
) -> pd.DataFrame:
    """Keep (or drop) the left rows whose key appears in the right table's column.

    Named refusals, never a silently untouched table:

    * no second table at all — the caller (a node with one wire, an API caller) is told the
      step needs two;
    * an unknown ``mode``/``keep`` name, or one column list empty / of a different length
      from the other side;
    * a named column that the table does not hold.

    The output is the left table's own rows and columns in their original order — no right
    column is merged in — so a downstream node keeps reading the names it always read. A
    row with a blank key is never matched (two absences are not "the same content"), and the
    counts of those rows are logged so the number is visible rather than silent.
    """
    if other_df is None:
        raise UnknownOperationError(t('analysis.two_table_no_right', op='anti_join'))
    if mode not in MATCH_MODES:
        raise UnknownOperationError(t('analysis.match_bad_mode', mode=mode, allowed=', '.join(MATCH_MODES)))
    if keep not in KEEP_MODES:
        raise UnknownOperationError(
            t('analysis.bad_option', op='anti_join', param='keep', value=keep, allowed=', '.join(KEEP_MODES))
        )

    left_columns = split_names(left_on)
    right_columns = split_names(right_on)
    if as_bool(swap_tables, False):
        # Swapping here (not in the node executor) keeps ``run_pipeline`` a plain chain: the
        # step still consumes one frame and returns one, and the caller's "left" is simply
        # not what this question filters.
        df, other_df = other_df, df
        left_columns, right_columns = right_columns, left_columns
    if not left_columns or not right_columns:
        raise UnknownOperationError(t('analysis.two_table_need_keys', op='anti_join'))
    if len(left_columns) != len(right_columns):
        raise UnknownOperationError(
            t(
                'analysis.anti_join_key_count',
                left='、'.join(left_columns),
                right='、'.join(right_columns),
            )
        )
    missing_left = [name for name in left_columns if name not in df.columns]
    if missing_left:
        raise UnknownOperationError(t('analysis.anti_join_left_missing', cols='、'.join(missing_left)))
    missing_right = [name for name in right_columns if name not in other_df.columns]
    if missing_right:
        raise UnknownOperationError(t('analysis.anti_join_right_missing', cols='、'.join(missing_right)))

    ignore_case = as_bool(ignore_case, False)
    left_records = df.to_dict('records')
    right_records = other_df.to_dict('records')
    if mode == 'similar':
        left_values = [_similar_key(row, left_columns) for row in left_records]
        right_values = [_similar_key(row, right_columns) for row in right_records]
        mask, stats = match_mask(left_values, right_values, mode=mode, max_distance=_distance(max_distance))
    else:
        # Composite keys go through ``row_key``: two columns of one row are ONE identity,
        # and a partially blank tuple never matches anything.
        right_keys = {row_key(row, right_columns, mode, ignore_case) for row in right_records}
        right_keys.discard('')
        left_keys = [row_key(row, left_columns, mode, ignore_case) for row in left_records]
        mask = [bool(key) and key in right_keys for key in left_keys]
        stats = {
            'left_blank': sum(1 for key in left_keys if not key),
            'right_blank': sum(1 for row in right_records if not row_key(row, right_columns, mode, ignore_case)),
            'right_keys': len(right_keys),
        }

    chosen = mask if keep == 'keep' else [not matched for matched in mask]
    result = df.loc[pd.Series(chosen, index=df.index)].reset_index(drop=True)
    kept = int(sum(1 for flag in chosen if flag))
    logger.info(
        t(
            'analysis.anti_join_done',
            rows=len(df),
            kept=kept,
            removed=len(df) - kept,
            right_keys=stats.get('right_keys', 0),
            blank=stats.get('left_blank', 0),
            right_blank=stats.get('right_blank', 0),
            mode=mode,
            keep=keep,
        )
    )
    return result
