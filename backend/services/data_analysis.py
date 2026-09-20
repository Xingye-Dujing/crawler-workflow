import logging

import pandas as pd

from i18n import t

logger = logging.getLogger(__name__)


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
        for c in cols:
            work[c] = work[c].replace('', pd.NA)
            if method:
                work[c] = work[c].fillna(method=method)
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
        elif op == 'gt':
            mask = pd.to_numeric(s, errors='coerce') > float(value)
        elif op == 'gte':
            mask = pd.to_numeric(s, errors='coerce') >= float(value)
        elif op == 'lt':
            mask = pd.to_numeric(s, errors='coerce') < float(value)
        elif op == 'lte':
            mask = pd.to_numeric(s, errors='coerce') <= float(value)
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
        cols = [c for c in (columns or []) if c in work.columns] or work.select_dtypes(
            include='object'
        ).columns.tolist()
        for c in cols:
            work[c] = work[c].astype(str).str.strip()
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
                work[column] = work[column].astype(bool)
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
        if n is not None and n >= len(df):
            return df
        return df.sample(n=n, frac=frac, random_state=seed).reset_index(drop=True)

    @staticmethod
    def groupby_agg(df: pd.DataFrame, group_col: str, agg_col: str, agg_func: str = 'sum') -> pd.DataFrame:
        if group_col not in df.columns or agg_col not in df.columns:
            return df
        result = df.groupby(group_col, as_index=False)[agg_col].agg(agg_func)
        return result

    @staticmethod
    def join_tables(
        df: pd.DataFrame, other_df: pd.DataFrame, how: str = 'left', left_on: str = '', right_on: str = ''
    ) -> pd.DataFrame:
        if left_on and right_on and left_on in df.columns and right_on in other_df.columns:
            return df.merge(other_df, how=how, left_on=left_on, right_on=right_on)
        return df

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
