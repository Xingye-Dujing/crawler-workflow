"""YouTube comments: one innertube answer's ``commentEntityPayload`` objects → rows.

The field names come from the live answer, not from a guess (see the docstring
below). This module owns the pure mapping; the in-page innertube walk that feeds
it lives in :class:`crawlers.comments.CommentSession`.
"""

from .comments_base import _query_value
from .engine.counters import parse_count, to_int
from .engine.jsonpath import collect, get_in, runs_text


def parse_youtube_comments(payload: dict, article_url: str) -> list:
    """One innertube answer's ``commentEntityPayload`` objects → rows.

    The field names come from the live answer, not from a guess (measured: the
    text is ``properties.content.content``, the like count is
    ``toolbar.likeCountNotliked`` with an accessibility sentence behind it, the
    author is ``author.displayName`` and the stable id is ``properties.commentId``).
    Two of those matter more than they look:

    * 评论时间 is relative prose on YouTube ("1 year ago") with no absolute
      sibling in the payload, so it cannot identify a row on its own — the
      ``评论ID`` is what makes a resumed walk refuse duplicates instead of
      storing the same comment twice;
    * a reply to a reply carries ``properties.replyLevel`` > 0, and the floor is
      kept so an analysis of "what did people say" can tell a thread from a
      top-level comment.
    """
    rows = []
    for item in collect(payload, 'commentEntityPayload'):
        if not isinstance(item, dict):
            continue
        props = item.get('properties') or {}
        toolbar = item.get('toolbar') or {}
        author = item.get('author') or {}
        comment_id = str(props.get('commentId') or '')
        handle = str(author.get('displayName') or '')
        canonical = str(get_in(author, 'channelCommand.innertubeCommand.browseEndpoint.canonicalBaseUrl') or '')
        rows.append(
            {
                '平台': 'youtube',
                '文章URL': article_url,
                '评论者': handle,
                '评论者主页': f'https://www.youtube.com{canonical}' if canonical else '',
                '评论者ID': str(author.get('channelId') or ''),
                '评论内容': runs_text(props.get('content')),
                '评论时间': str(props.get('publishedTime') or ''),
                # The count the viewer has not used reads the same as the one
                # they have, so either spelling is the number — and the a11y
                # sentence ("… along with 56 other people") is the fallback.
                '点赞数': to_int(toolbar.get('likeCountNotliked') or toolbar.get('likeCountLiked'))
                or parse_count(toolbar.get('likeButtonA11y')),
                '回复数': to_int(toolbar.get('replyCount')),
                '楼层': to_int(props.get('replyLevel')) + 1,
                '评论ID': comment_id,
                '是否作者回复': '1' if author.get('isCreator') else '0',
                '视频ID': _query_value(article_url, 'v'),
            }
        )
    return rows
