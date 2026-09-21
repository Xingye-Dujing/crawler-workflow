"""Zhihu parser tests driven by a fake Selenium driver — no browser needed.

The point is not Selenium (that chain gets its own real-Chrome tier via the
WeChat fixture), it is zhihu.py's scraping logic: the search URL it builds, the
exact selector set it reads cards through, the "作者 or 正文 must be present"
keep-filter, the streaming sink, and the resume arithmetic. A fake driver lets
all of that run in the default suite in milliseconds.
"""

import pytest
from selenium.common.exceptions import NoSuchElementException

import crawlers.base as base_module
from crawlers.base import Crawler
from crawlers.zhihu import ZhihuCrawler

pytestmark = pytest.mark.unit


class FakeElement:
    def __init__(self, text='', href='', aria=None):
        self.text = text
        self._attrs = {'href': href}
        if aria is not None:
            self._attrs['aria-label'] = aria

    def get_attribute(self, name):
        return self._attrs.get(name, '')

    def click(self):
        # The 2026 layout made 阅读全文 a NAVIGATION on column cards — clicking
        # it used to detach every remaining card. It must never be clicked.
        raise AssertionError(f'crawler clicked an expand button (text={self.text!r}) — regression')


class FakeCard:
    """A search-result card: a selector -> text map plus the handful of
    attributes the crawler reads. Unknown selectors raise the same
    NoSuchElementException the real driver raises, which is what the crawler's
    per-field fallbacks are written against."""

    def __init__(self, texts, buttons=(), hrefs=None, module='', aria=None, cls=''):
        self._texts = texts
        self._buttons = list(buttons)
        self._hrefs = hrefs or {}
        self._module = module
        self._aria = aria
        self._cls = cls

    def find_element(self, by, selector):
        if selector in self._texts:
            return FakeElement(self._texts[selector], self._hrefs.get(selector, ''))
        if selector.startswith('[aria-label*') and self._aria:
            return FakeElement('', aria=self._aria)
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        if selector.startswith('.ContentItem-actions') and self._buttons:
            return [FakeElement(text) for text in self._buttons]
        if selector == 'a[href]' and self._hrefs:
            return [FakeElement('', href) for href in self._hrefs.values() if href]
        return []

    def get_attribute(self, name):
        if name == 'data-za-detail-view-path-module':
            return self._module
        if name == 'class':
            return self._cls
        return ''


class FakeDriver:
    """Returns a fixed card list, or one that grows on every scroll round (the
    interleaved harvest is only observable if the page can gain cards)."""

    def __init__(self, cards, grow_by=0, max_cards=200, no_more=None, body_text=''):
        self.cards = list(cards)
        self.grow_by = grow_by
        self.max_cards = max_cards
        self.visited = []
        self.scrolls = 0
        self._no_more = no_more
        self._body = body_text

    def get(self, url):
        self.visited.append(url)

    def find_element(self, by, selector):
        if selector == '.css-7hmi9v' and self._no_more is not None:
            return FakeElement(self._no_more)
        if selector == 'body':
            return FakeElement(self._body)
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        if selector.startswith('.SearchResult-Card[role'):
            return list(self.cards)
        return []

    def execute_script(self, script, *args):
        if 'scroll' in script:
            self.scrolls += 1
            # One harvest round is `SCROLL_STEPS` steps plus the bottom jump.
            if self.grow_by and self.scrolls % (ZhihuCrawler.SCROLL_STEPS + 1) == 0:
                room = max(0, self.max_cards - len(self.cards))
                self.cards.extend(self.cards[: min(room, self.grow_by)])
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
CARD_1_HREFS = {'.ContentItem-title a': 'https://www.zhihu.com/question/123/answer/456'}
CARD_2 = dict(
    CARD_1,
    **{
        '.ContentItem-title a': '海口美食清单',
        '.RichContent-inner .RichText': '李四：清补凉必吃。',
    },
)
CARD_2_BUTTONS = ['赞同 9', '添加评论']
CARD_2_HREFS = {'.ContentItem-title a': 'https://zhuanlan.zhihu.com/p/789'}
CARD_EMPTY = {}  # neither author nor body → the keep-filter must drop it


