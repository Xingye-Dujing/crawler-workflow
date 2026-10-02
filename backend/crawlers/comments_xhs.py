"""xiaohongshu comments: the DOM-walker tuple adapter."""

from .engine import times


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
