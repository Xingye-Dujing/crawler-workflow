"""One definition of "the same content", shared by the analysis layer and the crawl audit.

Two features ask the same question about two tables — *which values of this column also
appear in that column?* — and must answer it identically:

* the ``anti_join`` analysis step (内容去重: keep the rows whose key is NOT in the other
  table), and
* the ``verify`` node (采集校验: is every link of the list present in the crawl result?).

A second implementation would mean a link the audit calls "missing" is a link the de-dup
step already dropped, and the user would chase a hole that does not exist. So the value
normalisation, the blank rule and the near-duplicate search live here, once.

**A key is an identity, never display text.** ``trim`` collapses whitespace, ``url`` folds
the address forms one site serves for one page, ``text`` reuses
:mod:`services.datasets.dedupe`'s normalisation (emoji codes, forward chains, mentions,
full-width punctuation), and ``similar`` compares SimHash fingerprints. None of those
forms may be rendered — they exist to be compared.

**A blank key never matches anything.** Two empty cells are not "the same content": they
are two absences. A row with no usable key is therefore never dropped by ``anti_join`` and
never counted as covered by ``verify``; both report the count so the number is visible.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError

#: How two values are decided to be the same content. Ordered from strictest to loosest;
#: ``trim`` is the default because it never merges two values a user would call different.
MATCH_MODES = ('exact', 'trim', 'url', 'text', 'similar')

#: The modes that answer a per-key COUNT as well as a yes/no. ``similar`` groups
#: near-duplicates transitively, so it can say "covered" but cannot say "this article has
#: N comments"; a step that must count (the verify node) refuses it by name.
COUNT_MODES = ('exact', 'trim', 'url', 'text')

#: What an anti-join keeps. ``exclude`` is the content de-dup (drop rows already present in
#: the other table); ``keep`` is its mirror (semi-join).
KEEP_MODES = ('exclude', 'keep')

#: The two-table steps. They read the node's SECOND incoming connection as the other table,
#: and a blank form cannot run them (there is nothing else to read) — which is why the
#: blank-form safety sweep in the test suite must skip them rather than call them inert.
STEP_TWO_TABLE = frozenset({'anti_join', 'join_tables'})

#: Separator of a composite key (several columns compared as one). U+001F cannot occur in a
#: crawled cell, so two different tuples can never join into the same key text.
KEY_SEPARATOR = '\x1f'

#: The default SimHash distance, matching ``dedupe_similar``: measured on hand-written Weibo
#: comments a one-word rewrite sits 5–18 bits away while unrelated comments sit 26–28.
SIMILAR_DEFAULT_DISTANCE = 8

#: Query parameters that identify a REFERRAL, not a page. Dropped in ``url`` mode so
#: "…/detail/42?utm_source=share" and "…/detail/42" are one link. A parameter not listed
#: here is kept (sorted), because dropping an unknown one could merge two different pages.
_TRACKING_KEYS = frozenset(
    {
        'from',
        'from_source',
        'for_share',
        'isappinstalled',
        'msource',
        'ref',
        'referrer',
        'scm',
        'share_from',
        'share_token',
        'spm',
        'spm_id_from',
        'vd_source',
        'wfr',
    }
)

_WHITESPACE_RE = re.compile(r'\s+')


def cell_text(value) -> str:
    """One cell as text, with the number shapes a table can hold folded to one spelling.

    An id read from a CSV is a ``str``; the same id from a JSON export is an ``int``; a
    pandas read of a spreadsheet can answer ``12345.0``. All three are the same key, and a
    key that changes spelling between two files makes every row look unmatched.
    """
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float):
        if pd.isna(value):
            return ''
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def clean_cell(value) -> str:
    """The trimmed form: full-width spaces and runs of whitespace folded to one space."""
    text = unicodedata.normalize('NFKC', cell_text(value)).replace('\u3000', ' ')
    return _WHITESPACE_RE.sub(' ', text).strip()


def is_url_cell(value) -> bool:
    """Whether *value* is shaped like an address (what ``url`` mode can fold)."""
    text = clean_cell(value)
    return '://' in text or text.startswith('//')


def canonical_url(value) -> str:
    """The address form of one page, or ``''`` when *value* is not an address.

    Folds only the differences a site itself produces for one page: scheme/host case, the
    default port, a leading ``www.``, one trailing slash (the path ``/`` alone is kept),
    the fragment, and the referral parameters above. The query is SORTED rather than
    dropped, so a page whose address carries meaningful parameters (``?id=42``) keeps them.
    """
    raw = clean_cell(value)
    if not raw:
        return ''
    if '://' not in raw:
        if not raw.startswith('//'):
            return ''
        raw = 'https:' + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ''
    if not parts.netloc:
        return ''
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if scheme == 'http' and netloc.endswith(':80'):
        netloc = netloc[:-3]
    if scheme == 'https' and netloc.endswith(':443'):
        netloc = netloc[:-4]
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    path = parts.path
    if len(path) > 1 and path.endswith('/'):
        path = path.rstrip('/')
    pairs = []
    try:
        parsed_query = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        parsed_query = []
    for key, value in parsed_query:
        lowered = key.lower()
        if lowered in _TRACKING_KEYS or lowered.startswith('utm_'):
            continue
        pairs.append((key, value))
    pairs.sort()
    return urlunsplit((scheme, netloc, path, urlencode(pairs, doseq=True), ''))


def _normalise_for_text(value, ignore_case: bool) -> str:
    """The identity residue of a text cell, through the project's one normaliser."""
    # Imported here, never at module scope: this module is reached by the analysis package,
    # and ``services.datasets.dedupe`` pulls in jieba — a cost a plain crawl must not pay.
    from services.datasets.dedupe import normalize_text, normalized_key

    normalised = normalize_text(clean_cell(value))
    if ignore_case:
        normalised = normalised.casefold()
    return normalized_key(normalised)


