"""YouTube comments: one innertube answer's ``commentEntityPayload`` objects → rows, and the walk.

The field names come from the live answer, not from a guess (see the docstring
below). This module owns both halves of the YouTube comment read: the pure
mapping and the in-page innertube walk that feeds it.
"""

import math

from crawlers.commenting.protocol import BLOCKED, DEAD, OK, _query_value
from crawlers.commenting.walks import register
from crawlers.engine import times
from crawlers.engine.counters import parse_count, to_int
from crawlers.engine.jsonpath import collect, get_in, runs_text
from crawlers.engine.wall import looks_blocked
from i18n import t


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
                '评论时间': times.absolute(props.get('publishedTime')),
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


#: One video's comments, walked as JSON.
@register('youtube')
def walk(session, url: str, limit: int) -> tuple:
    """One video's comments, read as JSON instead of by scrolling the panel.

    The panel is real — it grows by token, 20 comments a round — but reading it
    would pay a rendered screen per round when the page itself is fetching the
    same objects as JSON in ~0.3 s. So the walk is the browser's own:
    ``next(videoId)`` for the pager, then ``next(continuation=…)`` per round.

    The first round is a *search* for the working token rather than a fixed
    pick, and that is measured, not caution: a watch answer carries six
    continuation tokens (the comment pager, the related-video rail twice, the
    sort menu twice and one more), and the comment pager's length is not even
    stable across videos — 78 characters on one, 146 on another, while the
    rail's are 1412. So each candidate is asked, in document order, until one
    answers with comments.

    After that first page the rule is stricter, because a wrong token here is
    worse than a failed one: a round carries the real pager at the end of the
    comment list *and* two sort-menu tokens that both answer **page one again**.
    Following a sort token re-reads the same twenty comments, the ledger refuses
    them all as duplicates, the walk reports success — and a video with three
    thousand comments yields twenty. So the cursor is taken from the list the
    rows actually came from (``innertube.pager_of``).
    """
    from crawlers.engine import innertube, pager
    from crawlers.platforms.youtube.crawler import video_id_of

    video = video_id_of(url)
    if not video:
        return [], DEAD
    session.driver.get(f'https://www.youtube.com/watch?v={video}')
    found = innertube.ready(session.driver)
    if not found:
        # No API config means the page never booted as a watch page. Which
        # reason it was changes what the user does next, so the page itself
        # gets the last word.
        if looks_blocked(session.body_head()):
            return [], BLOCKED
        session.log(t('comment.ytNoPage', url=url))
        return [], DEAD
    key, context = found
    watch = innertube.call(session.driver, 'next', key, context, {'videoId': video})
    if innertube.refused(watch):
        return [], BLOCKED

    rows: list[dict] = []
    seen: set[str] = set()
    #: The pager of the list the last answer's rows came from. One entry by
    #: construction — a round carries several tokens and only that one pages
    #: this list, which is why it is selected by position rather than tried.
    candidates: list[str] = []

    def fetch(token):
        # dict.fromkeys keeps first-seen order while dropping the duplicate the
        # first round used to make: with no alternates yet, ``token`` and the
        # seeded ``candidates`` were the same continuation, so the identical
        # token was POSTed twice before giving up.
        order = list(dict.fromkeys(candidate for candidate in [token, *candidates] if candidate))[:3]
        for candidate in order:
            payload = innertube.call(session.driver, 'next', key, context, {'continuation': candidate})
            if innertube.refused(payload):
                return None
            if collect(payload, 'commentEntityPayload'):
                return payload
        return {}

    def extract(payload):
        nonlocal candidates
        page = parse_youtube_comments(payload, url)
        # The list holds ``commentThreadRenderer`` entries while the comment
        # text itself arrives beside it under frameworkUpdates, so the marker
        # that identifies *this* list is the thread renderer — asking for
        # commentEntityPayload would find no list at all and stop the walk.
        read = innertube.pager_of(payload, 'commentThreadRenderer')
        candidates = [read] if read else []
        return page, (candidates[0] if candidates else None)

    chosen = ''
    for token in innertube.pager_tokens(watch):
        candidates = [token]
        attempt = fetch(token)
        if attempt is None:
            return [], BLOCKED
        if attempt:
            chosen = token
            break
    if not chosen:
        # Nothing paged the comments: the author turned them off, or the video
        # has none. Either way that is an answer, and it has to read as
        # 无评论 rather than as a failed crawl.
        session.log(t('comment.commentsClosed', url=url))
        return [], OK

    def keep(row):
        rows.append(row)
        return True

    # The chosen token is fetched a second time here, which costs one 0.3 s
    # round: the alternative is to hand the pager a half-consumed page, and a
    # walk that starts from something other than its own cursor is how rows go
    # missing silently.
    outcome = pager.walk_pages(
        fetch,
        extract,
        keep,
        start_cursor=chosen,
        collected=lambda: len(rows),
        target=limit or math.inf,
        seen=seen,
        identity=lambda row: row['评论ID'],
        polite=lambda: session.nap(0.35),
        # The pager's own stop check: a comment walk can be asked for hundreds of
        # pages, and the node handler only looks between URLs.
        alive=lambda: not session.may_stop(),
    )
    if not rows and outcome.stopped_reason == 'fetch_failed':
        return [], BLOCKED
    return rows, OK
