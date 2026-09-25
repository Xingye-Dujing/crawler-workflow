import hashlib
import logging

import pandas as pd

from i18n import t
from utils.helpers import split_names

logger = logging.getLogger(__name__)

# Values that mean false when a text column is converted to bool. Without this
# map ``astype(bool)`` turns the *string* 'False' — and '0' — into True.
_FALSEY_TEXT = {'', '0', '0.0', 'false', 'no', 'n', 'off', 'none', 'null', 'nan', '假', '否', '不'}


def _stable_seed(df: pd.DataFrame) -> int:
    """A sampling seed that repeats for one input and differs between inputs.

    ``df.sample`` without ``random_state`` draws from the process-wide RNG, so any
    pipeline containing a sample step answered differently on every run of *the
    same* data — which breaks the promise the whole engine is built on (a
    repeated or resumed run reproduces the previous result, so re-running never
    silently changes the rows a paid-for downstream step was computed from).

    The seed is therefore derived from the frame itself: its shape, its column
    names and the row hashes of its first and last row. Deterministic (pandas
    hashes with a fixed key), cheap enough to pay per step, and still spread
    across the seed space so two datasets do not sample the same rows.
    """
    digest = hashlib.sha1()
    digest.update(f'{df.shape[0]}x{df.shape[1]}|'.encode())
    digest.update(repr([str(c) for c in df.columns]).encode('utf-8', 'replace'))
    edges = pd.concat([df.head(1), df.tail(1)]) if len(df) else df.iloc[0:0]
    try:
        # uint64 row hashes, not the values themselves: this stays cheap on a
        # wide text frame and never trips over the encoding of a cell.
        digest.update(pd.util.hash_pandas_object(edges, index=True).to_numpy().tobytes())
    except (TypeError, ValueError):
        # Unhashable cells (a column of dicts or lists) — fall back to a textual
        # dump, which is still the same bytes for the same rows.
        digest.update(repr(edges.values.tolist()).encode('utf-8', 'replace'))
    # 4 bytes: numpy's legacy RandomState only accepts a seed in 0 … 2**32 - 1.
    return int.from_bytes(digest.digest()[:4], 'big')


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


#: The select-shaped parameters of each cleaning step. A step reads these the way the
#: crawl matrix reads a ``select`` Field: only the listed spellings mean something,
#: and anything else is refused by name instead of being guessed into a different
#: operation. Before this table, ``convert_type(dtype='number')`` silently produced
#: text, ``fill_null(method='mean')`` silently filled a literal value, and
#: ``drop_null(how='none')`` died inside pandas with a stack trace.
FILTER_OPS = (
    'eq',
    'ne',
    'gt',
    'gte',
    'lt',
    'lte',
    'contains',
    'not_contains',
    'in',
    'not_in',
    'is_null',
    'not_null',
)
CONVERT_TYPES = ('str', 'int', 'float', 'bool', 'datetime')
DROP_HOW = ('any', 'all')
#: ``fill_null`` accepts pandas' own aliases, so both spellings of each pair are named
#: rather than mapped: the value that reaches the step has to be one the step honours.
FILL_METHODS = ('ffill', 'pad', 'bfill', 'backfill')
JOIN_HOW = ('left', 'right', 'inner', 'outer', 'cross')

#: Sentinel for a select with no fallback: leaving it blank is a missing choice, and
#: guessing one is the bug this table exists to stop. ``filter_rows`` uses it — defaulting
#: a blank comparison to ``eq`` would answer a mistyped filter with "the data was already
#: clean", which is the sentence this repo refuses to print.
NO_DEFAULT = object()

#: What each step needs from the table it is handed, checked before it runs.
#:
#: ``one`` names exactly one column, so a blank or an absent name is a mistake the user
#: can fix — it is NOT read as "every column". ``some`` names a subset where an empty
#: list legitimately means "every column" (the panel's 留空=全部 behaviour, which several
#: saved pipelines rely on). ``enums`` maps each select to ``(its fallback, the names it
#: accepts)``, the fallback being :data:`NO_DEFAULT` when a blank has to be refused.
#: ``nonblank`` is a parameter that names a *new* column or an expression: writing it
#: blank used to "succeed" by adding a header the CSV export shows as an empty cell.
#:
#: Applied in :meth:`DataAnalysisService.run_pipeline`, which both the analysis node and
#: ``/api/analysis/run`` go through, so one table guards every entry point — and after
#: :func:`normalize_step_params`, which is what makes each check a question about the
#: value the operation really receives.
STEP_PARAMS: dict = {
    'drop_null': {'some': ('columns',), 'enums': {'how': ('any', DROP_HOW)}},
    'fill_null': {'some': ('columns',), 'enums': {'method': (None, FILL_METHODS)}},
    'drop_duplicates': {'some': ('columns',)},
    'select_columns': {'some': ('columns',)},
    'strip_whitespace': {'some': ('columns',)},
    'filter_rows': {'one': ('column',), 'enums': {'op': (NO_DEFAULT, FILTER_OPS)}},
    'rename_columns': {'mapping': True},
    'convert_type': {'one': ('column',), 'enums': {'dtype': ('str', CONVERT_TYPES)}},
    'sort_rows': {'one': ('column',)},
    'groupby_agg': {'one': ('group_col', 'agg_col')},
    'join_tables': {'enums': {'how': ('left', JOIN_HOW)}},
    'column_calc': {'nonblank': ('new_col', 'expr')},
    'bin_column': {'one': ('column',)},
    'sample_rows': {},
}


