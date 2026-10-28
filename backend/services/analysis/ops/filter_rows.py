"""The ``filter_rows`` step, one module of the analysis op registry (see ops/__init__.py)."""

import pandas as pd

from services.analysis.kernels import UnknownOperationError, _checked_pattern


def filter_rows(df: pd.DataFrame, column: str, op: str, value) -> pd.DataFrame:
    if column not in df.columns:
        return df
    s = df[column]
    if op == 'eq':
        mask = s == value
    elif op == 'ne':
        mask = s != value
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
        values = value if isinstance(value, (list, tuple, set)) else [v.strip() for v in str(value).split(',')]
        mask = s.isin(values)
    elif op == 'not_in':
        values = value if isinstance(value, (list, tuple, set)) else [v.strip() for v in str(value).split(',')]
        mask = ~s.isin(values)
    elif op == 'is_null':
        mask = s.replace('', pd.NA).isna()
    elif op == 'not_null':
        mask = s.replace('', pd.NA).notna()
    else:
        raise UnknownOperationError(f'Unknown filter operator: {op}')
    return df[mask].reset_index(drop=True)