def _card(texts, buttons=(), hrefs=None, module='PostItem', aria=None, cls=''):
    return FakeCard(texts, buttons, hrefs, module, aria, cls)


@pytest.fixture
def make_crawler(monkeypatch):
    """Construct a ZhihuCrawler whose _create_driver installs a FakeDriver, and
    whose waits/sleeps are instant. Returns (crawler, driver)."""
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(cards, **driver_kwargs):
        driver = FakeDriver(cards, **driver_kwargs)

        def fake_create(self, *a, **kw):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        crawler = ZhihuCrawler(headless=True)
        crawler.wait_for_element = lambda selector, timeout=None: True
        return crawler, driver

    return _make


class TestZhihuSearch:
    def test_search_url_carries_the_encoded_keyword(self, make_crawler):
        crawler, driver = make_crawler([_card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS)])
        crawler.search('三亚', target_count=1)
        url = driver.visited[0]
        assert url.startswith('https://www.zhihu.com/search?q=')
        assert '%E4%B8%89%E4%BA%9A' in url and 'type=content' in url

    def test_card_selector_takes_every_result_kind(self, make_crawler):
        # The list is mostly answers; restricting it to PostItem made the
        # crawler scroll for cards it had already thrown away.
        crawler, _ = make_crawler(
            [
                _card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS, module='AnswerItem'),
                _card(CARD_2, CARD_2_BUTTONS, CARD_2_HREFS, module='PostItem'),
            ]
        )
        rows = crawler.search('三亚', target_count=5)
        assert [r['分类'] for r in rows] == ['回答', '文章']

    def test_cards_parse_into_full_rows(self, make_crawler):
        # FakeElement.click raises, so this test ALSO proves 阅读全文 is never
        # clicked — the navigation that used to detach every card after it.
        crawler, _ = make_crawler(
            [
                _card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS, module='AnswerItem'),
                _card(CARD_2, CARD_2_BUTTONS, CARD_2_HREFS, module='PostItem'),
            ]
        )
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 2
        first = rows[0]
        assert first['作者'] == '张三'  # parsed from the '作者名：' content prefix
        assert first['标题'] == '三亚的冬天可以下海'
        assert first['正文'] == '张三：海水温度非常舒适适合游泳。'
        assert first['赞同数'] == 128
        assert first['评论数'] == 12
        assert first['发布时间'] == '09-06'
        assert first['链接'] == 'https://www.zhihu.com/question/123/answer/456'
        assert first['分类'] == '回答'
        assert rows[1]['作者'] == '李四' and rows[1]['评论数'] == 0  # '添加评论' == zero

    def test_comment_count_falls_back_to_the_aria_label(self, make_crawler):
        # Some cards label comments only through aria-label; the vote button
        # next to it must never be read as a comment count.
        card = _card(CARD_1, ['赞同 128'], CARD_1_HREFS, aria='查看 7 条回答')
        crawler, _ = make_crawler([card])
        rows = crawler.search('三亚', target_count=5)
        assert rows[0]['评论数'] == 7
        assert rows[0]['赞同数'] == 128

    def test_content_without_author_prefix_keeps_the_row(self, make_crawler):
        no_author = dict(CARD_1)
        no_author['.RichContent-inner .RichText'] = '海水温度非常舒适适合游泳。'
        crawler, _ = make_crawler([_card(no_author)])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1 and rows[0]['作者'] == ''

    def test_card_without_author_and_body_is_dropped(self, make_crawler):
        crawler, _ = make_crawler([_card(CARD_EMPTY), _card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS)])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1 and rows[0]['作者'] == '张三'
        assert crawler.position['scanned'] == 2  # the skip was still recorded

    def test_sink_rejections_drop_rows_but_keep_position(self, make_crawler):
        crawler, _ = make_crawler(
            [
                _card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS),
                _card(CARD_2, CARD_2_BUTTONS, CARD_2_HREFS),
            ]
        )
        seen = []

        def sink(item):
            seen.append(item)
            return len(seen) == 1  # second item "already collected"

        crawler.set_sink(sink)
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1
        assert crawler.position['done'] == 1

    def test_target_reached_before_navigating_when_seeded(self, make_crawler):
        crawler, driver = make_crawler([_card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS)])
        crawler.seed([{'作者': '甲'}, {'作者': '乙'}])
        rows = crawler.search('三亚', target_count=2)
        assert driver.visited == []  # resume: nothing left to fetch
        assert len(rows) == 2

    def test_resumed_cursor_skips_cards_already_scanned(self, make_crawler):
        crawler, driver = make_crawler(
            [
                _card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS),
                _card(CARD_2, CARD_2_BUTTONS, CARD_2_HREFS),
            ]
        )
        crawler.seed([{'作者': '张三', '链接': CARD_1_HREFS['.ContentItem-title a']}])
        rows = crawler.search('三亚', target_count=3, resume={'keyword': '三亚', 'scanned': 1})
        # card 1 was read before the interruption; only card 2 is new.
        assert len(rows) == 2
        assert rows[-1]['作者'] == '李四'
        assert crawler.position['scanned'] == 2
        assert driver.visited  # the page itself is reloaded, the cursor is not

    def test_target_count_truncates_mid_card_run(self, make_crawler):
        crawler, _ = make_crawler(
            [
                _card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS),
                _card(CARD_2, CARD_2_BUTTONS, CARD_2_HREFS),
            ]
        )
        rows = crawler.search('三亚', target_count=1)
        assert len(rows) == 1
        # '没有更多了' / stuck detection are scroll-loop exits; the card cap must
        # stop collection regardless of how many cards the page offered.
        assert crawler.position['done'] == 1
        assert crawler.position['scanned'] == 1

    def test_missing_more_marker_ends_the_scroll_loop(self, make_crawler):
        crawler, driver = make_crawler([_card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS)] * 2, no_more='亲，没有更多了~')
        rows = crawler.search('三亚', target_count=50)
        assert len(rows) == 2  # loop broke at the marker, not at 30 scrolls
        assert driver.scrolls <= ZhihuCrawler.SCROLL_STEPS * 2 + 2

    def test_rows_stream_during_scrolling_not_after(self, make_crawler):
        """The speed contract: cards are harvested after every round, so a
        resumed/interrupted crawl already streamed what it collected."""
        cards = [_card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS) for _ in range(3)]
        crawler, driver = make_crawler(cards, grow_by=3, max_cards=9)
        timeline = []
        crawler.set_sink(lambda item: timeline.append((crawler._card_count(), len(timeline) + 1)) or True)
        rows = crawler.search('三亚', target_count=6)
        assert len(rows) == len(timeline)
        # The first emission happened while the page still had far fewer cards
        # than the crawl ended with — i.e. harvesting was interleaved.
        assert timeline[0][0] < driver.max_cards
        assert rows[-1] is not None

    def test_stuck_pages_end_the_loop(self, make_crawler):
        crawler, driver = make_crawler([_card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS)], no_more=None)
        rows = crawler.search('三亚', target_count=50)
        assert len(rows) == 1
        # Three fruitless rounds is the ceiling; a runaway 150-scroll loop is the
        # bug this guards against.
        assert driver.scrolls <= ZhihuCrawler.SCROLL_STEPS * (ZhihuCrawler.STUCK_ROUNDS + 1) + 6


