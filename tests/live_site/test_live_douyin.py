"""Live Douyin crawl — real Chrome in a VISIBLE window, the user's own session.

Douyin is the platform where the browser mode is part of the contract: headless
is answered with 验证码中间页 on every navigation, so this tier drives the visible
window (the same mode the Cookie panel logs in with) and separately asserts what
a headless attempt produces — a refusal, never a table of zeros.

Videos are discovered live rather than bookmarked, because an aweme id can be
withdrawn and a search page cannot, and every assertion is on the counters that
name themselves in the DOM. Note the deliberate absence: a douyin row has no
播放数 column, because the web player never shows plays.
"""

import pytest

from crawlers.comments import DEAD, OK, CommentSession
from crawlers.video import DouyinCrawler, douyin_id

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

KEYWORD = '人工智能'


def _assert_real_rows(rows, minimum=1):
    assert len(rows) >= minimum, f'expected at least {minimum} rows, got {len(rows)}'
    for row in rows:
        assert douyin_id(row['链接']), f'row link carries no video id: {row}'
        assert (row['标题'] or '').strip(), f'row without a title: {row}'
        assert '播放数' not in row, 'douyin must not publish a play count it cannot see'
        assert row['点赞数'] >= 0 and row['评论数'] >= 0
    assert any(row['点赞数'] > 0 for row in rows), 'no row carried a like count — the detail read failed'
    assert any((row['正文'] or '').strip() for row in rows), 'no row carried the video text (文案)'


@pytest.mark.live_quick
def test_visible_search_resolves_each_video(live_crawler):
    crawler = live_crawler('douyin', headless=False)
    try:
        rows = crawler.search(KEYWORD, target_count=2)
    finally:
        crawler.close()
    _assert_real_rows(rows, minimum=2)
    # The counters that name themselves are the only trusted source.
    assert any(row['收藏数'] > 0 for row in rows), 'no row carried 收藏数 — video-player-collect not read'
    assert any((row['作者'] or '').strip() for row in rows), 'no row carried an author'
    assert any((row['发布时间'] or '').startswith('20') for row in rows), 'no row carried a publish time'


def test_a_headless_attempt_never_files_a_silent_empty_success(live_crawler):
    """Measured environment fact: headless douyin gets the captcha page.

    The contract is not "a refusal happens" — it is "a headless run never returns
    an empty table as if it had succeeded". So both live outcomes are asserted
    here and neither is skipped: refused, it must name the wall or the missing
    search box; allowed through, it must actually deliver rows. Zero rows without
    a refusal is the one shape that would mislead a user, and it fails.
    """
    crawler = live_crawler('douyin', headless=True)
    try:
        try:
            rows = crawler.search(KEYWORD, target_count=2)
        except (RuntimeError, ValueError) as refused:
            message = str(refused)
            assert '验证' in message or '搜索框' in message, f'unexpected refusal text: {message}'
            return
        assert rows, (
            'a headless session returned 0 rows without refusing: that reads as '
            '"this keyword has no videos", which is the false answer this test exists to catch'
        )
        _assert_real_rows(rows, minimum=1)
    finally:
        crawler.close()


def test_comments_scroll_past_the_first_screen(live_crawler):
    """Paging proof, sized by the video the search actually returned.

    The threshold comes from the platform's own reported number rather than from a
    constant, and the sample is widened to eight videos so "no video here has
    enough comments to demonstrate a scroll walk" is a finding about the crawl,
    not a reason to skip: a hot douyin keyword that returns only dead videos, or
    a 评论数 column that stopped being read, is exactly what this test should fail
    on. Nothing here is skipped, and nothing here is satisfied by an empty table.
    """
    crawler = live_crawler('douyin', headless=False)
    try:
        rows = crawler.search(KEYWORD, target_count=8)
        assert rows, 'no video to comment on was found live'
        best = max(rows, key=lambda row: int(row['评论数'] or 0))
        link, reported = best['链接'], int(best['评论数'] or 0)
        assert reported >= 30, (
            f'none of the {len(rows)} live videos reported enough comments to page (max {reported}): '
            'either the keyword stopped returning live videos or 评论数 is no longer being read'
        )
        session = CommentSession(crawler.driver, log=print, nap=lambda s: None)
        comments, status = session.crawl_douyin(link, limit=40)
    finally:
        crawler.close()
    assert status == OK, f'douyin comment crawl ended as {status} on {link}'
    assert comments, 'a video reporting 评论数>0 must yield comment rows'
    for row in comments:
        assert row['平台'] == 'douyin' and row['文章URL'].endswith(douyin_id(link))
        assert (row['评论内容'] or '').strip(), f'comment row without text: {row}'
    # The crawler's own identity is (评论者, 评论内容, 评论时间), so a scroll that
    # replayed the list cannot survive into these rows — and keying the check on
    # (author, text) alone was wrong anyway: one person posting the same short
    # comment twice is a real thing that happens on a live video. What actually
    # proves the container scroll advanced is the count floor below, against a
    # first render measured at 5-16 rows.
    keys = {(row['评论者'], row['评论内容'], row['评论时间']) for row in comments}
    assert len(keys) == len(comments), 'two rows carry the same comment identity'
    assert any(row['评论时间'] for row in comments), 'an empty time would make the identity collapse'
    # The first render is a partial screen (measured 5-16 rows); reaching the
    # limit is what proves the container scroll keeps feeding the list.
    assert len(comments) >= 30, f'only {len(comments)} of ~{reported} comments were collected'
    assert any(row['点赞数'] > 0 for row in comments), 'no comment carried a like count'
    assert any(row['评论地区'] for row in comments), 'no comment carried its IP region'


def test_detail_read_of_one_live_video(live_crawler):
    crawler = live_crawler('douyin', headless=False)
    try:
        rows = crawler.search(KEYWORD, target_count=1)
        assert rows, 'nothing was found live'
        row = crawler.get_detail(rows[0]['链接'])
    finally:
        crawler.close()
    assert row and row['视频ID'] == douyin_id(rows[0]['链接'])
    assert row['链接'].startswith('https://www.douyin.com/video/')
    assert DouyinCrawler.never_headless is True and DouyinCrawler.supports_crawl is True


def test_a_link_that_is_not_a_video_is_dead(live_crawler):
    crawler = live_crawler('douyin', headless=False)
    try:
        session = CommentSession(crawler.driver, log=print, nap=lambda s: None)
        rows, status = session.crawl_douyin('https://www.douyin.com/jingxuan', 5)
    finally:
        crawler.close()
    assert rows == [] and status == DEAD
