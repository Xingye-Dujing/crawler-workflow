"""Zhihu parser tests driven by a fake Selenium driver — no browser needed.

The point is not Selenium (that chain gets its own real-Chrome tier via the
WeChat fixture), it is zhihu.py's scraping logic: the search URL it builds,
the exact selector set it reads cards through, the "作者 or 正文 must be
present" keep-filter, the streaming sink, and the resume arithmetic. A fake
driver lets all of that run in the default suite in milliseconds.
"""
import pytest
from selenium.common.exceptions import NoSuchElementException

import crawlers.zhihu as zhihu_module
from crawlers.base import Crawler
from crawlers.zhihu import ZhihuCrawler

pytestmark = pytest.mark.unit


class FakeElement:
    def __init__(self, text=''):
        self.text = text
        self.clicks = 0

    def click(self):
        self.clicks += 1


class FakeCard:
    """A search-result card: a selector -> text map. Unknown selectors raise the
    same NoSuchElementException the real driver raises, which is what the
    crawler's per-field fallbacks are written against."""

    def __init__(self, texts):
        self._texts = texts

    def find_element(self, by, selector):
        if selector in self._texts:
            return FakeElement(self._texts[selector])
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):  # pragma: no cover - not used by zhihu card parsing
        return []


class FakeDriver:
    def __init__(self, cards):
        self.cards = cards
        self.visited = []
        self._no_more = None

    def get(self, url):
        self.visited.append(url)

    def find_element(self, by, selector):
        if selector == '.css-7hmi9v' and self._no_more is not None:
            return FakeElement(self._no_more)
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        if selector.startswith('.SearchResult-Card[role'):
            return list(self.cards)
        return []

    def execute_script(self, script, *args):
        if 'scrollTo' in script:
            return None
        if 'innerText' in script and args:
            return args[0].text
        return None

    def quit(self):
        pass


CARD_1 = {
    '.AuthorInfo-name .UserLink-link': '张三',
    '.ContentItem-title a': '三亚的冬天可以下海',
    '.RichContent-inner .RichText': '海水温度非常舒适适合游泳。',
    '.VoteButton': '128 赞同',
    'button[aria-label*="评论"]': '12条评论',
    '.ContentItem-time a, .ContentItem-time div': '发布于 2026-01-01 09:00',
}
CARD_2 = dict(CARD_1, **{'.AuthorInfo-name .UserLink-link': '李四', '.ContentItem-title a': '海口美食清单'})
CARD_EMPTY = {}  # neither author nor body → the keep-filter must drop it


@pytest.fixture
def make_crawler(monkeypatch):
    """Construct a ZhihuCrawler whose _create_driver installs a FakeDriver, and
    whose waits/sleeps are instant. Returns (crawler, driver)."""
    monkeypatch.setattr(zhihu_module.time, 'sleep', lambda s: None)

    def _make(cards):
        driver = FakeDriver(cards)

        def fake_create(self, *a, **kw):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        crawler = ZhihuCrawler(headless=True)
        crawler.wait_for_element = lambda selector, timeout=None: True
        return crawler, driver

    return _make


class TestZhihuSearch:
    def test_search_url_carries_the_encoded_keyword(self, make_crawler):
        crawler, driver = make_crawler([FakeCard(CARD_1)])
        crawler.search('三亚', target_count=1)
        url = driver.visited[0]
        assert url.startswith('https://www.zhihu.com/search?q=')
        assert '%E4%B8%89%E4%BA%9A' in url and 'type=content' in url

    def test_cards_parse_into_full_rows(self, make_crawler):
        crawler, _ = make_crawler([FakeCard(CARD_1), FakeCard(CARD_2)])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 2
        first = rows[0]
        assert first['作者'] == '张三'
        assert first['标题'] == '三亚的冬天可以下海'
        assert first['正文'].startswith('海水温度')
        assert first['赞同数'] == 128
        assert first['评论数'] == 12
        assert '2026' in first['发布时间']

    def test_card_without_author_and_body_is_dropped(self, make_crawler):
        crawler, _ = make_crawler([FakeCard(CARD_EMPTY), FakeCard(CARD_1)])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1 and rows[0]['作者'] == '张三'
        assert crawler.position['scanned'] == 2  # the skip was still recorded

    def test_sink_rejections_drop_rows_but_keep_position(self, make_crawler):
        crawler, _ = make_crawler([FakeCard(CARD_1), FakeCard(CARD_2)])
        seen = []

        def sink(item):
            seen.append(item)
            return len(seen) == 1  # second item "already collected"

        crawler.set_sink(sink)
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1
        assert crawler.position['done'] == 1

    def test_target_reached_before_navigating_when_seeded(self, make_crawler):
        crawler, driver = make_crawler([FakeCard(CARD_1)])
        crawler.seed([{'作者': '甲'}, {'作者': '乙'}])
        rows = crawler.search('三亚', target_count=2)
        assert driver.visited == []  # resume: nothing left to fetch
        assert len(rows) == 2

    def test_target_count_truncates_mid_card_run(self, make_crawler):
        crawler, _ = make_crawler([FakeCard(CARD_1), FakeCard(CARD_2)])
        rows = crawler.search('三亚', target_count=1)
        assert len(rows) == 1
        # '没有更多了' / stuck detection are scroll-loop exits; the card cap must
        # stop collection regardless of how many cards the page offered.
        assert crawler.position['done'] == 1

    def test_missing_more_marker_ends_the_scroll_loop(self, make_crawler):
        crawler, driver = make_crawler([FakeCard(CARD_1)] * 2)
        driver._no_more = '亲，没有更多了~'
        rows = crawler.search('三亚', target_count=50)
        assert len(rows) == 2  # loop broke at the marker, not at 150 scrolls
