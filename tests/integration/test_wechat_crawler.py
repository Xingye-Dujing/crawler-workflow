"""End-to-end crawler test against a REAL Chrome — no live website involved.

WeChat's crawler natively accepts explicit article URLs, so the test points it
at a local ``file://`` fixture built with the same ids the real article pages
use (#activity-name, .rich_media_content, #js_name…). This is the only tier
that proves the whole Selenium chain — driver creation with the configured
chromedriver, page load, waits, scroll, CSS-selector extraction — actually
works on this machine. Selected only with ``-m integration``.
"""

import pytest

from crawlers.wechat import WechatCrawler

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def _new_crawler() -> WechatCrawler:
    try:
        return WechatCrawler(headless=True)
    except Exception as e:  # any failure to start Chrome = environment gap, not code bug
        pytest.skip(f'Chrome/chromedriver unavailable: {e}')


@pytest.fixture
def crawler():
    c = _new_crawler()
    try:
        yield c
    finally:
        c.close()


def test_fixture_is_a_shaped_wechat_page(crawler, wechat_article_url):
    """Sanity: the fixture really parses — if this fails, all parsing is suspect."""
    data = crawler.get_detail(wechat_article_url)
    assert data is not None
    assert data['标题'] == '三亚冬日旅游攻略'
    assert data['公众号'] == '旅行实验室'
    assert '2026' in data['发布时间']
    assert '亚龙湾' in data['正文']
    assert data['阅读数'] == 12345
    assert data['在看数'] == 67
    assert data['赞赏数'] == 8
    assert data['链接'] == wechat_article_url


def test_search_streams_items_through_the_sink(crawler, wechat_article_url):
    """The streaming contract (base.py): every scraped item passes through the
    sink, and a sink saying "already have it" keeps it out of results."""
    seen = []
    crawler.set_sink(lambda item: seen.append(item['标题']) or False)
    results = crawler.search(urls=[wechat_article_url])
    assert seen == ['三亚冬日旅游攻略']  # scrape happened
    assert results == []  # but the sink rejected the duplicate


def test_resume_cursor_skips_finished_articles(crawler, wechat_article_url):
    """Re-searching with a stored cursor must not touch the already-done page."""
    visited = []
    original_get = crawler.driver.get
    crawler.driver.get = lambda url: visited.append(url) or original_get(url)
    crawler.seed([{'标题': '已抓过', '链接': wechat_article_url}])
    out = crawler.search(urls=[wechat_article_url], resume={'url_index': 1})
    assert visited == []  # the one article was already scraped — skipped entirely
    assert out[0]['标题'] == '已抓过'  # seeded rows ride along downstream
    assert crawler.position['done'] == 1


def test_position_advances_per_article(crawler, wechat_article_url):
    crawler.search(urls=[wechat_article_url])
    pos = crawler.position
    assert pos['url_index'] == 1
    assert pos['url_total'] == 1
    assert pos['done'] == 1
