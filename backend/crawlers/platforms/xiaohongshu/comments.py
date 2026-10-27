"""xiaohongshu comments: the DOM-walker tuple adapter and the panel walk that feeds it."""

import contextlib
import re

from crawlers.commenting.protocol import BLOCKED, OK
from crawlers.commenting.walks import register
from crawlers.engine import times
from crawlers.engine.wall import looks_blocked
from i18n import t


def parse_xhs_comments(items) -> list:
    """Takes [(author, text, date, likes)] tuples scraped by the DOM walker."""
    return [
        {
            '平台': 'xiaohongshu',
            '文章URL': url,
            '评论者': author,
            '评论者主页': '',
            '评论内容': text,
            # The panel's own date cell, which is a relative wording for anything recent
            # ("3小时前"): converted here, because a time series built on the site's words
            # silently loses every recent comment. Unrecognised text is kept as it came.
            '评论时间': times.absolute(date),
            '点赞数': likes,
            '楼层': idx,
        }
        for idx, (url, author, text, date, likes) in enumerate(items, 1)
    ]


#: How many screens one 小红书 comment panel is scrolled before the walk gives up on it. This is
#: OUR budget, not the site's end, so when it runs out on a panel that is STILL mounting comments
#: the walk says so by name — the same shape the zhihu walk uses (``PANEL_ROUNDS`` +
#: ``comment.zhihuPanelCapped``) and the bug douyin's "no round budget" fix removed: a fixed number
#: that ends the walk quietly makes 「怎么采不满」 look like 「这条笔记就这么多评论」.
SCROLL_ROUNDS = 12


@register('xiaohongshu')
def walk(session, url: str, limit: int) -> tuple:
    """One note's comments, read off the mounted ``.comment-item`` cards."""
    session.driver.get(url)
    session.nap(5)
    if looks_blocked(session.body_head()):
        return [], BLOCKED
    seen, rows = set(), []
    for _round in range(SCROLL_ROUNDS):
        found = []
        for card in session.driver.find_elements('css selector', '.comment-item'):
            author = _first_text(session, card, '.author-wrapper .name, .name')
            text = _first_text(session, card, '.content')
            date = _first_text(session, card, '.date')
            likes = _first_number(session, card, '.like .count, .like-wrapper .count')
            key = (author, text)
            if not text or key in seen:
                continue
            seen.add(key)
            found.append((url, author, text, date, likes))
        rows.extend(parse_xhs_comments(found))
        if session.may_stop() or not found or (limit and len(rows) >= limit):
            break
        _scroll_panel(session)
        session.nap(1.2)
    else:
        # The ``for`` ran every round without a ``break``, so the last round still found new
        # comments (an empty one would have broken above). The panel was cut short by OUR number,
        # not by the site running out — name it, never return OK as though the thread were done.
        session.log(t('comment.xhsPanelCapped', url=url, rows=len(rows), rounds=SCROLL_ROUNDS))
    return (rows[:limit] if limit else rows), OK


def _first_text(session, root, selector) -> str:
    for el in root.find_elements('css selector', selector):
        text = session.safe_text(el)
        if text:
            return text
    return ''


def _first_number(session, root, selector) -> int:
    text = _first_text(session, root, selector)
    m = re.search(r'\d+', text or '')
    return int(m.group()) if m else 0


def _scroll_panel(session):
    script = """
    var box = document.querySelector('.note-scroller') || document.scrollingElement || document.body;
    var step = box === document.body ? 1200 : box.scrollHeight;
    box.scrollBy(0, step);
    window.scrollBy(0, 800);
    """
    with contextlib.suppress(Exception):
        session.driver.execute_script(script)
