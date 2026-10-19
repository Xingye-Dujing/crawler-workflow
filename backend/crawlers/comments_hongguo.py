"""红果短剧 comment payloads: the pure reader that turns harvested JSON into rows.

The comments of a 红果 drama live only behind the app protocol
(``api5-normal-lq.fqnovel.com/novel/commentapi/comment/list/{group_id}/v1/``), whose
signature (x-medusa/x-helios) this tool deliberately does NOT reimplement — measured,
even a byte-identical replay with a fresh ticket answers ``Code 110001``. Instead the
desktop player is run behind our own mitmproxy and this module reads the JSON the
player legitimately fetched (full measurement in ``docs/crawler_notes.md`` 红果短剧).

Two payload shapes reach here, both keyed by ``group_id`` (one EPISODE's comment page):

* ``comment/list`` — ``data.common_list_info{cursor,has_more,total}`` + ``data_list``;
* ``reply/list`` — the same envelope for one comment's children (``父楼层`` links back).

The walker feeds every entry through :func:`hg_comment_rows`, which drops the
danmaku-guide rows the feed injects (measured: ``create_timestamp == 0`` and an
``expand.danmaku_activity_info`` block; their ids are tiny like ``11114`` against a
real comment's ``7697905336342594366``) and maps the rest onto the standard comment
columns every other platform's table already uses.
"""

import re

from .comments_base import _stamp

#: One row of a 红果 comment page. ``data_type`` 4 is a comment, anything else is
#: refused; the danmaku-guide rows are comments too, so they are told apart by the
#: activity block and the zero timestamp, never by id length alone.
_DANMAKU_ACTIVITY = 'danmaku_activity_info'


def _as_int(value) -> int:
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


def hg_series_id(url: str) -> str:
    """The ``series_id`` a 红果 detail link names ('' when the link names none).

    The board's own 链接 column is ``https://hongguoduanju.com/detail?series_id=<id>``
    (measured), and a pasted link is that same shape. A bare id is accepted too — the
    panel's placeholder shows the link, but a person who copied the id from anywhere
    should not be told their input is not a number.
    """
    text = str(url or '').strip()
    if not text:
        return ''
    m = re.search(r'[?&]series_id=(\d{6,})', text)
    if m:
        return m.group(1)
    if re.fullmatch(r'\d{10,}', text):
        return text
    return ''


def hg_page_title(html_text: str) -> str:
    """The drama name the detail page's own ``<title>`` prints.

    Measured: ``<title>剧名_红果短剧免费短剧大全在线观看_红果短剧</title>`` — the name is the
    part before the first ``_``. This is the ONLY drama-level fact read from the web
    document (the main series payload is fetched client-side and is not in the SSR
    HTML), and the harvester uses it as the search phrase inside the player.
    """
    m = re.search(r'<title[^>]*>(.*?)</title>', str(html_text or ''), re.S | re.I)
    if not m:
        return ''
    return m.group(1).split('_')[0].strip()


def _user_name(user: dict) -> str:
    """The commenter's display name, wherever this endpoint happened to put it.

    A logged-in read carries ``user_info.base_info.user_name`` (measured 2026-10-19);
    an anonymous feed read carries ``user_info = {user_id}`` only — the name column
    then stays blank, never fabricated. The passport spellings are tried after it so
    a payload shape change degrades to blank loudly in the table, not to a wrong name.
    """
    if not isinstance(user, dict):
        return ''
    base = user.get('base_info') if isinstance(user.get('base_info'), dict) else {}
    for src, key in ((base, 'user_name'), (base, 'screen_name'), (user, 'user_name'), (user, 'screen_name')):
        name = str(src.get(key) or '').strip()
        if name:
            return name
    return ''


