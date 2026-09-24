"""Live X crawl — real Chrome, real x.com, and the visible window.

This tier is where the four design claims of ``crawlers/twitter.py`` meet the
site they were read off:

* **A headless window is refused, not empty.** The whole reason for
  ``never_headless`` is that X answers an automation-shaped browser with a
  sign-up sheet (search) or a 403 (profile). The test does not assert the exact
  refusal — a site is free to change which rude page it serves — it asserts the
  property that matters: a headless crawl never comes back with a quiet zero that
  would read as "this keyword found nothing".
* **The timeline is virtualized**, so a walk that watched the card count would
  stop after one screen. Asking for more rows than a screen holds (measured: 13-21
  ``<article>`` nodes) is the cheapest proof that the id-window watcher works.
* **One sentence carries the numbers.** Every count in a row must be an integer
  parsed off ``[role="group"]``'s aria-label — a row that stored the label's text
  or guessed 0 for a number the site showed is a wrong table, not an empty one.
* **Replies are the same walk**, on the post's own permalink, minus the post.

Volumes stay tiny (3-30 rows) and no assertion depends on a tweet that could be
deleted: the post whose replies are read is *found by this run*, the same way the
other live files pick their target.

"""

import re

import pytest

from crawlers.comments import OK, CommentSession

#: ``live_os``: x.com is unreachable from a Chinese network, so this file runs with a
#: VPN up while the domestic files run with it off (``live_cn``).
pytestmark = [pytest.mark.live_site, pytest.mark.live_os, pytest.mark.enable_socket]

KEYWORD = 'OpenAI'
#: An account that posts daily, so a profile walk never lands on an empty page.
ACCOUNT = 'NASA'
_PERMALINK = re.compile(r'^https://x\.com/[A-Za-z0-9_]{1,20}/status/\d+$')
_STAMP = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
_COUNTS = ('评论数', '转发数', '点赞数', '收藏数', '浏览数')


def _says_something(row) -> bool:
    """The row carries at least one thing a downstream node can work with.

    正文 cannot be the test on its own: measured on the live site, a **photo post
    with no caption** has no ``div[data-testid="tweetText"]`` node at all — the
    card's own text is empty while it holds one ``pbs.twimg.com`` image. Dropping
    such a post would lose the row the user searched for, and requiring text would
    fail a crawl that read the page perfectly.
    """
    return bool(
        (row['正文'] or '').strip()
        or int(row['图片数'])
        or int(row['视频数'])
        or row['是否引用'] == '1'
        or row['含外链卡片'] == '1'
        or row['含投票'] == '1'
    )


def _assert_real_posts(rows, minimum):
    """The row-level contract every X crawl owes, whatever mode produced it."""
    assert len(rows) >= minimum, f'expected at least {minimum} rows, got {len(rows)}'
    for row in rows:
        assert _PERMALINK.match(row['链接']), f'not a post permalink: {row["链接"]}'
        assert row['推文ID'].isdigit(), f'推文ID is not a status id: {row["推文ID"]!r}'
        assert row['推文ID'] in row['链接'], 'the row id and its link address different posts'
        assert _says_something(row), f'a row that carries nothing but a link: {row}'
        assert row['发布者ID'].startswith('@'), f'the poster has no handle: {row}'
        assert _STAMP.match(row['发布时间']), f'发布时间 is not the UTC stamp the page carries: {row["发布时间"]!r}'
        for column in _COUNTS:
            assert isinstance(row[column], int), f'{column} must be a number, got {row[column]!r}'
    ids = [row['推文ID'] for row in rows]
    assert len(set(ids)) == len(ids), 'a recycled window handed the same tweet back twice'


def test_a_headless_window_never_reports_a_quiet_zero(cookie_dir_str):
    """The measurement behind ``never_headless``: refused, or — if the site ever
    relents — real rows. Never an empty list, which is the outcome a user cannot
    tell apart from a dead keyword.

    Built directly instead of through ``live_crawler``: that fixture skips when no
    session is saved, and skipping is exactly what a test about refusal must not do.
    """
    from crawlers import get_crawler

    crawler = get_crawler('twitter', headless=True, cookie_dir=cookie_dir_str)
    try:
        try:
            rows = crawler.search(KEYWORD, target_count=3)
        except RuntimeError as e:
            assert str(e), 'a refusal must say where it happened'
            return
    finally:
        crawler.close()
    _assert_real_posts(rows, minimum=1)