def _blank(value) -> bool:
    """Nothing stated: absent, or the empty text a cleared settings box leaves behind."""
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_step_params(op: str, params: dict) -> dict:
    """Coerce one step's parameters into the shape and spelling the operation reads.

    Two entry paths used to disagree about this and nothing told the caller. The node
    executor sends the *flat* panel fields through ``_normalize_analysis_params``, which
    splits ``columns: '名称, 城市'`` into two stripped names; ``/api/analysis/run`` and a
    workflow file's own ``steps`` handed the same params to ``run_pipeline`` as they were,
    so a string was iterated as its **characters** — seven "columns" that match nothing, a
    step that quietly did nothing, and a green node. Normalizing here, at the one place
    both doors pass through, makes them mean the same thing.

    Padding comes off the names and selects, matching what the crawl matrix does with a
    text field (``Field.value_from`` strips), and a blank select becomes its declared
    fallback: passing ``how=''`` on to pandas is a ``ValueError: invalid how option:``
    for a box the user simply left alone. A *value* is deliberately untouched —
    ``filter_rows(value=' ')`` searches for a space, which is a real answer rather than a
    missing one.
    """
    spec = STEP_PARAMS.get(op)
    if spec is None or not isinstance(params, dict):
        return params or {}
    out = dict(params)
    for key in spec.get('some', ()):
        if key in out:
            out[key] = split_names(out[key])
    for key in (*spec.get('one', ()), *spec.get('nonblank', ())):
        if isinstance(out.get(key), str):
            out[key] = out[key].strip()
    for key, (default, _allowed) in (spec.get('enums') or {}).items():
        if key not in out or default is NO_DEFAULT or isinstance(out[key], bool):
            continue
        out[key] = default if _blank(out[key]) else str(out[key]).strip()
    return out


def validate_step(df: pd.DataFrame, op: str, params: dict) -> None:
    """Refuse a step this table cannot carry out, naming the reason.

    The silent alternatives were each worse than an error: a mistyped entry in a column
    *list* was dropped, and when every entry missed, ``drop_null`` read the emptied subset
    as "all columns" and deleted rows the user never aimed at, while
    ``filter_rows``/``sort_rows``/``convert_type`` on a column that does not exist settled
    the node **done** and passed the untouched table downstream — so an export shipped
    unfiltered data with a green check on it.

    Call it with :func:`normalize_step_params` output: it compares the value the operation
    will receive, so a name that passes here is a name that resolves there.
    """
    spec = STEP_PARAMS.get(op)
    if spec is None:
        # An op with no entry here is a gap in this table, not a licence to skip the
        # check; `test_the_gate_knows_every_registered_step` fails the suite first.
        return
    params = params or {}
    columns = [str(col) for col in df.columns]
    for key in spec.get('one', ()):
        name = params.get(key)
        if _blank(name):
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
        if str(name) not in columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op=op, col=str(name)))
    for key in spec.get('some', ()):
        wanted = params.get(key) or []
        missing = [str(name) for name in wanted if str(name) not in columns]
        if wanted and missing:
            raise UnknownOperationError(t('analysis.step_cols_missing', op=op, cols=', '.join(missing)))
    for key, (_default, allowed) in (spec.get('enums') or {}).items():
        if key not in params or params[key] is None:
            continue  # absent: the operation's own signature default answers
        value = str(params[key])
        if not value.strip():
            # A blank here survived normalize_step_params, so this select has no
            # fallback to fall back on and the choice is simply missing.
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
        if value not in allowed:
            raise UnknownOperationError(
                t('analysis.bad_option', op=op, param=key, value=value, allowed=', '.join(allowed))
            )
    for key in spec.get('nonblank', ()):
        if _blank(params.get(key)):
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
    if spec.get('mapping'):
        _validate_renames(df, op, params.get('mapping'))


def _validate_renames(df: pd.DataFrame, op: str, mapping) -> None:
    """A rename that would erase a column's name is refused, not applied.

    ``{'标题': ''}`` used to rename the column to the empty string: every later step
    that named 标题 then found nothing, and the exported CSV carried a header cell
    with no word in it. A blank *source* name is the same mistake on the other side,
    and an empty mapping "succeeded" while changing nothing.
    """
    if not isinstance(mapping, dict) or not mapping:
        raise UnknownOperationError(t('analysis.need_param', op=op, param='rename_from'))
    columns = [str(col) for col in df.columns]
    missing, blank_target = [], []
    for source, target in mapping.items():
        name = str(source)
        if not name.strip() or name not in columns:
            missing.append(name.strip() or name)
        elif _blank(target):
            blank_target.append(name)
    if missing:
        raise UnknownOperationError(t('analysis.step_cols_missing', op=op, cols=', '.join(missing)))
    if blank_target:
        raise UnknownOperationError(t('analysis.rename_blank', op=op, cols=', '.join(blank_target)))


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
        # An explicit seed is authoritative; a blank one (the settings panel
        # stores every field as a string, so '' is "left empty") is treated as
        # absent. Without either, the frame's own hash decides — see
        # ``_stable_seed``: the sample stays reproducible for the same input.
        raw_seed = str(seed).strip() if seed is not None else ''
        state = int(float(raw_seed)) if raw_seed else _stable_seed(df)
        # Both configured: an explicit row count is the more specific request.
        if n is not None:
            n = max(0, int(n))
            if n >= len(df):
                return df
            return df.sample(n=n, random_state=state).reset_index(drop=True)
        frac = min(max(float(frac), 0.0), 1.0)
        if frac >= 1.0:
            return df
        return df.sample(frac=frac, random_state=state).reset_index(drop=True)

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
            params = normalize_step_params(op, step.get('params', {}))
            func = operations.get(op)
            if func is None:
                raise UnknownOperationError(f'Unknown analysis operation: {op}')
            validate_step(current, op, params)
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
