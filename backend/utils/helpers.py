import io
import os
import re

import pandas as pd

# Longest name we hand to the OS: Windows caps a path component at 255 chars
# and a full path at ~260, and exports live under an already-deep data/ path.
MAX_FILENAME_LENGTH = 100


# The comment router's domain table. Lives here — browser-free and framework-free —
# because THREE callers must agree on it verbatim: crawlers.comments (routing),
# engine.workflow (design-time validation, which must never import crawlers) and
# static/js/workflow.js:urlPlatform (pre-run validation). The frontend contract
# test pins the JS copy against this one.
_COMMENT_DOMAINS = (
    ('zhihu', ('zhihu.com',)),
    ('xiaohongshu', ('xiaohongshu.com', 'xhslink.com')),
    ('weibo', ('weibo.com', 'weibo.cn')),
    ('bilibili', ('bilibili.com',)),
    ('douyin', ('douyin.com', 'iesdouyin.com')),
    # youtu.be is the share-link host: a person pasting a comment target gets
    # ``https://youtu.be/<id>`` far more often than the watch URL, and dropping it
    # would read as "this link is unsupported".
    ('youtube', ('youtube.com', 'youtu.be')),
    ('twitter', ('x.com', 'twitter.com', 'fxtwitter.com', 'vxtwitter.com')),
)


def _host_of(url: str) -> str:
    """The authority part of a link, lowercased and port-stripped.

    Matching a comment link by ``mark in url`` was wrong in both directions: a
    path like ``/weibo.com/…`` on any other host routed as Weibo, and — worse for
    X — ``x.com`` is a substring of ``max.com``, so an unrelated site could be
    handed to the wrong crawler and come back as data with the wrong platform on
    it. So the host is parsed out first, and a link that will not parse is simply
    unsupported rather than guessed at.
    """
    text = str(url or '').strip().lower()
    if not text:
        return ''
    tail = text.split('://', 1)[-1] if '://' in text else text
    return tail.split('/', 1)[0].split('?', 1)[0].split(':', 1)[0].strip()


def _host_matches(host: str, domain: str) -> bool:
    return bool(host) and (host == domain or host.endswith('.' + domain))


def platform_for(url: str) -> str:
    """Which comment adapter handles this article link ('' = unsupported)."""
    host = _host_of(url)
    if not host:
        return ''
    for platform, marks in _COMMENT_DOMAINS:
        if any(_host_matches(host, domain) for domain in marks):
            return platform
    return ''


def comment_platforms() -> tuple[str, ...]:
    """The platforms the comment router can serve, in table order.

    The console tells a user which links it accepts, and that sentence used to name
    them by hand — so the fifth platform landed and two messages kept advertising
    the old four. Read it from the table that actually decides.
    """
    return tuple(platform for platform, _marks in _COMMENT_DOMAINS)


def split_urls(value) -> list[str]:
    """Textareas arrive as one blob: accept a real list, or comma/newline separated text."""
    raw = value if isinstance(value, (list, tuple)) else str(value or '').replace(',', '\n').split('\n')
    return [str(u).strip() for u in raw if str(u).strip()]


def extract_number(text: str) -> int:
    """Extract first integer from text, supporting thousands separators."""
    if not text:
        return 0
    m = re.search(r'\d+', str(text).replace(',', ''))
    return int(m.group(0)) if m else 0


#: The words a stored switch uses for each answer. Three grammars have to agree here
#: because a parameter can arrive as the literal strings the settings panel writes
#: (``renderParamCheckbox`` stores ``'true'``/``'false'``), as a real JSON boolean
#: (an exported-and-reopened workflow, ``/api/analysis/clean``, a hand-written file),
#: or in the Chinese a person types into a draft.
_TRUE_TEXT = frozenset({'true', '1', '1.0', 'yes', 'y', 'on', '是', '真'})
_FALSE_TEXT = frozenset({'false', '0', '0.0', 'no', 'n', 'off', 'none', 'null', 'nan', '否', '不', '假'})


def as_bool(value, default: bool = False) -> bool:
    """Read *value* as a switch, answering *default* when it states nothing.

    Comparing a parameter against the text ``'true'`` is not a boolean test: real
    ``True`` is unequal to ``'true'``, so every caller that sent the value a JSON
    document actually holds got the opposite behaviour — 升序 sorted descending. This
    reads the value instead of matching one spelling of it.

    Absent, blank and unrecognised answer *default* rather than False, because each of
    these parameters has its own declared default (the figure the panel showed before
    anyone touched it) and "no answer" must not become "the other answer". A number is
    interpreted the way pandas interprets a truthy cell: non-zero is on.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value != value:  # a NaN is a missing value, not the answer "off"
            return default
        return value != 0
    text = str(value).strip().lower()
    if text in _TRUE_TEXT:
        return True
    if text in _FALSE_TEXT:
        return False
    return default


def split_names(value) -> list[str]:
    """A list of column names, from whichever shape the caller wrote.

    A real list is what the node executor sends after normalizing the settings box; a
    comma-separated string is what that box holds and what ``/api/analysis/run`` and a
    workflow file write. Both have to mean the same list — one path used to, and the
    other iterated ``'名称, 城市'`` as its **characters**, a step that matched nothing and
    reported success.

    The reading of a non-string is the one the settings panel has always had: falsy
    (``0``, ``False``, ``None``, ``''``) is "no names", and anything else is
    stringified, so ``True`` asks for a column literally called ``True``.
    """
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or '').split(',') if part.strip()]


def sanitize_filename(name: str) -> str:
    """Make *name* safe to use as a single path component.

    Strips directory separators (so a caller-supplied name can never escape the
    target directory), control characters, leading/trailing dots and spaces, and
    caps the length so the write itself cannot fail with a path-too-long error.
    """
    clean = re.sub(r'[\x00-\x1f\\/*?:"<>|]', '_', str(name or ''))
    clean = clean.strip().strip('.')
    # Keep the extension visible when truncating a long name.
    if len(clean) > MAX_FILENAME_LENGTH:
        root, ext = os.path.splitext(clean)
        keep = max(1, MAX_FILENAME_LENGTH - len(ext))
        clean = root[:keep] + ext
    return clean


def df_to_csv_string(df: pd.DataFrame) -> str:
    """Convert DataFrame to CSV string."""
    output = io.StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    return output.getvalue()


def merge_results(results: list, _key: str = 'platform') -> pd.DataFrame:
    """Merge multiple result lists into a single DataFrame."""
    all_items = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)
        elif isinstance(r, dict):
            all_items.append(r)
    return pd.DataFrame(all_items)
