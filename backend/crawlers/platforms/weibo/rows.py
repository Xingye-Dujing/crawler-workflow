"""Weibo's value-shaping rules: what an address, a timestamp, a card's HTML and a board entry mean.

Separated from the walk because every rule here was measured on a *value* rather than on an
interaction: which digit shapes actually address a person, that the endpoint and the search page
stamp the same column in two different formats, that a topic's name is not in the field named
``title``. Those claims are about data, and they used to be reachable only by instantiating a
crawler.

One honest limit on that claim: :func:`hot_row` uses ``as_index``, which lives with the crawl
contract in :mod:`crawlers.core.crawler` (it is the cursor-field coercion every platform's resume
path shares). So importing this module loads that module — what it does NOT need is a driver, a
selector or a site.
"""

import re
from urllib.parse import quote, unquote

from crawlers.core.crawler import as_index
from crawlers.engine import times
from crawlers.engine.counters import parse_count

# The author walk addresses a person by their numeric uid only; the mymblog endpoint
# honours `uid`, and a screen name addresses nobody (measured).
_UID_PATTERNS = (
    re.compile(r'(?:^|\.)weibo\.com/u/(\d{5,})'),
    re.compile(r'(?:^|//)m?\.?weibo\.(?:com|cn)/u/(\d{5,})'),
    re.compile(r'weibo\.com/(\d{5,})(?:[/?#]|$)'),
    re.compile(r'^(\d{5,})$'),
)


def weibo_uid(value: str) -> str:
    """Digits, a ``weibo.com/u/<uid>`` profile link, a ``weibo.com/<uid>/<post>`` link
    or the search row's own 用户链接 → the numeric uid.

    Anything without one of those digit shapes is refused with ``''``: opening a
    guessed profile would report "this person posted nothing" about a page that is
    not theirs, which is worse than saying the address was not a uid. The ``/u/<id>``
    form is matched only on a weibo host (a taobao ``/u/123456`` is a different
    person), and query/fragment junk is stripped first because the real 用户链接
    carries ``?refer_flag=…``.
    """
    raw = str(value or '').strip().split('#')[0].split('?')[0]
    if not raw:
        return ''
    for pattern in _UID_PATTERNS:
        match = pattern.search(raw)
        if match:
            return match.group(1)
    return ''


def hot_row(item: dict, rank: int) -> dict | None:
    """One board entry, flattened. ``word`` is the topic; ``word_scheme`` carries
    the ``#…#`` form the site publishes. ``note`` duplicates ``word`` on the
    measured rows, so it is not a column of its own."""
    word = str(item.get('word') or '').strip()
    if not word:
        return None
    scheme = str(item.get('word_scheme') or '').strip() or word
    heat = item.get('num')
    return {
        '排名': as_index(item.get('realpos'), rank),
        '标题': word,
        '话题': scheme,
        '热度': as_index(heat, 0) if str(heat or '').strip() else parse_count(str(item.get('label') or '')),
        '链接': f'https://s.weibo.com/weibo?q={quote(scheme)}',
    }


def normalise_time(value) -> str:
    # The endpoint stamps 'Wed Sep 24 15:42:51 +0800 2026'; the search page shows the
    # site's own wording instead — an absolute Chinese date for old posts and a relative
    # label ("3小时前") for recent ones. Two shapes in one column is the documented defect,
    # so both are resolved to one readable absolute form here rather than shipping an
    # English stamp beside a Chinese label beside a relative word. The comment engine
    # parses the same stamp, so the formats live in engine/times.py — a second copy here
    # is what the helper exists to prevent.
    return times.absolute(value)


def strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def author_topics(struct) -> str:
    # topic_struct carries {topic_url, title} with an EMPTY title; the name lives
    # url-encoded between %23…%23 (#…#) in topic_url's q= parameter.
    names = []
    for item in struct or []:
        url = str((item or {}).get('topic_url') or '')
        match = re.search(r'q=([^&]+)', url)
        if not match:
            continue
        label = unquote(match.group(1)).strip('#').strip()
        if label and label not in names:
            names.append(label)
    return ' | '.join(names)


def page_url(base_url: str) -> str:
    cleaned = re.sub(r'[?&]page=\d+', '', base_url)
    return f'{cleaned}{"&" if "?" in cleaned else "?"}page='