def value_key(value, mode: str = 'trim', ignore_case: bool = False) -> str:
    """The comparison key of one cell — ``''`` when the cell states no identity.

    ``ignore_case`` folds case for ``exact``/``trim``/``text``. It is deliberately NOT
    applied to ``url``: a host is already lower-cased, while a path is case-sensitive on
    several of the sites this project crawls, and folding it would merge two real pages.
    """
    if mode == 'similar':
        raise UnknownOperationError(t('analysis.match_keyless', mode=mode))
    text = cell_text(value)
    if not text.strip():
        return ''
    if mode == 'exact':
        key = text
    elif mode == 'trim':
        key = clean_cell(text)
    elif mode == 'url':
        key = canonical_url(text) or clean_cell(text)
    elif mode == 'text':
        return _normalise_for_text(text, ignore_case)
    else:
        raise UnknownOperationError(t('analysis.match_bad_mode', mode=mode, allowed=', '.join(MATCH_MODES)))
    if ignore_case and mode != 'url':
        key = key.casefold()
    return key


def row_key(row, columns, mode: str = 'trim', ignore_case: bool = False) -> str:
    """The composite key of one row over *columns*; ``''`` when any part is blank.

    A partially blank tuple is not a weaker identity — it is an incomplete one, and letting
    ``('公众号A', '')`` match every blank link of that account is exactly the silent merge
    this module exists to prevent.
    """
    parts = []
    for column in columns or ():
        part = value_key((row or {}).get(column), mode, ignore_case)
        if not part:
            return ''
        parts.append(part)
    return KEY_SEPARATOR.join(parts) if parts else ''


def keys_of(values, mode: str = 'trim', ignore_case: bool = False) -> list[str]:
    """Comparison keys of a value list, index-aligned (``''`` entries kept in place)."""
    return [value_key(value, mode, ignore_case) for value in values]


