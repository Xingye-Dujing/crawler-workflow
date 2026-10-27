"""weibo comments: the ``buildComments`` JSON endpoint, its rows and its walk."""

import json
import re

from crawlers.commenting.protocol import DEAD, OK, _strip_tags, as_count
from crawlers.commenting.walks import register
from crawlers.engine import times
from i18n import t


def _user_home(user: dict) -> str:
    """The commenter's own page, not their avatar.

    Measured 2026-09-28: the row's ``user`` object carries BOTH ``profile_image_url`` (a picture) and
    ``profile_url='/u/5893846418'`` (the person), and the column is named 评论者主页 — the old code read the
    image, so every row handed the user a jpg URL where a home page should be. ``profile_url`` is
    protocol-relative-but-hostless, so the origin is added rather than the value dropped.
    """
    raw = str(user.get('profile_url') or '').strip()
    if raw.startswith('http'):
        return raw
    if raw.startswith('/'):
        return f'https://weibo.com{raw}'
    uid = str(user.get('idstr') or user.get('id') or '').strip()
    return f'https://weibo.com/u/{uid}' if uid else ''


def _as_int(value) -> int:
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _one_row(item: dict, article_url: str, fallback_floor: int, parent_floor: int = 0) -> dict | None:
    """One comment object → a row. Missing fields degrade to empty, never raise.

    Every column here used to be a guess:

    * **点赞数** read ``like_count``, a key the desktop endpoint does not send — measured, the row carries
      ``like_counts`` (``like_count`` is the *mobile* shape, so both are honoured). The old miss made every
      comment look unloved at 0, the same defect zhihu's 点赞数 just had.
    * **楼层** came from a per-page ``enumerate``, and the walker calls this adapter **once per page**, so
      page 2 restarted at 1 and a 119-row table held six rows called "1". The site prints its own
      ``floor_number`` (a whole-thread number: measured, a 30-comment thread's 22 top-level rows cover
      floors 1..30 minus exactly the 8 nested ones), so that is the value. The index survives only as a
      fallback for a top-level row that carries no floor at all — and NOT for a reply, because a reply's
      ``floor_number`` is measured ``0``: the site is saying it has no floor, and substituting "position
      inside its parent's preview" would re-create the six-rows-called-1 defect this bullet describes,
      one column meaning two numbering systems.
    * **评论时间** was stored verbatim, which on this endpoint is ``'Sun Jul 26 09:49:46 +0800 2026'`` —
      an English stamp in a column that must sort and chart as one thing. The author path already
      normalised it; ``engine/times.py`` is now the one place that shape is read.
    * **评论内容** was read out of ``text`` and stripped, which is right for a text comment and **destroys
      an emoji-only one**: measured, such a row's ``text`` is a run of ``<img alt="[可怜]" …>`` tags and the
      strip leaves ``''`` — an empty row that still carries an id, an author and a timestamp, so no count,
      summary or preview can see that content was lost. The payload's own ``text_raw`` (``'[可怜][鼓掌][黑线]'``)
      is the text, and it is now what the column reads, exactly as ``_author_row`` has always done.
    * **父楼层** is new: ``is_sub_cmt`` (measured on a preview child) and ``rootid != id`` both mark a
      reply, so the two shapes are told apart from the payload rather than by call-site position.
    """
    if not isinstance(item, dict):
        return None
    user = item.get('user') if isinstance(item.get('user'), dict) else {}
    # A row is a row even when the payload has no id for it: 评论ID exists to de-duplicate the pages
    # this walker fetches (and to key the parent link), and an empty one simply opts out of that —
    # it may not delete a comment the site showed.
    cid = str(item.get('id') or '')
    root = str(item.get('rootid') or '')
    is_child = bool(item.get('is_sub_cmt')) or bool(parent_floor) or bool(root and cid and root != cid)
    site_floor = _as_int(item.get('floor_number'))
    if site_floor:
        floor = site_floor
    elif is_child:
        floor = ''
    else:
        floor = fallback_floor
    likes = item.get('like_counts')
    if likes is None:
        likes = item.get('like_count')
    # The body is read from ``text_raw`` first, with the stripped HTML only as a fallback (U40, caught by a
    # live comment table). An emoji-only comment arrives as a run of image tags —
    # ``<img alt="[可怜]" src="…png" />`` — so ``_strip_tags`` eats the comment's entire content and the row
    # keeps its author, its time and its id while 评论内容 comes back empty. Measured in
    # ``scratchpad/weibo_*.json``: the same object carries ``text_raw='[可怜][鼓掌][黑线]'``, and **every** real
    # comment with a stripped-empty ``text`` had a non-empty ``text_raw`` (17 of 17; the four lacking that
    # key entirely are DOM records an earlier probe saved, not comments). This platform's post rows have
    # read it this way all along (``WeiboCrawler._author_row`` prefers ``text_raw`` then strips); the
    # comment adapter never copied the rule, and an empty row is the half of 漏采 nobody sees in a summary.
    body = str(item.get('text_raw') or '').strip() or _strip_tags(str(item.get('text') or ''))
    return {
        '平台': 'weibo',
        '文章URL': article_url,
        '评论者': str(user.get('screen_name') or ''),
        '评论者主页': _user_home(user),
        '评论内容': body,
        # ``absolute``, not the RFC-822-only helper: the JSON path is normally the RFC stamp,
        # but the same column also carries the site's own wording when the payload falls back
        # to it, and a relative one there would be a time series' missing row.
        '评论时间': times.absolute(item.get('created_at')),
        '点赞数': _as_int(likes),
        '楼层': floor,
        # '' and not 0: a row the payload flags as a reply without naming its parent has no
        # parent floor to report, and a zero would read as floor number zero in a chart.
        '父楼层': (parent_floor or '') if is_child else '',
        '评论ID': cid,
    }


