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

    def click(self):
        # The 2026 layout made 阅读全文 a NAVIGATION on column cards — clicking
        # it used to detach every remaining card. It must never be clicked.
        raise AssertionError(f'crawler clicked an expand button (text={self.text!r}) — regression')


class FakeCard:
    """A search-result card: a selector -> text map. Unknown selectors raise the
    same NoSuchElementException the real driver raises, which is what the
    crawler's per-field fallbacks are written against."""

    def __init__(self, texts, buttons=()):
        self._texts = texts
        self._buttons = list(buttons)

    def find_element(self, by, selector):
        if selector in self._texts:
            return FakeElement(self._texts[selector])
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        if selector.startswith('.ContentItem-actions') and self._buttons:
            return [FakeElement(t) for t in self._buttons]
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
    # The 2026 card carries no author element at all — the name is inlined as
    # a '作者名：正文' prefix inside the preview. 阅读全文 is present and MUST
    # NOT be clicked (FakeElement.click raises).
    '.ContentItem-title a': '三亚的冬天可以下海',
    '.RichContent-inner .RichText': '张三：海水温度非常舒适适合游泳。',
    'button.ContentItem-more': '阅读全文',
    '.VoteButton': '赞同 128',
    '.SearchItem-time': '09-06',
}
CARD_1_BUTTONS = ['赞同 128', '12条评论']
CARD_2 = dict(CARD_1, **{'.ContentItem-title a': '海口美食清单', '.RichContent-inner .RichText': '李四：清补凉必吃。'})
CARD_2_BUTTONS = ['赞同 9', '添加评论']
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
        crawler, driver = make_crawler([FakeCard(CARD_1, CARD_1_BUTTONS)])
        crawler.search('三亚', target_count=1)
        url = driver.visited[0]
        assert url.startswith('https://www.zhihu.com/search?q=')
        assert '%E4%B8%89%E4%BA%9A' in url and 'type=content' in url

    def test_cards_parse_into_full_rows(self, make_crawler):
        # FakeElement.click raises, so this test ALSO proves 阅读全文 is never
        # clicked — the navigation that used to detach every card after it.
        crawler, _ = make_crawler([FakeCard(CARD_1, CARD_1_BUTTONS), FakeCard(CARD_2, CARD_2_BUTTONS)])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 2
        first = rows[0]
        assert first['作者'] == '张三'  # parsed from the '作者名：' content prefix
        assert first['标题'] == '三亚的冬天可以下海'
        assert first['正文'] == '张三：海水温度非常舒适适合游泳。'
        assert first['赞同数'] == 128
        assert first['评论数'] == 12
        assert first['发布时间'] == '09-06'
        assert rows[1]['作者'] == '李四' and rows[1]['评论数'] == 0  # '添加评论' == zero

    def test_content_without_author_prefix_keeps_the_row(self, make_crawler):
        no_author = dict(CARD_1)
        no_author['.RichContent-inner .RichText'] = '海水温度非常舒适适合游泳。'
        crawler, _ = make_crawler([FakeCard(no_author)])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1 and rows[0]['作者'] == ''

    def test_card_without_author_and_body_is_dropped(self, make_crawler):
        crawler, _ = make_crawler([FakeCard(CARD_EMPTY), FakeCard(CARD_1, CARD_1_BUTTONS)])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1 and rows[0]['作者'] == '张三'
        assert crawler.position['scanned'] == 2  # the skip was still recorded

    def test_sink_rejections_drop_rows_but_keep_position(self, make_crawler):
        crawler, _ = make_crawler([FakeCard(CARD_1, CARD_1_BUTTONS), FakeCard(CARD_2, CARD_2_BUTTONS)])
        seen = []

        def sink(item):
            seen.append(item)
            return len(seen) == 1  # second item "already collected"

        crawler.set_sink(sink)
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1
        assert crawler.position['done'] == 1

    def test_target_reached_before_navigating_when_seeded(self, make_crawler):
        crawler, driver = make_crawler([FakeCard(CARD_1, CARD_1_BUTTONS)])
        crawler.seed([{'作者': '甲'}, {'作者': '乙'}])
        rows = crawler.search('三亚', target_count=2)
        assert driver.visited == []  # resume: nothing left to fetch
        assert len(rows) == 2

    def test_target_count_truncates_mid_card_run(self, make_crawler):
        crawler, _ = make_crawler([FakeCard(CARD_1, CARD_1_BUTTONS), FakeCard(CARD_2, CARD_2_BUTTONS)])
        rows = crawler.search('三亚', target_count=1)
        assert len(rows) == 1
        # '没有更多了' / stuck detection are scroll-loop exits; the card cap must
        # stop collection regardless of how many cards the page offered.
        assert crawler.position['done'] == 1

    def test_missing_more_marker_ends_the_scroll_loop(self, make_crawler):
        crawler, driver = make_crawler([FakeCard(CARD_1, CARD_1_BUTTONS)] * 2)
        driver._no_more = '亲，没有更多了~'
        rows = crawler.search('三亚', target_count=50)
        assert len(rows) == 2  # loop broke at the marker, not at 150 scrolls
