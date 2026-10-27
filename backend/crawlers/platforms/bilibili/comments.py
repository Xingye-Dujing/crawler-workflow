"""bilibili comments: ``x/v2/reply/main`` rows, the endpoint helpers and the walk.

The desktop DOM is a maze of hashed class names and the comment panel renders
nothing, so the endpoint fetched in page is the only path — this module owns how
its JSON becomes rows, how that endpoint is addressed and what its answer codes
blame (the link or the session).
"""

from crawlers.commenting.protocol import BLOCKED, DEAD, OK, _json_or_none, _stamp, as_count
from crawlers.commenting.walks import register
from crawlers.engine.wall import looks_blocked
from i18n import t


def parse_bilibili_comments(items, article_url: str, floor: int = 0) -> list:
    """``x/v2/reply/main`` rows → comment rows, sub-replies flattened in place.

    ``floor`` continues the numbering across pages, so 楼层 stays a position in
    the article's comment set rather than in one page's payload.

    A carried ``replies`` list is NOT the whole thread: measured on a hot page,
    a comment with ``rcount=11`` carries 2 sub-replies. They are stored with
    their parent's id so a reader can tell a reply-from-a-reply from a top-level
    comment, and ``子回复数`` keeps the unexpanded remainder visible instead of
    letting the count read as "this thread has 2 replies".
    """
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        floor += 1
        rows.append(_bili_comment_row(item, article_url, floor, parent=''))
        for sub in item.get('replies') or []:
            if isinstance(sub, dict):
                floor += 1
                rows.append(_bili_comment_row(sub, article_url, floor, parent=str(item.get('rpid') or '')))
    return rows


def _bili_comment_row(item: dict, article_url: str, floor: int, parent: str) -> dict:
    member = item.get('member') if isinstance(item.get('member'), dict) else {}
    content = item.get('content') if isinstance(item.get('content'), dict) else {}
    mid = str(member.get('mid') or '')
    level = (
        (member.get('level_info') or {}).get('current_level') if isinstance(member.get('level_info'), dict) else None
    )
    return {
        '平台': 'bilibili',
        '文章URL': article_url,
        '评论者': str(member.get('uname') or ''),
        '评论者主页': f'https://space.bilibili.com/{mid}' if mid else '',
        '用户等级': int(level or 0),
        '评论内容': str(content.get('message') or ''),
        '评论时间': _stamp(item.get('ctime')),
        '点赞数': int(item.get('like') or 0),
        '楼层': floor,
        '评论ID': str(item.get('rpid') or ''),
        '父评论ID': parent or str(item.get('root') or ''),
        '子回复数': int(item.get('rcount') or 0),
        '回复数': int(item.get('count') or 0),
        'UP主态': '点赞' if _bili_up_liked(item) else '',
    }


def _bili_up_liked(item: dict) -> bool:
    """Whether the video's UP主 liked this comment (the card_label badge).

    It is the one signal in the payload that says "the author read this", and
    an analyst sorting a comment table by it is sorting by author engagement —
    which is why it is kept and why a missing label must read as plain ''.
    """
    for label in item.get('card_label') or []:
        if isinstance(label, dict) and 'UP主' in str(label.get('text_content') or ''):
            return True
    return bool((item.get('up_action') or {}).get('like')) if isinstance(item.get('up_action'), dict) else False


def bilibili_view_js(bvid: str) -> str:
    return f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}'


def bilibili_reply_js(aid, next_cursor: int = 0, size: int = 20) -> str:
    """One page of the hot-sorted comment list.

    ``mode=3`` is what the video page itself requests and the only mode measured
    to page coherently: ``mode=2`` (by time) jumped its own cursor to 1435 and
    then reported ``is_end`` after a single row.
    """
    return f'https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=3&next={next_cursor}&ps={size}'


_VIDEO_CODES = frozenset({-404, -400, 62002})
#: B站 ``view``/``reply`` codes that are a fact about THIS session or IP (风控 / 请求拦截 / 未登录):
#: the only codes whose answer is "stop, and let 继续 retry" (BLOCKED → the node may latch cookieExpired).
_RISK_CODES = frozenset({-352, -412, -101})


def bili_code_verdict(code) -> str:
    """Who an error code blames: the link (``video``/``transport`` → DEAD) or the session (risk/unknown → BLOCKED).

    §6 U55 was exactly the wrong default — every non-``-404`` code sent to BLOCKED, so a bad BV (which
    answers ``-400``) convicted the whole session. The polarity is now: the *link* is accused only for a
    code that describes the video (gone/bad/hidden) or a transport failure (no JSON — a slow link, not a
    refusal, per crawler_rules「慢不是拒绝」); the *session* is accused for a known risk/login code AND,
    named, for any unrecognised code — so a new rate-limit code backs off instead of being silently
    guessed into "this video is fine" and pressing on against a flagged account.
    """
    if code == 0:
        return 'ok'
    if code is None:
        return 'transport'
    if code in _VIDEO_CODES:
        return 'video'
    if code in _RISK_CODES:
        return 'risk'
    return 'unknown'