def parse_weibo_comments(payload: dict, article_url: str) -> list:
    """buildComments JSON → rows, **including the nested replies the envelope hides**.

    ``fetch_level=0`` returns top-level comments only: measured, a thread whose own envelope says
    ``total_number: 30`` hands back 22 rows, and the missing floors are exactly its 楼中楼. No request shape
    this session tried would return them as a list (``docs/crawler_notes.md`` 微博第 0 步), but every parent
    row already carries ``comments: [one child]`` — the site's own preview of the thread under it. Those
    previews are harvested here (they cost nothing and were being thrown away), each tagged with the
    parent's 楼层 so a reader can see what it replies to; the rest of the gap is named by the walker, never
    silently dropped.
    """
    rows = []
    for i, item in enumerate(payload.get('data') or [], 1):
        row = _one_row(item, article_url, i)
        if not row:
            continue
        rows.append(row)
        children = item.get('comments')
        if not isinstance(children, list):
            continue
        for j, child in enumerate(children, 1):
            kid = _one_row(child, article_url, j, parent_floor=row['楼层'])
            if kid and kid['评论ID'] != row['评论ID']:
                rows.append(kid)
    return rows


def weibo_bid(url: str) -> str:
    """Extract the weibo id — /detail/<mid> or weibo.com/<uid>/<bid>."""
    m = re.search(r'/detail/(\d+)', url or '')
    if m:
        return m.group(1)
    m = re.search(r'weibo\.com(?:/.*)?/([A-Za-z0-9]{6,})', url or '')
    return m.group(1) if m else ''


def weibo_show_js(bid: str) -> str:
    return f'https://weibo.com/ajax/statuses/show?id={bid}'


def weibo_comments_js(mid: str, max_id: int = 0, count: int = 20) -> str:
    return (
        'https://weibo.com/ajax/statuses/buildComments?is_reload=1&id='
        f'{mid}&is_show_bulletin=2&is_mix=0&count={count}&flow=0&fetch_level=0&max_id={max_id}'
    )


#: How many consecutive pages may add nothing new before the walk calls it finished.
#: This is NOT a page budget — the repo has none any more (README, and the 2026-09-25 entry in
#: ``docs/crawler_notes.md`` that deleted every backend round/page ceiling). It answers one specific
#: cursor failure measured here: this API hands back a live ``max_id`` whose rows are already in the
#: table, and a walk that noticed that only through a constant would keep paying round trips.
EMPTY_ROUNDS = 2


