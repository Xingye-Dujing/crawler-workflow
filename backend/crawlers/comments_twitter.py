"""X (twitter) replies: reuse the timeline's card extractor for a reply thread."""


def parse_twitter_replies(cards: list, article_url: str, root_id: str = '') -> list:
    """X reply cards → comment rows.

    The same extractor as the timeline is reused (one ``execute_script`` per card),
    and the tweet the page is *about* is dropped: it appears first on its own
    permalink, and storing it would hand the user a row saying "this post replied
    to itself" while inflating its own counts.
    """
    from .twitter import row_from_card

    rows = []
    for index, card in enumerate(cards):
        row = row_from_card(card if isinstance(card, dict) else {})
        if row is None or (root_id and row['推文ID'] == str(root_id)):
            continue
        rows.append(
            {
                '平台': 'twitter',
                '文章URL': article_url,
                '评论者': row['发布者ID'] or row['发布者'],
                '评论者昵称': row['发布者'],
                '评论者主页': row['用户链接'],
                '评论内容': row['正文'],
                '评论时间': row['发布时间'],
                '点赞数': row['点赞数'],
                '回复数': row['评论数'],
                '转发数': row['转发数'],
                '浏览数': row['浏览数'],
                '图片链接': row['图片链接'],
                '图片数': row['图片数'],
                '是否引用': row['是否引用'],
                '楼层': index + 1,
                '评论ID': row['推文ID'],
                '推文ID': row['推文ID'],
            }
        )
    return rows
