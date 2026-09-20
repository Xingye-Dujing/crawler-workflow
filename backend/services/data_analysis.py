import logging

import pandas as pd

from i18n import t

logger = logging.getLogger(__name__)

# Values that mean false when a text column is converted to bool. Without this
# map ``astype(bool)`` turns the *string* 'False' — and '0' — into True.
_FALSEY_TEXT = {'', '0', '0.0', 'false', 'no', 'n', 'off', 'none', 'null', 'nan', '假', '否', '不'}


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        try:
            if pd.isna(value):
                return False
        except (TypeError, ValueError):
            return False
        return value != 0
    return str(value).strip().lower() not in _FALSEY_TEXT


class UnknownOperationError(ValueError):
    pass


class DataAnalysisService:
    """Stateless helpers for cleaning/transforming a DataFrame, plus a
    pipeline runner that chains several steps and reports what changed."""

    # ── Individual, composable operations ───────────────────────

    @staticmethod
    def inspect(df: pd.DataFrame) -> dict:
        return {
            'rows': int(len(df)),
            'columns': list(df.columns),
            'dtypes': {c: str(t) for c, t in df.dtypes.items()},
            'null_counts': {c: int(n) for c, n in df.isna().sum().items()},
            'duplicate_rows': int(df.duplicated().sum()),
        }

    @staticmethod
    def drop_null(df: pd.DataFrame, columns: list = None, how: str = 'any') -> pd.DataFrame:
        subset = [c for c in (columns or []) if c in df.columns] or None
        work = df.copy()
        if subset:
            work[subset] = work[subset].replace('', pd.NA)
        else:
            work = work.replace('', pd.NA)
        return work.dropna(subset=subset, how=how).reset_index(drop=True)

    @staticmethod
    def fill_null(df: pd.DataFrame, columns: list = None, value=None, method: str = None) -> pd.DataFrame:
        work = df.copy()
        cols = [c for c in (columns or []) if c in work.columns] or list(work.columns)
        # Forward/backward filling is its own method now — pandas 3 removed the
        # ``fillna(method=…)`` keyword the original code relied on.
        filler = {'ffill': 'ffill', 'pad': 'ffill', 'bfill': 'bfill', 'backfill': 'bfill'}.get(str(method or ''))
        for c in cols:
            work[c] = work[c].replace('', pd.NA)
            if filler == 'ffill':
                work[c] = work[c].ffill()
            elif filler == 'bfill':
                work[c] = work[c].bfill()
            else:
                work[c] = work[c].fillna(value)
        return work

    @staticmethod
    def drop_duplicates(df: pd.DataFrame, columns: list = None, keep: str = 'first') -> pd.DataFrame:
        subset = [c for c in (columns or []) if c in df.columns] or None
        return df.drop_duplicates(subset=subset, keep=keep).reset_index(drop=True)

    @staticmethod
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
            mask = s.astype(str).str.contains(str(value), na=False)
        elif op == 'not_contains':
            mask = ~s.astype(str).str.contains(str(value), na=False)
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

    @staticmethod
    def select_columns(df: pd.DataFrame, columns: list) -> pd.DataFrame:
        cols = [c for c in columns if c in df.columns]
        return df[cols] if cols else df

    @staticmethod
    def rename_columns(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
        return df.rename(columns=mapping)

    @staticmethod
    def strip_whitespace(df: pd.DataFrame, columns: list = None) -> pd.DataFrame:
        work = df.copy()
        # is_string_dtype() instead of select_dtypes('object'): pandas 3 stores
        # text as 'str' (not 'object') and the old call is deprecated.
        text_cols = [c for c in work.columns if pd.api.types.is_string_dtype(work[c])]
        cols = [c for c in (columns or []) if c in work.columns] or text_cols
        for c in cols:
            # Strip only real strings: astype(str) would rewrite every missing
            # value as the text 'None'/'nan'.
            work[c] = work[c].map(lambda v: v.strip() if isinstance(v, str) else v)
        return work

    @staticmethod
    def convert_type(df: pd.DataFrame, column: str, dtype: str) -> pd.DataFrame:
        if column not in df.columns:
            return df
        work = df.copy()
        try:
            if dtype == 'int':
                work[column] = pd.to_numeric(work[column], errors='coerce').astype('Int64')
            elif dtype == 'float':
                work[column] = pd.to_numeric(work[column], errors='coerce')
            elif dtype == 'bool':
                work[column] = work[column].map(_to_bool)
            elif dtype == 'datetime':
                work[column] = pd.to_datetime(work[column], errors='coerce')
            else:
                work[column] = work[column].astype(str)
        except (ValueError, TypeError) as e:
            logger.warning(t('analysis.type_convert_failed', col=column, dtype=dtype, err=e))
        return work

    # ── New operations (Phase 2) ────────────────────────────────

    @staticmethod
    def sort_rows(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
        if column not in df.columns:
            return df
        return df.sort_values(by=column, ascending=ascending).reset_index(drop=True)

    @staticmethod
    def sample_rows(df: pd.DataFrame, n: int = None, frac: float = None, seed: int = None) -> pd.DataFrame:
        # Neither bound configured: pandas' own default is n=1, which silently
        # threw away every other row. Ask for nothing, change nothing.
        if n is None and frac is None:
            return df
        # Both configured: an explicit row count is the more specific request.
        if n is not None:
            n = max(0, int(n))
            if n >= len(df):
                return df
            return df.sample(n=n, random_state=seed).reset_index(drop=True)
        frac = min(max(float(frac), 0.0), 1.0)
        if frac >= 1.0:
            return df
        return df.sample(frac=frac, random_state=seed).reset_index(drop=True)

    @staticmethod
    def groupby_agg(df: pd.DataFrame, group_col: str, agg_col: str, agg_func: str = 'sum') -> pd.DataFrame:
        if group_col not in df.columns or agg_col not in df.columns:
            return df
        try:
            result = df.groupby(group_col, as_index=False)[agg_col].agg(agg_func)
        except (TypeError, ValueError) as e:
            # e.g. sum() over a text column: report the operation instead of a
            # raw pandas error deeper in the pipeline.
            raise UnknownOperationError(f'groupby_agg({agg_func}) failed on "{agg_col}": {e}') from e
        return result

    @staticmethod
    def join_tables(
        df: pd.DataFrame, other_df: pd.DataFrame, how: str = 'left', left_on: str = '', right_on: str = ''
    ) -> pd.DataFrame:
        """Merge with the right-hand table.

        Every way this can fail used to return the left table unchanged, so a
        mistyped column name looked exactly like a successful join. Each case
        now raises a message naming what is missing.
        """
        if other_df is None or len(other_df) == 0:
            raise UnknownOperationError(t('analysis.join_no_right'))
        if not left_on or not right_on:
            raise UnknownOperationError(t('analysis.join_need_keys'))
        missing = []
        if left_on not in df.columns:
            missing.append(f'{left_on} (left)')
        if right_on not in other_df.columns:
            missing.append(f'{right_on} (right)')
        if missing:
            raise UnknownOperationError(t('analysis.join_missing_cols', cols=', '.join(missing)))
        return df.merge(other_df, how=how, left_on=left_on, right_on=right_on)

    @staticmethod
    def column_calc(df: pd.DataFrame, new_col: str, expr: str) -> pd.DataFrame:
        if not new_col or not expr:
            return df
        work = df.copy()
        try:
            work[new_col] = work.eval(expr)
        except Exception as e:
            logger.warning(t('analysis.calc_failed', col=new_col, expr=expr, err=e))
        return work

    @staticmethod
    def bin_column(
        df: pd.DataFrame, column: str, bins: list = None, labels: list = None, new_col: str = ''
    ) -> pd.DataFrame:
        if column not in df.columns:
            return df
        work = df.copy()
        bin_col = new_col or f'{column}_bin'
        if bins is None:
            bins = 4
        try:
            work[bin_col] = pd.cut(pd.to_numeric(work[column], errors='coerce'), bins=bins, labels=labels)
        except Exception as e:
            logger.warning(t('analysis.bin_failed', col=column, err=e))
        return work

    # ── Operation registry + pipeline runner ────────────────────

    @classmethod
    def _operations(cls) -> dict:
        return {
            'drop_null': cls.drop_null,
            'fill_null': cls.fill_null,
            'drop_duplicates': cls.drop_duplicates,
            'filter_rows': cls.filter_rows,
            'select_columns': cls.select_columns,
            'rename_columns': cls.rename_columns,
            'strip_whitespace': cls.strip_whitespace,
            'convert_type': cls.convert_type,
            'sort_rows': cls.sort_rows,
            'sample_rows': cls.sample_rows,
            'groupby_agg': cls.groupby_agg,
            'join_tables': cls.join_tables,
            'column_calc': cls.column_calc,
            'bin_column': cls.bin_column,
        }

    @classmethod
    def run_pipeline(cls, df: pd.DataFrame, steps: list) -> tuple:
        operations = cls._operations()
        report = []
        current = df
        for step in steps or []:
            op = step.get('op')
            params = step.get('params', {})
            func = operations.get(op)
            if func is None:
                raise UnknownOperationError(f'Unknown analysis operation: {op}')
            before = len(current)
            current = func(current, **params)
            report.append(
                {
                    'op': op,
                    'params': params,
                    'rows_before': before,
                    'rows_after': len(current),
                    'rows_removed': before - len(current),
                }
            )
        return current, report