@register('weibo')
def walk(session, url: str, limit: int) -> tuple:
    """One weibo post's comments, paged through its own JSON endpoint fetched *in page*."""
    bid = weibo_bid(url)
    if not bid:
        return [], DEAD
    try:
        # The in-page fetch is same-origin only: a search flow leaves the
        # browser on s.weibo.com, where fetching weibo.com/ajax is a CORS
        # rejection that reads as a dead link. Park on the right host first.
        current = session.driver.current_url or ''
        if not current.startswith('https://weibo.com'):
            session.driver.get('https://weibo.com/')
            session.nap(2)
    except Exception:
        pass
    try:
        raw = session.fetch_in_page(weibo_show_js(bid))
        show = json.loads(raw)
    except Exception:
        session.log(t('comment.weiboShowFailed', url=url))
        return [], DEAD
    mid = str(show.get('id') or show.get('mid') or '')
    if not mid:
        return [], DEAD
    # The site's own denominator for this thread. Measured 2026-09-28 the three places that print it
    # agree (the search card 「30」, ``statuses/show.comments_count``, the page's ``total_number``), so
    # a table that comes back shorter is knowable *while crawling* — which is the whole reason to read
    # it. ``trendsText`` also says 「已加载全部评论」 on a 22-of-30 walk, so that sentence is not a
    # verdict and is never consulted.
    declared = as_count(show.get('comments_count'))
    rows, seen, max_id, page, empty_rounds = [], set(), 0, 0, 0
    # Which exit ended the walk decides what may be SAID about its length. Three of these endings are
    # this code's own doing or the user's ask, and none of them is a statement about the thread: the
    # shortfall may only be attributed to the site when the cursor itself ran out.
    ended = 'cursor'
    while True:
        try:
            batch = json.loads(session.fetch_in_page(weibo_comments_js(mid, max_id)))
        except Exception:
            ended = 'fetch'
            break
        items = batch.get('data') or []
        before = len(rows)
        for row in parse_weibo_comments({'data': items}, url):
            key = str(row.get('评论ID') or '')
            if key and key in seen:
                continue
            seen.add(key)
            rows.append(row)
        page += 1
        declared = declared or as_count(batch.get('total_number'))
        max_id = batch.get('max_id') or 0
        if not items or not max_id:
            break
        if len(rows) == before:
            # The cursor moved and the page refilled rows already in the table. Named, because the
            # alternative is a table that quietly stopped growing while the console said nothing —
            # and this API really does hand back a live ``max_id`` over replayed rows.
            empty_rounds += 1
            if empty_rounds >= EMPTY_ROUNDS:
                ended = 'replay'
                session.log(t('comment.weiboReplay', page=page, rows=len(rows)))
                break
        else:
            empty_rounds = 0
        if limit and len(rows) >= limit:
            # The user's own number, not the site's. Reporting the gap against ``total_number`` here
            # would blame the thread for the ask: 评论上限 20 on a 749-comment post is not a
            # shortfall, and the table is exactly as long as the node was told to make it.
            ended = 'limit'
            break
        session.nap(0.8)  # polite page interval on the comment API
    table = rows[:limit] if limit else rows
    # **The gap is measured against what the walk received, never against the truncated table** (U41,
    # caught by the live D5 cell). A thread that reports 3 comments, hands all 3 to the walker, and is
    # then cut to 评论上限 2 used to print 「站点写着 3 条，本表只有 2 条 —— 差额是楼中楼」: the cursor
    # died on the same page that crossed the limit, so ``ended`` stayed ``'cursor'`` and the sentence
    # blamed the site for the user's own number — the exact thing the branch above exists to prevent,
    # arriving by a path that branch does not see. ``len(rows)`` is the only number that answers
    # "did the site give less than it said"; when the user's limit then shortens the table, that is
    # not a gap and nothing is said about it.
    if ended == 'cursor' and declared and len(rows) < declared:
        session.log(t('comment.weiboShort', declared=declared, rows=len(rows), gap=declared - len(rows)))
    if ended == 'fetch':
        # The one exit of this walk that used to say nothing at all. Every other ending is either the
        # site's answer (the cursor ran out, and ``comment.weiboShort`` names the gap against its own
        # number) or the user's ask (``limit``); a request that died mid-thread is neither, and the
        # table it leaves behind is shorter than the thread with no line anywhere to point at. Naming
        # it is also the difference between 「继续」 and a re-crawl: the cursor already holds the page
        # this walk reached.
        session.log(
            t(
                'comment.weiboFetchDied',
                page=page,
                rows=len(rows),
                declared=declared or '?',
                gap=(declared - len(rows)) if declared and len(rows) < declared else 0,
            )
        )
    return table, OK
