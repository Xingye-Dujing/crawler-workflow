"""The ``filter_rows`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError, _checked_pattern


def _numeric_view(series: pd.Series) -> pd.Series | None:
    """``series`` as numbers, or None when that would mean inventing rows.

    The admission test is "every non-null value reads as a number": a partially numeric
    column is a text column with numbers in it, and coercing it would silently drop the
    rows the user can see in the preview.
    """
    numeric = pd.to_numeric(series, errors='coerce')
    filled = series.notna()
    if filled.any() and numeric.notna().sum() == filled.sum():
        return numeric
    return None


def _as_float(value) -> float | None:
    """``value`` as a number, or None when it is not one (a text operand stays a text operand)."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _numbers(values: list) -> list:
    """``values`` as floats when every one of them reads as a number, else unchanged."""
    numbers = []
    for value in values:
        try:
            numbers.append(float(str(value).strip()))
        except (TypeError, ValueError):
            return values
    return numbers


def _split_values(value) -> list:
    """``in``/``not_in`` operands: a real sequence stays one, text splits on commas."""
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [part.strip() for part in str(value).split(',')]


def filter_rows(df: pd.DataFrame, column: str, op: str, value) -> pd.DataFrame:
    if column not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='filter_rows', col=column))
    s = df[column]
    if op == 'eq':
        # The panel stores its operand as TEXT, and ``df['点赞数'] == '25'`` is False for every
        # row (pandas answers no error and no warning). A filter whose matches the user can see
        # in the preview came back as an empty table and reported itself DONE. Compare both ways.
        numeric = _numeric_view(s)
        number = _as_float(value)
        mask = s == value
        if numeric is not None and number is not None:
            mask = mask | (numeric == number)
    elif op == 'ne':
        numeric = _numeric_view(s)
        number = _as_float(value)
        mask = s != value
        if numeric is not None and number is not None:
            # Both must miss: '25' and 25 are the same row to the person who typed it, and a
            # text operand that reads as a number must not be dropped from the comparison.
            mask = mask & (numeric != number)
    elif op in ('gt', 'gte', 'lt', 'lte'):
        try:
            bound = float(value)
        except (TypeError, ValueError) as e:
            # Without this the pipeline died inside float() with a bare
            # "could not convert string to float".
            raise UnknownOperationError(f'"{op}" needs a numeric value, got: {value!r}') from e
        numeric = pd.to_numeric(s, errors='coerce')
        mask = {
            'gt': numeric > bound,
            'gte': numeric >= bound,
            'lt': numeric < bound,
            'lte': numeric <= bound,
        }[op]
    elif op == 'contains':
        mask = s.astype(str).str.contains(_checked_pattern(op, value), na=False)
    elif op == 'not_contains':
        mask = ~s.astype(str).str.contains(_checked_pattern(op, value), na=False)
    elif op == 'in':
        values = _split_values(value)
        mask = s.isin(values)
        numeric = _numeric_view(s)
        if numeric is not None:
            mask = mask | numeric.isin(_numbers(values))
    elif op == 'not_in':
        values = _split_values(value)
        mask = ~s.isin(values)
        numeric = _numeric_view(s)
        if numeric is not None:
            # Both must miss: '25' and 25 are the same row to the person who typed it.
            mask = mask & ~numeric.isin(_numbers(values))
    elif op == 'is_null':
        mask = s.replace('', pd.NA).isna()
    elif op == 'not_null':
        mask = s.replace('', pd.NA).notna()
    else:
        raise UnknownOperationError(f'Unknown filter operator: {op}')
    return df[mask].reset_index(drop=True)