class TestLinkFallback:
    def test_promo_card_without_title_anchor_still_gets_a_link(self, make_crawler):
        # Paid-column / promo cards carry no .ContentItem-title a — the first
        # real href on the card is still the article's own destination.
        promo = {'.RichContent-inner .RichText': '推广：三亚酒店特惠，点击了解详情。'}
        card = _card(promo, hrefs={'any-link': 'https://www.zhihu.com/market/paid_column/1?x=1'})
        crawler, _ = make_crawler([card])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1
        assert rows[0]['链接'] == 'https://www.zhihu.com/market/paid_column/1?x=1'
        assert rows[0]['标题'] == ''

    def test_unmounted_card_link_nudged_into_view(self, make_crawler):
        # Virtualised lists ship top cards with zero anchors; the nudge path
        # scrolls the card into view and re-scrapes once before accepting a
        # link-less row. The fake gains its anchor between scrapes.
        texts = dict(CARD_1)
        card = _card(texts, CARD_1_BUTTONS, hrefs=None)
        crawler, driver = make_crawler([card])
        original_scrape = crawler._scrape_card

        def scraping(card_obj):
            item = original_scrape(card_obj)
            if not card._hrefs:  # first pass: mount the card for the retry
                card._hrefs = {'.ContentItem-title a': 'https://zhuanlan.zhihu.com/p/late-mount'}
            return item

        crawler._scrape_card = scraping
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1
        assert rows[0]['链接'] == 'https://zhuanlan.zhihu.com/p/late-mount'