def _one_comment(
    entry: dict,
    article_url: str,
    floor: int,
    parent_floor: int = 0,
    drama_title: str = '',
    episode_index: int = 0,
) -> dict | None:
    """One ``data_list`` entry → a comment row; ``None`` when it is not one.

    A danmaku-guide row is the feed's own prompt (「发送弹幕…」), not a comment: it carries
    an activity block and ``create_timestamp == 0``. Dropping it is the difference
    between a comment table and a table that claims the site's prompts are opinions.

    ``文章URL`` keeps its shared name on purpose: it is the key every platform's comment
    table already joins on (8 crawlers emit it, the cross-platform analyses read it), so
    renaming it here would split 红果 off the shared tables over a matter of wording. The
    drama's own words live beside it — ``剧名`` and ``集序号`` — because a 短剧 comment is
    about an EPISODE, and a payload id nobody can read is not a name.
    """
    if not isinstance(entry, dict):
        return None
    c = entry.get('comment')
    if not isinstance(c, dict):
        return None
    common = c.get('common') if isinstance(c.get('common'), dict) else {}
    expand = c.get('expand') if isinstance(c.get('expand'), dict) else {}
    stamp = _as_int(common.get('create_timestamp'))
    if expand.get(_DANMAKU_ACTIVITY) or stamp == 0:
        return None
    content = common.get('content') if isinstance(common.get('content'), dict) else {}
    text = str(content.get('text') or '').strip()
    if not text:
        # A comment with no body cannot be analyzed; the site itself does not show one.
        return None
    stat = c.get('stat') if isinstance(c.get('stat'), dict) else {}
    user = common.get('user_info') if isinstance(common.get('user_info'), dict) else {}
    cid = str(c.get('comment_id') or '')
    return {
        '平台': 'hongguo',
        '文章URL': article_url,
        # The two facts a 短剧 table actually needs and the payload cannot print itself:
        # the drama's name (the web detail ``<title>``, or the 剧名 the walk was fed) and
        # which episode of it this thread belongs to. A walk fed by name carries no web
        # link at all — ``文章URL`` then stays blank, never invented from a search guess.
        '剧名': drama_title,
        '集序号': episode_index or '',
        '评论者': _user_name(user),
        # The payload hands out a numeric user_id and no profile URL; a link built here
        # would be a guess at a page this app never shows (评论者主页 blank, not invented).
        '评论者主页': '',
        '评论内容': text,
        # ``_stamp``, not ``times.absolute``: this endpoint hands back a bare epoch
        # second (measured), and the read-time door above only knows printed wordings.
        '评论时间': _stamp(stamp),
        '点赞数': _as_int(stat.get('digg_count')),
        '楼层': floor,
        '父楼层': parent_floor or '',
        '评论ID': cid,
        # Facts a reader may want for one drama's table: which episode and which parent.
        # ``分集ID`` is the ``group_id`` of ONE episode's thread (a drama has as many of
        # them as it has episodes) — it is not the drama's id, which is ``series_id``.
        '分集ID': str(common.get('group_id') or ''),
        '子回复数': _as_int(stat.get('reply_count')),
    }


def hg_comment_rows(
    payload: dict,
    article_url: str,
    first_floor: int = 1,
    parent_floor: int = 0,
    drama_title: str = '',
    episode_index: int = 0,
) -> tuple:
    """A ``comment/list`` / ``reply/list`` envelope → ``(rows, dropped, total, has_more)``.

    ``first_floor`` keeps 楼层 whole across the pages one episode's walk fetches (the
    payload itself orders newest-first inside a page but prints no floor); a reply
    page passes its parent's floor and every row links to it. ``total``/``has_more``
    are the SITE's own words and travel to the walker for the end-of-list license.
    ``drama_title``/``episode_index`` are the walker's own facts (the web title it
    resolved, the episode position it was standing on) — a payload never names its own
    drama, so a row without them would be attributable only by an unreadable id.
    """
    data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    info = data.get('common_list_info') if isinstance(data.get('common_list_info'), dict) else {}
    entries = data.get('data_list')
    entries = entries if isinstance(entries, list) else []
    rows = []
    dropped = 0
    floor = first_floor
    for entry in entries:
        row = _one_comment(
            entry,
            article_url,
            floor,
            parent_floor=parent_floor,
            drama_title=drama_title,
            episode_index=episode_index,
        )
        if row is None:
            dropped += 1
            continue
        rows.append(row)
        floor += 1
    return rows, dropped, _as_int(info.get('total')), bool(info.get('has_more'))
