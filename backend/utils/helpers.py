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
)


def platform_for(url: str) -> str:
    """Which comment adapter handles this article link ('' = unsupported)."""
    u = str(url or '').strip().lower()
    for platform, marks in _COMMENT_DOMAINS:
        if any(mark in u for mark in marks):
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
