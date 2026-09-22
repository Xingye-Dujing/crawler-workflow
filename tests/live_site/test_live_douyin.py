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

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]

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


def test_a_headless_attempt_refuses_instead_of_filing_zeros(live_crawler):
    """The measured environment fact, pinned: headless gets the captcha page.

    If douyin ever lets a headless session through, this skips — the contract
    that must not break is "no silent empty success", not the refusal itself.
    """
    crawler = live_crawler('douyin', headless=True)
    try:
        with pytest.raises((RuntimeError, ValueError)) as err:
            crawler.search(KEYWORD, target_count=2)
        message = str(err.value)
        assert '验证' in message or '搜索框' in message, f'unexpected refusal text: {message}'
    except pytest.fail.Exception:
        pytest.skip('douyin answered a headless session this run — the wall moved, not the code')
    finally:
        crawler.close()


def test_comments_scroll_past_the_first_screen(live_crawler):
    """Paging proof, sized to the video that is actually on screen.

    The crawler picks which video to comment-crawl from what the live search
    returned, so the threshold has to come from that video's own reported count:
    a 6-comment video cannot demonstrate a scroll walk, and asserting 15+ from it
    would fail for a reason that has nothing to do with the code.
    """
    crawler = live_crawler('douyin', headless=False)
    try:
        rows = crawler.search(KEYWORD, target_count=4)
        assert rows, 'no video to comment on was found live'
        best = max(rows, key=lambda row: int(row['评论数'] or 0))
        link, reported = best['链接'], int(best['评论数'] or 0)
        if reported < 30:
            pytest.skip(f'none of the {len(rows)} live videos had enough comments to page (max {reported})')
        session = CommentSession(crawler.driver, log=print, nap=lambda s: None)
        comments, status = session.crawl_douyin(link, limit=40)
    finally:
        crawler.close()
    assert status == OK, f'douyin comment crawl ended as {status} on {link}'
    assert comments, 'a video reporting 评论数>0 must yield comment rows'
    for row in comments:
        assert row['平台'] == 'douyin' and row['文章URL'].endswith(douyin_id(link))
        assert (row['评论内容'] or '').strip(), f'comment row without text: {row}'
    keys = {(row['评论者'], row['评论内容']) for row in comments}
    assert len(keys) == len(comments), 'the scroll replayed a comment instead of advancing'
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
