"""weibo comments: the ``buildComments`` JSON adapter and the id/endpoint helpers."""

import re

from .comments_base import _strip_tags
from .engine import times


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
