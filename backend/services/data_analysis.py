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
#: How ``drop_duplicates`` decides two rows are the same row. ``exact`` is pandas'
#: equality over the selected columns; ``normalized`` compares the identity form
#: that :mod:`services.text_dedupe` computes, so a comment farm's extra emoji code, a
#: fresh tracking link or a re-pasted forward chain no longer makes a row unique.
DEDUPE_MODES = ('exact', 'normalized')
#: Which calendar part :meth:`DataAnalysisService.extract_time` can derive. ``date`` is the
#: one an event study is built on — a day is the unit every phase boundary is drawn in.
TIME_PARTS = ('date', 'hour', 'weekday', 'month', 'year')


# Module-level, not lambdas: sklearn's vectorisers keep the callable they were built with,
# and these two are handed to one inside ``topic_model``. They are also what makes the
# tokenisation explicit — jieba has already cut the text into space-separated tokens, so the
# vectoriser only has to split, and doing that here keeps the same convention the ML
# classifiers use (``analyzers.ml_base``).
def _split_tokens(text: str) -> list:
    return str(text).split()


def _keep_text(text: str) -> str:
    return text


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
    'drop_duplicates': {'some': ('columns',), 'enums': {'mode': ('exact', DEDUPE_MODES)}},
    # SimHash near-duplicates read ONE column: the fingerprint is over a text, so a
    # multi-column ask would have to invent a concatenation order nobody chose.
    'dedupe_similar': {'one': ('column',)},
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
    # ── the event-study steps ──
    # All four name ONE column: an unnamed timestamp is not "every timestamp", and a topic
    # model over a column nobody named has no corpus to read. A blank is refused by name
    # rather than defaulted to 正文, because comment crawls file their text under 评论内容 —
    # a default there would model the wrong column and report it as a result.
    'extract_time': {'one': ('column',)},
    'bin_time': {'one': ('column',)},
    'topic_model': {'one': ('column',)},
    'sentiment_evolution': {'one': ('column',)},
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
    def drop_duplicates(
        df: pd.DataFrame, columns: list = None, keep: str = 'first', mode: str = 'exact'
    ) -> pd.DataFrame:
        """Drop repeated rows, by exact equality or by their normalised identity.

        ``exact`` is plain pandas equality. ``normalized`` compares the identity form
        from :mod:`services.text_dedupe`: a comment farm reposts the same sentence with a
        different tracking link, one more emoji code, or a re-pasted forward chain, and
        every one of those is a new string but the same comment. The original text is what
        survives — the key is a temporary column and never reaches the output.
        """
        subset = [c for c in (columns or []) if c in df.columns] or None
        work = df.copy()
        if mode == 'exact':
            return work.drop_duplicates(subset=subset, keep=keep).reset_index(drop=True)
        if mode not in DEDUPE_MODES:
            raise UnknownOperationError(
                t(
                    'analysis.bad_option',
                    op='drop_duplicates',
                    param='mode',
                    value=mode,
                    allowed=', '.join(DEDUPE_MODES),
                )
            )
        from services.text_dedupe import normalized_key

        cols = subset or [str(col) for col in work.columns]
        # Joined with a byte that cannot appear in a cell, so ('ab', 'c') and ('a', 'bc')
        # are not handed the same key — the bug a plain ''.join would produce.
        joined = work[cols[0]].fillna('').astype(str)
        for name in cols[1:]:
            joined = joined + '\x1e' + work[name].fillna('').astype(str)
        work['__dedupe_key__'] = joined.map(normalized_key)
        out = work.drop_duplicates(subset=['__dedupe_key__'], keep=keep)
        return out.drop(columns=['__dedupe_key__']).reset_index(drop=True)

    @staticmethod
    def dedupe_similar(df: pd.DataFrame, column: str, max_distance: int = 8) -> pd.DataFrame:
        """Drop near-duplicate rows — SimHash distance within ``max_distance`` bits.

        What ``drop_duplicates`` cannot see: a comment reposted with one word changed, or
        the same sentence padded to a different length. SimHash puts each comment's
        *meaning-bearing tokens* into 64 bits, so a small edit flips few bits and the row
        collapses into the group it belongs to.

        The first row of each group is kept, matching ``keep='first'`` above, and the
        search is sub-quadratic by banding (see :mod:`services.text_dedupe`) — an
        all-pairs scan over a hundred-thousand-row comment table is not a thing this can
        afford, so a distance the banded index cannot prove is refused by name rather than
        answered with a slow scan or a quietly incomplete group.

        The default is 8 rather than the tightest distance that could be justified, and it
        is measured rather than chosen: on hand-written Weibo comments a one-word rewrite
        sits 5–18 bits away while two unrelated comments sit 26–28, so 8 catches the
        clearly-identical rewrites and leaves the genuinely-different ones alone. Raising
        it towards 15 buys recall and spends precision — worth doing per table, with the
        row counts the run reports, rather than once for every table.
        """
        work = df.copy()
        if column not in work.columns:
            return work
        # Imported here, not at module scope: this module is what the app loads on a plain
        # crawl, and the dedupe helpers pull in jieba for tokenising.
        from services.text_dedupe import MAX_BANDED_DISTANCE, group_near_duplicates, normalize_text, simhash64

        distance = 8 if max_distance is None else int(max_distance)
        if not 0 <= distance <= MAX_BANDED_DISTANCE:
            raise UnknownOperationError(t('analysis.dedupe_distance', value=distance, max=MAX_BANDED_DISTANCE))
        candidates = []
        for idx, raw in work[column].items():
            if pd.isna(raw):
                continue
            text = str(raw)
            # A comment that is only artifacts has no fingerprint of its own: every such
            # row hashes to the same value, so including them would collapse unrelated
            # rows into one group. They are not duplicates of each other — they are empty.
            if not normalize_text(text):
                continue
            candidates.append((str(idx), simhash64(text)))
        dropped = []
        for group in group_near_duplicates(candidates, max_distance=distance):
            dropped.extend(int(member) for member in group[1:])
        if dropped:
            work = work.drop(index=dropped)
        logger.info(t('analysis.dedupe_similar', n=len(dropped), column=column, distance=distance))
        return work.reset_index(drop=True)

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
                # ``format='mixed'`` is not a fix for a wrong guess, it is the guess being *said out
                # loud*: without a format pandas tries one for the whole column, fails on a table
                # whose rows came from different sources, and then parses every element individually
                # with dateutil anyway — while warning that it did. Declaring the per-element path
                # keeps the behaviour identical and removes the noise the user cannot act on
                # (pandas >= 2.0; the project venv carries 3.x).
                # ``format='mixed'`` is not a fix for a wrong guess, it is the guess being *said out
                # loud*: without a format pandas tries one for the whole column, fails on a table
                # whose rows came from different sources, and then parses every element individually
                # with dateutil anyway — while warning that it did. Measured, the undeclared path was
                # worse than noisy: on ``['2024-01-01', '2024-01-02 03:04:05']`` it inferred
                # ``%Y-%m-%d`` from row one and coerced row two to ``NaT``, so the timestamps simply
                # disappeared from the user's table. Declaring the per-element path keeps every row
                # and removes the noise the user cannot act on (pandas >= 2.0; the venv has 3.x).
                work[column] = pd.to_datetime(work[column], errors='coerce', format='mixed')
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
        """Add a computed column, or refuse with the expression that could not run.

        This used to log a warning and hand the table back UNCHANGED, which is the one
        outcome this project forbids everywhere else: the node settled DONE, the column the
        user named was never created, and the only trace was a line in ``logs/``. A
        mistyped column name then surfaced two nodes later as a chart with nothing in it —
        on a run that had already paid for its crawl.

        The column name inside an expression is the reason this could not simply be added
        to :data:`STEP_PARAMS`: no table of column names can validate a formula, so the
        check has to be the evaluation itself. Which means the refusal has to BE the
        evaluation's failure, carrying the expression the user typed.
        """
        if not new_col or not expr:
            return df
        work = df.copy()
        try:
            work[new_col] = work.eval(expr)
        except Exception as e:
            raise UnknownOperationError(t('analysis.calc_failed', col=new_col, expr=expr, err=e)) from e
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
            # Same rule as ``column_calc`` above: a refusal, never a silent no-op. The
            # inputs that reach here are real — edges given in the wrong order, a label
            # list that does not match the number of buckets — and each of them used to
            # settle the node DONE with no new column and one line in the log file.
            raise UnknownOperationError(t('analysis.bin_failed', col=column, err=e)) from e
        return work

    # ── Time dimension ──────────────────────────────────────────
    #
    # An event study is a study of WHEN, and nothing above answers that: `评论时间` holds
    # "2024-05-02 13:45", so grouping by it groups by the minute, and a line chart of a
    # per-minute series is noise. These two steps are the floor the whole analysis stands
    # on — daily post counts, the phase split, and the sentiment curve are all defined
    # over a calendar day rather than over a timestamp.

    @staticmethod
    def extract_time(df: pd.DataFrame, column: str, new_col: str = '日期', part: str = 'date') -> pd.DataFrame:
        """Derive one calendar part of a timestamp column.

        ``date`` answers with ``YYYY-MM-DD`` text rather than a date object: the value is
        grouped, exported and charted, and a lexical sort of ISO dates IS a chronological
        sort, so the text form costs nothing and survives every serialisation in this
        pipeline. The other parts answer with a number.

        A timestamp the site handed back as a relative label ("09月26日 21:00" is what Weibo
        shows when it has no year) cannot be turned into a calendar day, and guessing this
        year for it would move rows between phases. Those rows are left EMPTY and counted
        in the console — an empty is not a date, and pandas' own ``groupby`` then drops them
        instead of inventing a 1970 bucket for them.
        """
        if column not in df.columns:
            return df
        if part not in TIME_PARTS:
            raise UnknownOperationError(
                t('analysis.bad_option', op='extract_time', param='part', value=part, allowed=', '.join(TIME_PARTS))
            )
        work = df.copy()
        stamps = pd.to_datetime(work[column], errors='coerce', format='mixed')
        unparsed = int(stamps.isna().sum())
        if part == 'date':
            work[new_col] = stamps.dt.strftime('%Y-%m-%d')
            # strftime answers 'NaT' for a missing stamp, and a column whose missing value
            # is the text "NaT" groups those rows together as if they were one day.
            work.loc[stamps.isna(), new_col] = pd.NA
        else:
            work[new_col] = getattr(stamps.dt, part)
        if unparsed:
            logger.warning(t('analysis.time_unparsed', col=column, n=unparsed))
        return work

    @staticmethod
    def bin_time(
        df: pd.DataFrame, column: str, edges: list = None, labels: list = None, new_col: str = '阶段'
    ) -> pd.DataFrame:
        """Cut a timestamp column into named windows — the event's lifecycle phases.

        ``edges`` are the boundaries, left-closed and right-open: five phases need SIX
        edges, and the last one is the day after the final phase ends. That is stated
        rather than smoothed over because the alternative reading ("edges are the phase
        ends") silently shifts every row on a boundary day into the neighbouring phase —
        and those are exactly the days an event study is about.

        Which is why the comparison runs on the calendar DAY: a row stamped 23:59 on the
        day before a boundary belongs to the earlier phase, not to the next one by two
        minutes.
        """
        if column not in df.columns:
            return df
        work = df.copy()
        bounds = [value for value in (edges or []) if not _blank(value)]
        names = [str(name).strip() for name in (labels or []) if str(name).strip()]
        if len(bounds) < 2:
            raise UnknownOperationError(t('analysis.need_param', op='bin_time', param='edges'))
        if len(names) != len(bounds) - 1:
            raise UnknownOperationError(t('analysis.time_bin_labels', edges=len(bounds), labels=len(names)))
        parsed = pd.to_datetime(pd.Series(bounds), errors='coerce', format='mixed')
        if parsed.isna().any():
            bad = [bounds[index] for index, ok in enumerate(parsed.notna()) if not ok]
            raise UnknownOperationError(t('analysis.time_bin_edges', edges=', '.join(str(x) for x in bad)))
        if not parsed.is_monotonic_increasing:
            # pd.cut would raise on unsorted bins with pandas' own wording; naming the
            # parameter is what lets the user find the box that holds it.
            raise UnknownOperationError(t('analysis.time_bin_order', op='bin_time'))
        stamps = pd.to_datetime(work[column], errors='coerce', format='mixed')
        unparsed = int(stamps.isna().sum())
        work[new_col] = pd.cut(stamps.dt.normalize(), bins=parsed, labels=names, right=False)
        if unparsed:
            logger.warning(t('analysis.time_unparsed', col=column, n=unparsed))
        counts = work[new_col].value_counts()
        detail = '、'.join(f'{name} {int(counts.get(name, 0))} 行' for name in names)
        logger.info(t('analysis.time_binned', col=new_col, detail=detail))
        return work

    # ── Topic modelling ─────────────────────────────────────────

    @staticmethod
    def topic_model(
        df: pd.DataFrame, column: str, n_topics: int = 5, topn: int = 10, max_features: int = 2000
    ) -> pd.DataFrame:
        """LDA over one text column: which subjects is this corpus made of.

        ``sklearn``'s ``LatentDirichletAllocation``, not Gensim's: scikit-learn is already
        a dependency of this project and gensim is not, and a topic model that needs a
        second numerical stack installed to read a table is not worth the extra words it
        would type. Both fit the same generative model; the numbers they report are not
        identical, so a replication should say which one produced its table.

        The output is ONE ROW PER (topic, keyword) rather than one row per topic with its
        words joined: it is the shape the keyword node already answers with, it keeps every
        weight addressable, and a chart can group it by ``topic`` directly. Reading it as
        the paper's table is a job for the console line, which prints each topic's words in
        order.

        The perplexity is logged because "设定主题个数" is a real decision and the paper
        does not say how it was made: run the node at several ``n_topics`` and read the
        number, which falls as the model fits better and stops meaning anything once it
        starts memorising rows.
        """
        import jieba
        from sklearn.decomposition import LatentDirichletAllocation
        from sklearn.feature_extraction.text import CountVectorizer

        if column not in df.columns:
            return df
        topics = int(n_topics)
        if topics < 2:
            raise UnknownOperationError(t('analysis.topic_count', value=topics))
        texts = [str(value) for value in df[column].dropna().tolist() if str(value).strip()]
        if len(texts) < topics:
            raise UnknownOperationError(t('analysis.topic_rows', rows=len(texts), topics=topics))
        # Tokens with no letter or digit in them are dropped before the model sees them, the
        # same rule the word-cloud tokenizer applies: jieba hands back the punctuation it
        # split on, and a topic model whose vocabulary is "。" and "！" has topics that are
        # punctuation. A corpus that is nothing BUT punctuation then has no vocabulary at
        # all, which is refused below rather than answered with an empty table.
        tokenized = [
            ' '.join(token for token in jieba.cut(text) if any(char.isalnum() for char in token)) for text in texts
        ]
        vectorizer = CountVectorizer(
            tokenizer=_split_tokens,
            preprocessor=_keep_text,
            token_pattern=None,
            max_features=max(10, int(max_features)),
        )
        try:
            matrix = vectorizer.fit_transform(tokenized)
        except ValueError as e:
            raise UnknownOperationError(t('analysis.topic_features', err=e)) from e
        model = LatentDirichletAllocation(n_components=topics, random_state=42, learning_method='batch')
        model.fit(matrix)
        vocabulary = vectorizer.get_feature_names_out()
        rows = []
        lines = []
        for index, component in enumerate(model.components_):
            best = component.argsort()[::-1][: max(1, int(topn))]
            words = [str(vocabulary[position]) for position in best]
            lines.append(f'Topic-{index + 1}: {" ".join(words)}')
            for rank, position in enumerate(best):
                rows.append(
                    {
                        'topic': f'Topic-{index + 1}',
                        'rank': rank + 1,
                        'keyword': str(vocabulary[position]),
                        'weight': round(float(component[position]), 6),
                    }
                )
        logger.info(
            t(
                'analysis.topic_done',
                n=topics,
                rows=len(texts),
                perplexity=round(float(model.perplexity(matrix)), 2),
            )
        )
        for line in lines:
            # One line per topic, so the console reads like the paper's table without an
            # export round trip — the whole point of running the node.
            logger.info(line)
        return pd.DataFrame(rows, columns=['topic', 'rank', 'keyword', 'weight'])

    # ── The sentiment curve ─────────────────────────────────────

    @staticmethod
    def sentiment_evolution(
        df: pd.DataFrame,
        column: str,
        label_col: str = 'sentiment',
        positive: str = 'positive',
        neutral: str = 'neutral',
        negative: str = 'negative',
        new_col: str = 'sentiment_index',
    ) -> pd.DataFrame:
        """Per-period sentiment shares and one signed intensity — the evolution curve.

        The number this exists for is ``sentiment_index`` = (positive − negative) / total,
        which is the paper's daily value: +1 means the period was wholly positive, −1
        wholly negative, and 0 means either everything was neutral or the two sides
        cancelled. It is deliberately NOT a mean of per-row scores: a mean over rows answers
        "how strong was the average opinion", while this answers "which way did the crowd
        lean", and a phase with a large silent neutral majority must read as moderate even
        when the few opinions are extreme. That distinction is the paper's central finding
        (爆发期 76% negative but a phase index near −0.56), so it is computed rather than
        approximated.

        Rows whose label is none of the three named values are counted in ``total`` and in
        none of the three buckets — a blank the polarity node could not judge is not a
        neutral opinion, and folding it into 中性 would report a finding the data does not
        contain. Their count is ``other_n``, so the difference is visible rather than lost.
        """
        if column not in df.columns or label_col not in df.columns:
            return df
        work = df.copy()
        labels = work[label_col].astype('string').fillna('').str.strip()
        work['_pos'] = (labels == positive).astype(int)
        work['_neu'] = (labels == neutral).astype(int)
        work['_neg'] = (labels == negative).astype(int)
        grouped = work.groupby(column, dropna=True).agg(
            positive_n=('_pos', 'sum'),
            neutral_n=('_neu', 'sum'),
            negative_n=('_neg', 'sum'),
            total=('_pos', 'size'),
        )
        grouped = grouped.reset_index()
        grouped['other_n'] = grouped['total'] - grouped['positive_n'] - grouped['neutral_n'] - grouped['negative_n']
        # A zero total cannot happen (groupby only makes groups from rows) but the ratio is
        # written defensively: a division here would surface as an inf in a chart, not as
        # an error anyone could trace back to this line.
        totals = grouped['total'].replace(0, pd.NA)
        for name, source in (
            ('positive_pct', 'positive_n'),
            ('neutral_pct', 'neutral_n'),
            ('negative_pct', 'negative_n'),
        ):
            grouped[name] = (grouped[source] / totals * 100).round(2)
        grouped[new_col] = ((grouped['positive_n'] - grouped['negative_n']) / totals).round(4)
        # Ascending by the period so a line chart draws left-to-right in time without the
        # user having to add a sort step — and 'YYYY-MM-DD' sorts chronologically as text,
        # which is why extract_time answers with text.
        grouped = grouped.sort_values(column, kind='stable').reset_index(drop=True)
        grouped = grouped.rename(columns={column: 'period'})
        logger.info(
            t(
                'analysis.evolution_done',
                n=len(grouped),
                periods=str(grouped['period'].iloc[0]) + ' … ' + str(grouped['period'].iloc[-1])
                if len(grouped)
                else '',
            )
        )
        return grouped

    # ── Operation registry + pipeline runner ────────────────────

    @classmethod
    def _operations(cls) -> dict:
        return {
            'drop_null': cls.drop_null,
            'fill_null': cls.fill_null,
            'drop_duplicates': cls.drop_duplicates,
            'dedupe_similar': cls.dedupe_similar,
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
            'extract_time': cls.extract_time,
            'bin_time': cls.bin_time,
            'topic_model': cls.topic_model,
            'sentiment_evolution': cls.sentiment_evolution,
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