def _similar_mask(left_values: list, right_values: list, max_distance: int) -> tuple[list, int, int]:
    """Near-duplicate membership by SimHash over the union of both sides.

    One grouping call over ``left ∪ right`` (the same banded search ``dedupe_similar``
    uses), then a left row counts as matched when its group holds a right row. Grouping is
    by connected component, so nearness chains: A~B and B~C put A, B and C in one group.
    Cells that normalise to nothing carry no fingerprint of their own and are skipped on
    both sides (they are counted as blanks by the caller).
    """
    # Imported here for the same reason as ``_normalise_for_text``: jieba is a heavy import
    # that must not be paid by a canvas that never runs a similarity step.
    from services.datasets.dedupe import MAX_BANDED_DISTANCE, group_near_duplicates, normalize_text, simhash64

    distance = SIMILAR_DEFAULT_DISTANCE if max_distance is None else int(max_distance)
    if distance > MAX_BANDED_DISTANCE:
        raise UnknownOperationError(t('analysis.match_distance', value=distance, max=MAX_BANDED_DISTANCE))
    if distance < 0:
        raise UnknownOperationError(t('analysis.match_distance', value=distance, max=MAX_BANDED_DISTANCE))
    items = []
    left_ids = set()
    right_ids = set()
    left_blank = 0
    right_blank = 0
    for index, value in enumerate(left_values):
        if not normalize_text(clean_cell(value)):
            left_blank += 1
            continue
        left_ids.add(f'L{index}')
        items.append((f'L{index}', simhash64(clean_cell(value))))
    for index, value in enumerate(right_values):
        if not normalize_text(clean_cell(value)):
            right_blank += 1
            continue
        right_ids.add(f'R{index}')
        items.append((f'R{index}', simhash64(clean_cell(value))))
    matched_left: set = set()
    if left_ids and right_ids:
        for group in group_near_duplicates(items, max_distance=distance):
            if any(member in right_ids for member in group):
                matched_left.update(member for member in group if member in left_ids)
    mask = [f'L{index}' in matched_left for index in range(len(left_values))]
    return mask, left_blank, right_blank


def match_mask(
    left_values,
    right_values,
    mode: str = 'trim',
    ignore_case: bool = False,
    max_distance: int = SIMILAR_DEFAULT_DISTANCE,
) -> tuple[list[bool], dict]:
    """``([has a counterpart in right], stats)`` for one left value list.

    ``stats`` names the numbers a console line needs: how many left cells had no usable key,
    how many distinct right keys exist, and how many right cells were blank. They are
    returned rather than logged here because the caller knows what to call the two tables.
    """
    if mode not in MATCH_MODES:
        raise UnknownOperationError(t('analysis.match_bad_mode', mode=mode, allowed=', '.join(MATCH_MODES)))
    if mode == 'similar':
        mask, left_blank, right_blank = _similar_mask(list(left_values), list(right_values), max_distance)
        distinct = len(keys_of([v for v in right_values if clean_cell(v)], 'trim'))
        return mask, {'left_blank': left_blank, 'right_blank': right_blank, 'right_keys': distinct}
    left_keys = keys_of(left_values, mode, ignore_case)
    right_keys = keys_of(right_values, mode, ignore_case)
    distinct_right = {key for key in right_keys if key}
    mask = [bool(key) and key in distinct_right for key in left_keys]
    return mask, {
        'left_blank': sum(1 for key in left_keys if not key),
        'right_blank': sum(1 for key in right_keys if not key),
        'right_keys': len(distinct_right),
    }


def key_counts(values, mode: str = 'trim', ignore_case: bool = False) -> tuple[dict, int]:
    """``({key: row count}, blank_count)`` — the per-key tally a count check reads."""
    counts: dict[str, int] = {}
    blanks = 0
    for value in values:
        key = value_key(value, mode, ignore_case)
        if not key:
            blanks += 1
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts, blanks
