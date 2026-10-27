"""X (twitter) replies: reuse the timeline's card extractor for a reply thread, and the walk."""

import math

from selenium.common.exceptions import JavascriptException, StaleElementReferenceException

from crawlers.commenting.protocol import BLOCKED, DEAD, OK
from crawlers.commenting.walks import register
from crawlers.engine import feed
from crawlers.engine.wall import looks_blocked
from i18n import t


def parse_twitter_replies(cards: list, article_url: str, root_id: str = '') -> list:
    """X reply cards → comment rows.

    The same extractor as the timeline is reused (one ``execute_script`` per card),
    and the tweet the page is *about* is dropped: it appears first on its own
    permalink, and storing it would hand the user a row saying "this post replied
    to itself" while inflating its own counts.
    """
    from crawlers.platforms.twitter.crawler import row_from_card

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


@register('twitter')
def walk(session, url: str, limit: int) -> tuple:
    """One post's replies, read off its own permalink page.

    X has no readable comment endpoint for a browser session (its GraphQL needs
    a transaction label the page mints per request), so this is a DOM walk —
    and the DOM is virtualized, so the same rules as the timeline apply:
    progress is measured by rows kept, and identity by the reply's status id
    (measured: 13-21 ``<article>`` nodes on screen while 139 distinct replies
    passed through in eight scrolls).
    """
    from crawlers.platforms.twitter.crawler import EXTRACT_CARD_JS, WINDOW_LINKS_JS, TwitterCrawler, tweet_id_of

    root = tweet_id_of(url)
    if not root:
        return [], DEAD

    def cards_of():
        return session.driver.find_elements('css selector', TwitterCrawler.CARD_SELECTOR)

    session.driver.get(url if 'x.com/' in url or 'twitter.com/' in url else f'https://x.com/i/status/{root}')
    # Waited for, not slept: the permalink is an app route that fetches its own
    # thread and measured ~12 s to its first rendered card on a connection that
    # was fine. A fixed nap ended the walk on a page that had not painted, and
    # an empty page is what the walk reports as a dead link.
    feed.wait_for(lambda: len(cards_of()), 1, timeout=TwitterCrawler.MOUNT_WAIT)
    if looks_blocked(session.body_head()):
        return [], BLOCKED

    rows: list[dict] = []
    seen: set[str] = set()

    def scrape(card, _index):
        # ``_index`` is the walk's screen slot, fixed by ``feed.walk_feed``'s
        # ``scrape(card, index)`` contract; a reply's identity is its own 评论ID, so the
        # position the card sat at in this round says nothing about it.
        try:
            data = session.driver.execute_script(EXTRACT_CARD_JS, card)
        except (StaleElementReferenceException, JavascriptException):
            # The reply list recycles its nodes while the walk is reading them;
            # the post is still unseen, so a later round reads it off a new handle.
            return None
        parsed = parse_twitter_replies([data], url, root)
        if not parsed:
            return None
        row = parsed[0]
        return None if row['评论ID'] in seen else row

    def keep(row):
        seen.add(row['评论ID'])
        rows.append(row)
        return True

    walk_result = feed.walk_feed(
        cards_of,
        scrape,
        keep,
        scroll=lambda: _scroll_replies(session),
        target=limit or math.inf,
        collected=lambda: len(rows),
        # Same rule as the timeline: the reply list recycles its nodes, so the
        # walk waits for the ids on screen to change, not for more nodes.
        window=lambda: str(session.driver.execute_script(WINDOW_LINKS_JS) or ''),
        stuck_rounds=3,
        settle_wait=4.0,
        stopped=session.may_stop,
    )
    if not rows and walk_result.stopped_reason == 'no_cards':
        session.log(t('comment.xNoList', url=url))
        return [], DEAD
    if not rows:
        # The page mounted and there is still nothing under the post: replies
        # are closed, or nobody answered. That is a fact about the tweet and it
        # reads as the same line the other platforms say — not as a failed crawl.
        session.log(t('comment.commentsClosed', url=url))
    return rows, OK


def _scroll_replies(session):
    """Scroll the reply page the way a person does, then let it settle."""
    session.driver.execute_script('window.scrollBy(0, window.innerHeight * 1.4);')
    session.nap(1.2)
