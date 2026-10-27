"""zhihu comments: the per-panel row builder, the panel read and the walk.

This file owns both halves: :data:`PANEL_JS` measures a live comment panel and
:func:`parse_zhihu_comments` turns what it read into rows, in the columns the export shows.

Two columns are here because a measurement said what the panel does and does not hold
(``backend/test_zhihu_comment_dom.py``, two real panels, 22 items):

* **评论时间** is on the page — relative for recent comments (「14 小时前」), absolute for old ones
  (「2019-08-15」) — so it is read. It used to be written as ``''`` without looking, and the relative
  half then sat in the column as the site's own words: a time series over it loses exactly the
  comments a live event is about, so both shapes go through ``engine.times.absolute`` here.
* **点赞数** is not reachable as a button, an ``aria-label`` or a bare number anywhere in an item's
  own subtree, so it is published as ``''``. It used to be a hard ``0``, which is a number the user
  reads as "nobody liked this" about a column this crawler never asked the site for.
"""

import contextlib
import re

from crawlers.commenting.protocol import BLOCKED, OK
from crawlers.commenting.walks import register
from crawlers.engine import times
from crawlers.engine.wall import looks_blocked
from i18n import t


def parse_zhihu_comments(url: str, items) -> list:
    """One panel's readings (``{text, author, href, time, parent}``) into rows.

    ``author`` is empty only when the comment's OWN subtree holds no ``/people/`` link at all.
    The reader refuses to climb higher than that on purpose: an ancestor wide enough to be
    another comment's header would name the wrong person, and a wrong name is worse than none.

    ``parent`` is the index (in the same read) of the comment this one replies to, or -1. Measured:
    nested replies do not exist in the DOM until 「展开其中 N 条回复」 is clicked, and on one answer
    the items whose author sat outside their own subtree were exactly those — so the column both
    keeps a thread readable and tells a future reader whether a blank author means 「anonymous」 or
    「a reply, whose header lives one wrapper deeper」.
    """
    rows = []
    index = 0
    for one in items:
        text = str(one.get('text') or '').strip()
        if not text:
            continue
        index += 1
        parent = one.get('parent')
        rows.append(
            {
                '平台': 'zhihu',
                '文章URL': url,
                '评论者': str(one.get('author') or ''),
                '评论者主页': str(one.get('href') or ''),
                '评论内容': text,
                # Zhihu prints a relative wording for recent comments; converted at the row
                # boundary so every platform's 评论时间 is one format.
                '评论时间': times.absolute(one.get('time')),
                '点赞数': '',
                '楼层': index,
                '父楼层': (int(parent) + 1) if isinstance(parent, int) and parent >= 0 else '',
            }
        )
    return rows


#: One read per panel, in the page. The shape of this script is the measurement
#: (``backend/test_zhihu_comment_dom.py``): the author anchor lives at the FIRST ancestor of
#: ``.CommentContent`` for most items, but 2 of 12 items on a real panel answered only at
#: depth 4 — inside a node that already spans their neighbours. A fixed-depth climb therefore
#: returns either ``''`` or, worse, the person who posted next door. So the climb is bounded
#: by a structural fact instead: stop as long as the candidate still holds exactly one
#: comment body. That node is this comment, and nothing read inside it can belong to another.
#:
#: The time pattern covers both shapes the panel uses (relative for recent, absolute for old).
#: No like count is looked for: measured over 22 items, neither an ``aria-label``, a button
#: nor a bare number carries one, and a column of invented zeros is a worse answer than a
#: blank one (see :func:`parse_zhihu_comments`).
PANEL_JS = r"""
return (function () {
    var TIME = /(\d+\s*(分钟|小时|天|个月|年)前|\d{4}-\d{1,2}-\d{1,2}|昨天|今天|\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})/;
    function bodyText(el) {
        return (el.textContent || '').replace(/\s+/g, ' ').trim();
    }
    function ownScope(node) {
        var best = node, up = node.parentElement;
        while (up && up.querySelectorAll('.CommentContent').length === 1) {
            best = up;
            up = up.parentElement;
        }
        return best;
    }
    var out = [];
    var bodies = document.querySelectorAll('.CommentContent');
    for (var i = 0; i < bodies.length; i++) {
        var text = bodyText(bodies[i]);
        if (!text) { continue; }
        var scope = ownScope(bodies[i]);
        var author = '', href = '';
        var links = scope.querySelectorAll('a[href*="/people/"]');
        for (var p = 0; p < links.length; p++) {
            var name = bodyText(links[p]);
            if (name) { author = name; href = links[p].href || ''; break; }
        }
        var when = '';
        var leaves = scope.querySelectorAll('span, time, div');
        for (var s = 0; s < leaves.length; s++) {
            if (leaves[s].children.length) { continue; }
            var hit = bodyText(leaves[s]).match(TIME);
            if (hit) { when = hit[0]; break; }
        }
        var parent = -1;
        var enclosing = bodies[i].parentElement ? bodies[i].parentElement.closest('.CommentContent') : null;
        if (enclosing) {
            for (var q = 0; q < bodies.length; q++) {
                if (bodies[q] === enclosing) { parent = q; break; }
            }
        }
        out.push({text: text, author: author, href: href, time: when, parent: parent});
    }
    return out;
})();
"""

