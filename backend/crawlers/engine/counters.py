"""Counters, ids and the numbers a page shows the user.

Every platform writes its figures the way its readers write them: 万/千/亿 for a
Chinese audience, K/M/B for an English one, ``1,027,710次观看`` inside a YouTube
label, ``97 views`` inside an X ``aria-label``. Three near-identical copies of
this parsing existed (``base._number_in``, ``video.cn_count``,
``xhs._extract_count_from_text``), which meant a fourth platform had to pick one
and hope. This module is that one.

Deliberate limits:

* Nothing here invents a number. An unlabelled or unparseable string is ``0``,
  and a caller that must distinguish "zero" from "unreadable" says so by
  checking the string first — a fabricated count is worse than a blank column.
* ``cn_count`` keeps returning an int even for a float-ish label, because every
  consumer writes it into a spreadsheet column.
"""

import re

#: Multipliers that appear in the wild on the platforms this project crawls.
_UNITS = {
    '万': 10_000,
    '千': 1_000,
    '亿': 100_000_000,
    'w': 10_000,  # douyin/x shorthand: ``1.2w``
    'k': 1_000,
    'm': 1_000_000,
    'b': 1_000_000_000,
}

_NUMBER_RE = re.compile(r'(\d+(?:[.,]\d+)?\s*)([万亿千wkmb]?)', re.IGNORECASE)
_DIGITS_RE = re.compile(r'\d+')


def clean(text) -> str:
    """Strip the separators and whitespace a rendered counter is full of.

    ``1,027,710``, `` 2346万 次观看 `` and ``5.9\\n万`` all have to reach the same
    parser, so the normalising step is shared rather than open-coded per caller.
    """
    if text is None:
        return ''
    if isinstance(text, bool):
        # A JSON flag is not a count, but ``True`` reaching a counter column has
        # happened; reading it as 1 keeps the arithmetic honest and silent.
        return str(int(text))
    if isinstance(text, (int, float)):
        return str(text)
    return re.sub(r'[,，\s]+', '', str(text))


def parse_count(text) -> int:
    """First plausible number in *text*, honouring 万/千/亿 and K/M/B.

    Returns 0 when there is no digit at all: a bare word like ``点赞`` or
    ``独白`` must not become ``0`` by accident of a caller that forgot to check,
    but it also must not raise mid-crawl. Callers that need the difference test
    :func:`has_count` first.
    """
    cleaned = clean(text)
    match = _NUMBER_RE.search(cleaned)
    if not match:
        return 0
    digits = match.group(1).replace(',', '').replace('，', '')
    try:
        value = float(digits)
    except ValueError:
        return 0
    unit = match.group(2).lower()
    if unit in _UNITS:
        value *= _UNITS[unit]
    return int(value)


def has_count(text) -> bool:
    """Whether *text* carries a digit (i.e. whether :func:`parse_count` saw evidence)."""
    return bool(_DIGITS_RE.search(clean(text)))


def first_int(text) -> int:
    """The first run of digits, ignoring any unit — for labels already expanded.

    ``"23,462,998次观看"`` is the exact figure behind a ``2346万`` rounded label;
    reading it with :func:`parse_count` would stop at ``23``.
    """
    cleaned = clean(text)
    match = _DIGITS_RE.search(cleaned or '')
    return int(match.group()) if match else 0


def to_int(value, default: int = 0) -> int:
    """A JSON field that may be a string, a float or missing → an int."""
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        # ``"1.2万"`` arrives as a string far too often for a caller to pre-parse.
        parsed = parse_count(value)
        return parsed if parsed else default
