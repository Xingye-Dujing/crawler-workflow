"""bilibili comments: ``x/v2/reply/main`` rows → tables, plus the endpoint helpers.

The desktop DOM is a maze of hashed class names and the comment panel renders
nothing, so the endpoint fetched in page is the only path — this module owns how
its JSON becomes rows and how that endpoint is addressed.
"""

from .comments_base import _stamp


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