@pytest.mark.live_quick
def test_search_rows_carry_the_shape_a_post_has(live_crawler):
    """The row-level contract of a live keyword walk — with no numeric promise.

    A screen of ``f=live`` is minutes-old replies, and measured twice it came back
    with every engagement figure at zero on rows the site really did show; views are
    only rendered for some accounts. So nothing here asks for a number: a *number that
    was never shown* is a legitimate zero, and asserting one would make the tier fail
    on the world's mood rather than on the crawler. The counter-parsing contract lives
    in :func:`test_author_mode_reads_that_accounts_own_timeline`, where the account is
    chosen because it does have them.
    """
    crawler = live_crawler('twitter', headless=False)
    try:
        rows = crawler.search(KEYWORD, target_count=4)
    finally:
        crawler.close()
    _assert_real_posts(rows, minimum=3)


def test_the_walk_reads_past_the_rendered_window(live_crawler):
    """One screen holds 13-21 cards on the real site; 22 distinct tweets is the
    cheapest proof the walk is watching ids and not node counts."""
    crawler = live_crawler('twitter', headless=False)
    try:
        rows = crawler.search(KEYWORD, target_count=30)
    finally:
        crawler.close()
    _assert_real_posts(rows, minimum=22)


def test_author_mode_reads_that_accounts_own_timeline(live_crawler):
    """An active account is where the counters are asserted, for the simple reason
    that its posts have them: every number in a row is parsed off the card's
    ``[role="group"]`` sentence, and "0 Likes. Like" on a two-minute-old reply proves
    nothing about that parser — a few hundred likes on a NASA post does.
    """
    crawler = live_crawler('twitter', headless=False)
    try:
        rows = crawler.author(ACCOUNT, target_count=4)
    finally:
        crawler.close()
    _assert_real_posts(rows, minimum=3)
    assert any(row['评论数'] > 0 or row['点赞数'] > 0 for row in rows), (
        f'no row of {ACCOUNT} carried a single count — the [role="group"] sentence was not parsed'
    )
    handle = f'@{ACCOUNT.lower()}'
    # Reposts render the original author's name inside the same article, so the
    # profile walk is judged by how much of it *is* the account, not by every row.
    mine = sum(1 for row in rows if row['发布者ID'].lower() == handle)
    assert mine >= 2, f'only {mine} of {len(rows)} rows were {handle} own posts'


def test_replies_are_walked_on_the_posts_own_page(live_crawler):
    """Find a live post that reports replies, then read them off its permalink.

    The root post is the one thing that must *not* come back: it is the page
    itself, and storing it would give the user a reply to its own tweet.

    The post is taken from an active account rather than from ``f=live``: measured,
    a live keyword stream is minutes-old replies whose own sentences say "0
    Replies", so it cannot honestly be the source of a post that has any.
    """
    crawler = live_crawler('twitter', headless=False)
    try:
        posts = crawler.author(ACCOUNT, target_count=8)
        link = ''
        root = ''
        for row in posts:
            if int(row['评论数']) >= 3:
                link, root = row['链接'], row['推文ID']
                break
        assert link, f'none of {len(posts)} posts from {ACCOUNT} reported replies — nothing to read honestly'
        session = CommentSession(crawler.driver, log=print)
        rows, status = session.crawl_twitter(link, limit=8)
    finally:
        crawler.close()
    assert status == OK, f'the reply walk reported {status} on a post that shows replies'
    assert len(rows) >= 2, f'expected at least 2 replies, got {len(rows)}'
    assert len(rows) <= 8, 'the limit is a promise, not a suggestion'
    for row in rows:
        assert row['平台'] == 'twitter' and row['文章URL'] == link
        assert (row['评论内容'] or '').strip(), f'a reply with no text: {row}'
        assert row['评论ID'] != root, 'the root post came back as a reply to itself'
    assert len({row['评论ID'] for row in rows}) == len(rows), 'the same reply twice'
