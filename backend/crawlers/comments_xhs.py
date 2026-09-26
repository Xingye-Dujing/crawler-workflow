"""xiaohongshu comments: the DOM-walker tuple adapter."""


def parse_xhs_comments(items) -> list:
    """Takes [(author, text, date, likes)] tuples scraped by the DOM walker."""
    return [
        {
            '平台': 'xiaohongshu',
            '文章URL': url,
            '评论者': author,
            '评论者主页': '',
            '评论内容': text,
            '评论时间': date,
            '点赞数': likes,
            '楼层': idx,
        }
        for idx, (url, author, text, date, likes) in enumerate(items, 1)
    ]