#: Scroll the panel's OWN box to its bottom. Measured (``backend/test_zhihu_comment_structure.py``):
#: zhihu has no 「更多」 control on a comment panel at all — the list is lazy-filled by the
#: container (class ``css-34podr``, whose ``scrollHeight`` grew 1302 → 12733 on one answer), and
#: scrolling the WINDOW changes nothing (12 items before, 12 after). So this, not a button hunt,
#: is what feeds the list. Returns how far the box moved, which is the caller's evidence that a
#: bottom was reached and re-read.
PUMP_JS = r"""
return (function () {
    var boxes = [].slice.call(document.querySelectorAll('div, section, ul')).filter(function (n) {
        return n.scrollHeight > n.clientHeight + 200 && n.querySelectorAll('.CommentContent').length;
    });
    if (!boxes.length) { return -1; }
    // The box that holds the MOST comments, not the first one found. Measured reason: opening a
    // reply thread adds an inner scrollable list that also holds ``.CommentContent`` nodes, so a
    // first-match pump can end up scrolling one reply's own list forever while the panel above it
    // never advances — a walk that stalls and stops, reporting a short table as a finished one.
    var best = boxes[0];
    for (var i = 1; i < boxes.length; i++) {
        if (boxes[i].querySelectorAll('.CommentContent').length > best.querySelectorAll('.CommentContent').length) {
            best = boxes[i];
        }
    }
    var before = best.scrollTop;
    best.scrollTop = best.scrollHeight;
    return best.scrollTop - before;
})();
"""

#: How many pump-and-read rounds one panel may take, and how many of them must come back with
#: nothing new (and no reply thread left to open) before the walk believes the panel is done.
#: Both numbers are a *budget the crawler imposes*, so reaching the first one is announced:
#: measured, a 261-comment panel needs ~26 fills of ~10 items, and the alternative to naming
#: the budget is reporting 12 rows as if the site had nothing more (docs/live_test_plan.md §6).
PANEL_ROUNDS = 60
QUIET_ROUNDS = 3

#: The nested-reply opener's own words: 「展开其中 2 条回复」 / 「查看 3 条回复」 / 「全部回复」.
#: The count and the wording between the verb and 回复 both vary (「其中」 is in one of them), so
#: the match is on the verb-plus-回复 shape rather than an exact phrase. Every one of these is a
#: bucket of comments that does not exist in the DOM until clicked (measured: +5 and +29 rows on
#: two answers), so an un-clicked expander is 漏采 by construction.
REPLY_OPENER = re.compile(r'(查看|展开).{0,8}回复|全部回复')


@register('zhihu')
def walk(session, url: str, limit: int) -> tuple:
    """One question/answer page: open every comment button, drain each panel."""
    session.driver.get(url)
    session.nap(6)
    if looks_blocked(session.body_head()):
        return [], BLOCKED
    opened = 0
    rows = []
    for btn in list(session.driver.find_elements('css selector', 'button')):
        text = session.safe_text(btn)
        match = re.search(r'(\d+)\s*条评论', text)
        if not match:
            continue
        # The button's own number is carried into the walk: it is the figure the user can read
        # off the page, so it is the only honest denominator for 「did we get them all」.
        declared = int(match.group(1))
        with contextlib.suppress(Exception):
            session.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', btn)
            session.nap(0.4)
            btn.click()
            opened += 1
            session.nap(2)
            rows.extend(_drain_panel(session, url, limit, declared))
        if limit and len(rows) >= limit:
            break
    if not opened and rows == []:
        # No comment button at all: either 评论已关闭 or the page never
        # rendered the answers — treat as ok-with-nothing, but say so.
        session.log(t('comment.zhihuNoPanels', url=url))
    return (rows[:limit] if limit else rows), OK


def _click_reply_threads(session) -> int:
    """Open every visible 「N 条回复」 thread, so nested comments exist to be read."""
    clicked = 0
    for el in list(session.driver.find_elements('css selector', 'button, a')):
        text = session.safe_text(el)
        if not text or not REPLY_OPENER.search(text):
            continue
        with contextlib.suppress(Exception):
            session.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', el)
            session.nap(0.2)
            el.click()
            clicked += 1
            session.nap(0.4)
    return clicked


def _drain_panel(session, url: str, limit: int, declared: int = 0) -> list:
    collected, seen = [], set()
    quiet = 0
    rounds = 0
    while rounds < PANEL_ROUNDS:
        rounds += 1
        session.driver.execute_script(PUMP_JS)
        session.nap(0.6)
        threads = _click_reply_threads(session)
        batch = session.driver.execute_script(PANEL_JS) or []
        fresh = []
        for row in parse_zhihu_comments(url, batch):
            key = (row['评论者'], row['评论内容'])
            if key in seen:
                continue
            seen.add(key)
            fresh.append(row)
        if fresh:
            session.log(t('comment.zhihuRound', n=len(fresh), total=len(collected) + len(fresh), r=rounds))
        collected.extend(fresh)
        unnamed = sum(1 for row in fresh if not row['评论者'])
        if unnamed:
            # Said once per panel, about a count: an empty 评论者 is a site answer for some
            # rows and a dead selector for others, and the only way the two are told apart
            # later is that this line exists with a number in it.
            session.log(t('comment.zhihuNoAuthor', n=unnamed, total=len(fresh)))
        if limit and len(collected) >= limit:
            return collected[:limit]
        if not fresh and not threads:
            quiet += 1
            if quiet >= QUIET_ROUNDS:
                break
        else:
            quiet = 0
    if rounds >= PANEL_ROUNDS:
        session.log(t('comment.zhihuPanelCapped', n=PANEL_ROUNDS, rows=len(collected)))
    if declared and len(collected) < declared:
        # The site's own number is the denominator the user reads off the page; anything short
        # of it is said out loud, because 「the panel had 12」 and 「we stopped at 12 of 261」 are
        # two different reports and only one of them is checkable.
        session.log(t('comment.zhihuPanelShort', declared=declared, rows=len(collected)))
    return collected
