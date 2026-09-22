"""Live Bilibili crawl — real Chrome, the user's saved cookie, real bilibili.com.

The fixture link is one the user handed over for this purpose
(``BV1s4Js68EVp``); everything else is discovered live, because a bookmarked
video can be withdrawn and a search page cannot.

The assertions are the ones the probes earned:

* a row's numbers come from ``x/web-interface/view``, so 播放数 must be a real
  integer (not the card's rounded 万-label) and the 链接 must be the video page;
* a comment crawl must actually page — one screen of 19 rows is what a single
  request gives, so ``limit=40`` is the cheapest way to prove the cursor walk;
* a refusal (risk control, dead cookie) surfaces as ``blocked`` and skips the
  test, never as an empty table that reads like "this video has no comments".
"""

import pytest

from crawlers.comments import BLOCKED, DEAD, OK, CommentSession
from crawlers.video import bilibili_bvid

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]

#: The video the user supplied for real testing.
PROBE_URL = 'https://www.bilibili.com/video/BV1s4Js68EVp/'


def _assert_real_rows(rows, minimum=2):
    assert len(rows) >= minimum, f'expected at least {minimum} rows, got {len(rows)}'
    for row in rows:
        assert row['链接'].startswith('https://www.bilibili.com/video/BV'), row['链接']
        assert bilibili_bvid(row['链接']), 'the link must carry the id the row was built from'
        assert (row['标题'] or '').strip(), f'row without a title: {row}'
        assert (row['UP主'] or '').strip(), f'row without an UP主: {row}'
        assert isinstance(row['播放数'], int) and row['播放数'] > 0, f'播放数 must be a real count: {row}'
        assert (row['发布时间'] or '').startswith('20'), f'发布时间 not formatted: {row}'
    links = {row['链接'] for row in rows}
    assert len(links) == len(rows), 'rows must be distinct videos (dedupe identity is the link)'


@pytest.mark.parametrize('headless', [True, False], ids=['headless', 'visible'])
def test_search_returns_rows_resolved_through_the_api(live_crawler, headless):
    crawler = live_crawler('bilibili', headless=headless)
    try:
        rows = crawler.search('人工智能', target_count=4)
    finally:
        crawler.close()
    _assert_real_rows(rows, minimum=2)
    # The endpoint is the only source of these two: the search card shows a
    # rounded 播放 label and never shows 投币/收藏/转发 at all.
    assert any(row['收藏数'] > 0 for row in rows), 'no row carried 收藏数 — the detail fetch failed'
    assert any(row['投币数'] > 0 for row in rows), 'no row carried 投币数 — the detail fetch failed'


def test_pager_reaches_beyond_one_screen(live_crawler):
    """One search page holds ~34 videos and scrolling adds nothing, so more rows
    than that is the proof the ``&page=N`` walk works — and that page 1 was
    requested without the parameter that renders it empty."""
    crawler = live_crawler('bilibili')
    try:
        rows = crawler.search('人工智能', target_count=40)
    finally:
        crawler.close()
    _assert_real_rows(rows, minimum=35)


def test_detail_read_of_the_probe_video(live_crawler):
    crawler = live_crawler('bilibili')
    try:
        row = crawler.get_detail(PROBE_URL)
    finally:
        crawler.close()
    assert row, 'the probe video must resolve through the view endpoint'
    assert row['BV号'] == 'BV1s4Js68EVp'
    assert row['链接'] == PROBE_URL
    assert (row['标题'] or '').strip() and row['播放数'] > 0
    assert row['评论数'] >= 0 and isinstance(row['时长秒'], int)


@pytest.mark.parametrize('headless', [True, False], ids=['headless', 'visible'])
def test_comments_page_past_one_screen(live_crawler, headless):
    crawler = live_crawler('bilibili', headless=headless)
    try:
        session = CommentSession(crawler.driver, log=print, nap=lambda s: None)
        rows, status = session.crawl_bilibili(PROBE_URL, limit=40)
    finally:
        crawler.close()
    assert status == OK, f'bilibili comment crawl ended as {status} on {PROBE_URL}'
    assert len(rows) > 19, 'a single page answers 19-20 rows — more than that proves the cursor walk'
    seen = {row['评论ID'] for row in rows}
    assert len(seen) == len(rows), 'the cursor replayed a page instead of advancing'
    for row in rows:
        assert row['平台'] == 'bilibili' and row['文章URL'] == PROBE_URL
        assert (row['评论内容'] or '').strip() or (row['评论者'] or '').strip()
        assert row['评论时间'].startswith('20'), f'评论时间 not formatted: {row}'
    assert any(row['点赞数'] > 0 for row in rows), 'the hot-sorted page must carry liked comments'
    assert any(row['父评论ID'] for row in rows), 'sub-replies should flatten under their parent'


def test_a_link_that_is_not_a_video_is_dead_not_empty(live_crawler):
    crawler = live_crawler('bilibili')
    try:
        session = CommentSession(crawler.driver, log=print, nap=lambda s: None)
        rows, status = session.crawl_bilibili('https://www.bilibili.com/bangumi/play/ss12345/', 5)
    finally:
        crawler.close()
    assert rows == [] and status in (DEAD, BLOCKED), f'a non-video link must be refused, not tabled: {status}'
