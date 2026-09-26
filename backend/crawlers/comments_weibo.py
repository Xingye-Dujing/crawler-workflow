"""weibo comments: the ``buildComments`` JSON adapter and the id/endpoint helpers."""

import re

from .comments_base import _strip_tags


def parse_weibo_comments(payload: dict, article_url: str) -> list:
    """buildComments JSON → rows. Missing fields degrade to empty, never raise."""
    rows = []
    for i, item in enumerate(payload.get('data') or [], 1):
        if not isinstance(item, dict):
            continue
        user = item.get('user') if isinstance(item.get('user'), dict) else {}
        rows.append(
            {
                '平台': 'weibo',
                '文章URL': article_url,
                '评论者': str(user.get('screen_name') or ''),
                '评论者主页': str(user.get('profile_image_url') or ''),
                '评论内容': _strip_tags(str(item.get('text') or '')),
                '评论时间': str(item.get('created_at') or ''),
                '点赞数': int(item.get('like_count') or 0),
                '楼层': i,
            }
        )
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