class TestPromoCardsExcluded:
    def test_hot_landing_answer_cards_are_never_harvested(self, make_crawler):
        # 热榜落地推广卡 (AnswerItem-hotLanding): zero anchors, no title node —
        # the live search page leads with them and they polluted the table.
        promo = _card(
            {'.RichContent-inner .RichText': '张三：海水温度非常舒适适合游泳。'},
            hrefs=None,
            module='AnswerItem',
            cls='Card SearchResult-Card AnswerItem-hotLanding',
        )
        normal = _card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS)
        crawler, _ = make_crawler([promo, normal])
        rows = crawler.search('三亚', target_count=5)
        assert len(rows) == 1
        assert rows[0]['链接'] == CARD_1_HREFS['.ContentItem-title a']


class TestZeroCardSearch:
    """A search page that loads no cards is zhihu's day-by-day headless risk
    control — and, historically, the one branch that crashed with an
    AttributeError because its fallback helpers were never implemented.
    Zero cards must speak with the catalog's actionable line, never a
    traceback, and the shell/no-result distinction must actually branch."""

    def test_a_silent_zero_page_raises_the_actionable_message(self, make_crawler):
        crawler, _ = make_crawler([])
        with pytest.raises(RuntimeError) as exc:
            crawler.search('三亚', target_count=3)
        assert '风控' in str(exc.value) or 'risk control' in str(exc.value)

    def test_a_definite_no_result_plate_does_not_burn_the_fallback(self, make_crawler, monkeypatch):
        crawler, driver = make_crawler([])
        driver._body = '未搜索到相关内容'  # the page already ANSWERED: zero is real
        tried = []
        monkeypatch.setattr(crawler, '_search_via_input', lambda kw: tried.append(kw) or True)
        with pytest.raises(RuntimeError):
            crawler.search('三亚', target_count=3)
        assert tried == [], 'a definitive no-results plate must not trigger a retry'

    def test_the_shell_page_retries_once_through_the_search_box(self, make_crawler, monkeypatch):
        crawler, driver = make_crawler([])
        card = _card(CARD_1, CARD_1_BUTTONS, CARD_1_HREFS)

        def fake_input(kw):
            # The resubmitted request is the one the SPA actually fetches.
            driver.cards.append(card)
            return True

        monkeypatch.setattr(crawler, '_search_via_input', fake_input)
        rows = crawler.search('三亚', target_count=1)
        assert len(rows) == 1

    def test_the_fallback_gives_up_quietly_when_the_box_moved(self, make_crawler):
        # No 'body'/'PromptInput'/input in the fake driver at all except body
        # (empty text): the real _search_via_input finds no box and must say
        # so with False, not an exception.
        crawler, _ = make_crawler([])
        assert crawler._search_via_input('三亚') is False