@register('bilibili')
def walk(session, url: str, limit: int) -> tuple:
    """One video's comments, walked through ``x/v2/reply/main``.

    Paging follows the server's cursor rather than a counter, because the
    counter is a trap that this project measured the hard way: ``next=0``
    answers and reports ``cursor.next=2``, and a request for ``next=1``
    replays page 0 identically. Incrementing would therefore store the first
    19 comments over and over and still claim to have reached the limit, so
    the walk stops on a page that carries no new ``rpid`` — which is also
    what makes a repeating server-side cursor harmless.
    """
    from crawlers.platforms.bilibili.crawler import bilibili_bvid

    session.driver.get(url)
    session.nap(3)
    if looks_blocked(session.body_head()):
        return [], BLOCKED
    bvid = bilibili_bvid(url)
    if not bvid:
        return [], DEAD
    view = _json_or_none(session.fetch_in_page(bilibili_view_js(bvid)))
    verdict = bili_code_verdict((view or {}).get('code'))
    if verdict == 'video' or verdict == 'transport':
        # This link is gone/bad/hidden, or its endpoint never answered as JSON: a fact about
        # THIS link, so it is DEAD for the link and must not accuse the session (the douyin U47
        # rule). A real wall was already caught above by ``looks_blocked``.
        return [], DEAD
    if verdict == 'risk':
        return [], BLOCKED
    if verdict == 'unknown':
        # A code we have not measured: do not guess it is a video answer and keep hammering,
        # and do not silently convict either — refuse it BY NAME and back off (BLOCKED).
        session.log(t('comment.biliBadAnswer', url=url, code=(view or {}).get('code')))
        return [], BLOCKED
    data = view.get('data') or {}
    aid = data.get('aid')
    if not aid:
        return [], DEAD
    #: The site's own comment count — the denominator the user reads off the page. Kept so a clean-end
    #: walk far under it can be named (U54), not just counted silently into a finished crawl.
    declared = as_count((data.get('stat') or {}).get('reply'))
    if not declared:
        # The author closed the comment section: that is an answer, not a
        # failure, and it has to read as 无评论 rather than as a dead link.
        session.log(t('comment.commentsClosed', url=url))
        return [], OK
    rows, cursor, seen, guard = [], 0, set(), 0
    # Did the walk stop because the SESSION was refused (must back off + 继续), or because a slow
    # link never answered (keep what was read, do not latch the session)? Neither is "the thread ended".
    session_stop = False
    first_page_unreadable = False
    while guard < 200:
        guard += 1
        payload = _json_or_none(session.fetch_in_page(bilibili_reply_js(aid, cursor)))
        page_verdict = bili_code_verdict((payload or {}).get('code'))
        if page_verdict != 'ok':
            # Name the refused page with the site's own code; a later page failing still keeps
            # what we collected, so the walk stops here rather than advancing a dead cursor.
            session.log(t('comment.biliBadAnswer', url=url, code=(payload or {}).get('code')))
            if page_verdict in ('risk', 'unknown'):
                session_stop = True
            elif not rows:
                # The FIRST page never answered as JSON and the denominator said there ARE comments:
                # this thread was unreadable, not empty. A slow link must not latch the session, so
                # it is DEAD for the link rather than the old silent OK-that-reads-as-no-comments.
                first_page_unreadable = True
            break
        page = payload.get('data') or {}
        items = [r for r in (page.get('replies') or []) if str(r.get('rpid')) not in seen]
        if not items:
            break
        for item in page.get('replies') or []:
            seen.add(str(item.get('rpid')))
        rows.extend(parse_bilibili_comments(items, url, floor=len(rows)))
        info = page.get('cursor') or {}
        if info.get('is_end') or (limit and len(rows) >= limit):
            break
        cursor = int(info.get('next') or (cursor + 1))
        session.nap(0.8)  # polite page interval on the comment API
    if session_stop:
        # A risk/unknown page: the thread did NOT end. Keep what was read and report BLOCKED, so the
        # node latches cookieExpired, the run STOPS (no further links pressed against a flagged
        # account), and 继续 resumes from the recorded cursor. This is U54's "按 §5 具名短收": a
        # throttled 9-row thread is NAMED-BLOCKED (back-off), never a silent OK and never a full.
        return rows, BLOCKED
    if first_page_unreadable:
        return [], DEAD
    # U54 (measured live 2026-09-29, H1 comment leg): a 2194-comment thread delivered only 7 rows and
    # ENDED on is_end/empty page → the old code returned OK silently, so table+summary+completion all
    # agreed on a short count that no line explained. A clean end far under the site's OWN denominator
    # is not "the thread is short" — it is what an anonymous deep-page bucket does when throttled. Name
    # the gap against ``declared`` (mirror comment.weiboShort / comment.zhihuPanelShort); a thread that
    # really holds that many (rows==declared) or that met the user's ask says nothing (two-sided).
    met_ask = bool(limit) and len(rows) >= limit
    if not met_ask and len(rows) < declared:
        session.log(t('comment.biliShort', url=url, rows=len(rows), declared=declared))
    return (rows[:limit] if limit else rows), OK
