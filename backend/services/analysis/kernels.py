"""Pieces every analysis operation reads through.

These lived in ``pipeline.py`` while the operations themselves did. They move here so an
operation module (``services.analysis.ops.<name>``) can import them without importing the service
that dispatches it — that cycle is why the package exists. ``pipeline`` imports them back, so
``from services.analysis.pipeline import UnknownOperationError`` keeps working.
"""

import hashlib
import re

import pandas as pd

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


def _checked_pattern(op: str, value) -> str:
    """Return ``value`` as a regex string, refusing an invalid one BY NAME.

    ``str.contains`` reads the filter value as a REGULAR EXPRESSION. An invalid
    pattern surfaces as ``re.error`` from the object engine but a ``ValueError``
    from the arrow engine — version-dependent — so compile it here and raise the
    same ``ValueError`` on every engine/pandas version, never a raw ``re.error``.
    """
    try:
        re.compile(str(value))
    except re.error as exc:
        raise ValueError(f'{op} 值 is not a valid regular expression: {exc}') from exc
    return str(value)


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
#: that :mod:`services.datasets.dedupe` computes, so a comment farm's extra emoji code, a
#: fresh tracking link or a re-pasted forward chain no longer makes a row unique.
DEDUPE_MODES = ('exact', 'normalized')
#: Which calendar part :meth:`DataAnalysisService.extract_time` can derive. ``date`` is the
#: one an event study is built on — a day is the unit every phase boundary is drawn in.
TIME_PARTS = ('date', 'hour', 'weekday', 'month', 'year')


def _blank(value) -> bool:
    """Nothing stated: absent, or the empty text a cleared settings box leaves behind."""
    return value is None or (isinstance(value, str) and not value.strip())


#: The timestamp shape THIS PROJECT'S OWN weibo crawler writes: '2022年01月27日 00:59'.
#:
#: ``crawlers/weibo.py`` normalises an absolute RFC-822 stamp to ISO, but the search page
#: hands back the site's own Chinese display label for most rows and that label is kept as
#: it came (``times.normalise_rfc822`` returns anything it cannot parse untouched, on
#: purpose — inventing an absolute time for a relative label would be worse). So the
#: project emits a column its own time operators cannot read: ``pd.to_datetime`` answers
#: every one of those rows with NaT, and the whole day/phase/sentiment-curve chain then
#: produces one empty column and reports success. Measured on a real export: 4000 of 4000
#: sampled rows are this shape and nothing else.
_CJK_DATE_RE = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')


def _to_datetime(values):
    """Parse a timestamp column, including the shape our own crawler writes.

    The CJK date form is folded to ISO first and then parsed once for the whole column.
    The substitution is a no-op on a string that is already ISO, so a column carrying both
    shapes (an export where some rows took the absolute path and others did not) parses
    whole rather than half — which is the case the old single call got wrong.
    """
    text = values.astype('string')
    folded = text.str.replace(_CJK_DATE_RE, r'\1-\2-\3', regex=True)
    return pd.to_datetime(folded, errors='coerce', format='mixed')
