"""Zhihu parser tests driven by a fake Selenium driver — no browser needed.

The point is not Selenium (that chain gets its own real-Chrome tier via the
WeChat fixture), it is zhihu.py's scraping logic: the search URL it builds, the
exact selector set it reads cards through, the "作者 or 正文 must be present"
keep-filter, whether a clamped card was opened before its body was kept, the
streaming sink, and the resume arithmetic. A fake driver lets all of that run in
the default suite in milliseconds.
"""

import re

import pytest
from selenium.common.exceptions import NoSuchElementException

import crawlers.base as base_module
import i18n
from crawlers.base import Crawler
from crawlers.zhihu import ZhihuCrawler

pytestmark = pytest.mark.unit


def _lines(caplog) -> list:
    """The console lines a crawl actually logged, as the crawler wrote them.

    Compared against ``i18n.t(...)`` rather than a pasted sentence: the wording is the
    product's to change, and a test that demands a literal copy of it fails on a
    translation edit while proving nothing about the crawl.
    """
    return [record.getMessage() for record in caplog.records]


class FakeElement:
    def __init__(self, text='', href='', aria=None):
        self.text = text
        self._attrs = {'href': href}
        if aria is not None:
            self._attrs['aria-label'] = aria

    def get_attribute(self, name):
        return self._attrs.get(name, '')

    def click(self):
        # Nothing in a search crawl should reach this: the crawler drives the
        # page through ``execute_script``, and the one control it may click is
        # answered by ``FakeCard.expand`` below, which is where the site's own
        # behaviour (in place vs away) is modelled.
        raise AssertionError(f'crawler clicked a DOM node directly (text={self.text!r}) — regression')


class FakeCard:
    """A search-result card: a selector -> text map plus the handful of
    attributes the crawler reads. Unknown selectors raise the same
    NoSuchElementException the real driver raises, which is what the crawler's
    per-field fallbacks are written against.

    The 阅读全文 control is modelled by the three flags below, each one a shape
    measured on the live page on 2026-09-24:

    * nothing set — the card carries no control, because that answer is short by itself;
    * ``after`` — an *answer* card's control re-renders the card in place (74 characters
      became 308, same URL, a handle two rows down still alive). The dict is what the
      page looks like afterwards, and it is not only the body: the date label also moves
      off ``.SearchItem-time`` onto a full timestamp, which is why the row keeps the
      values read before the click;
    * ``silent`` — the control is there and answers nothing, which is a truncated row
      the crawl has to admit to;
    * ``navigate`` — a *column* card's control leaves the page and detaches every
      remaining handle, so the crawler must never click one. That is an assertion, not a
      simulation: reaching it fails the test.
    """

    def __init__(
        self, texts, buttons=(), hrefs=None, module='', aria=None, cls='', after=None, silent=False, navigate=False
    ):
        self._texts = dict(texts)
        self._buttons = list(buttons)
        self._hrefs = hrefs or {}
        self._module = module
        self._aria = aria
        self._cls = cls
        self._after = dict(after or {})
        self._silent = silent
        self._navigate = navigate
        self.clicks = 0

    def expand(self) -> int:
        """What the site does when this card's 阅读全文 is clicked."""
        self.clicks += 1
        if self._navigate:
            raise AssertionError(
                'a column card was clicked — that navigates to its own page and detaches every remaining handle'
            )
        if not self._after and not self._silent:
            return 0
        for selector, text in self._after.items():
            if text is None:
                self._texts.pop(selector, None)
            else:
                self._texts[selector] = text
        return 1

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
        # Checked before the text reader: the expand script also mentions innerText,
        # and answering it with a text would hide the fact that a card was clicked.
        if '阅读全文' in script and args:
            return args[0].expand()
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
    # a '作者名：正文' prefix inside the preview. This card models one with no
    # 阅读全文 control (a short answer), so the preview IS its full body and
    # every assertion below about 正文 holds without expansion.
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


def _card(texts, buttons=(), hrefs=None, module='PostItem', aria=None, cls='', **site):
    return FakeCard(texts, buttons, hrefs, module, aria, cls, **site)


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
        # Neither of these cards carries a 阅读全文 control (see FakeCard), so the
        # preview is its full body and the parse below is the whole story.
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
    Every zero-card shape must now end honestly: recover, return the
    documented 0-row outcome, or raise the catalog's actionable line."""

    def test_the_unfetchable_shell_ends_in_zero_rows_not_a_crash(self, make_crawler):
        # No cards, no plate, no search box: nothing can be fetched. The run
        # returns the legitimate 0 rows (AGENTS: never pretend, never crash).
        crawler, _ = make_crawler([])
        rows = crawler.search('三亚', target_count=3)
        assert rows == []

    def test_a_definite_no_result_plate_returns_zero_rows_without_retry(self, make_crawler, monkeypatch):
        crawler, driver = make_crawler([])
        driver._body = '未搜索到相关内容'  # the page already ANSWERED: zero is real
        tried = []
        monkeypatch.setattr(crawler, '_search_via_input', lambda kw: tried.append(kw) or True)
        rows = crawler.search('三亚', target_count=3)
        assert rows == []
        assert tried == [], 'a definitive plate must not trigger a retry'

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

    def test_a_retry_that_lands_on_the_no_result_plate_raises_the_actionable_line(self, make_crawler, monkeypatch):
        crawler, driver = make_crawler([])

        def fake_input(kw):
            driver._body = '没有找到相关内容'  # the retry got a DEFINITE answer
            return True

        monkeypatch.setattr(crawler, '_search_via_input', fake_input)
        with pytest.raises(RuntimeError) as exc:
            crawler.search('三亚', target_count=3)
        assert '风控' in str(exc.value) or 'risk control' in str(exc.value)

    def test_the_fallback_gives_up_quietly_when_the_box_moved(self, make_crawler):
        # FakeDriver answers no box selectors at all: the real
        # _search_via_input must report False instead of throwing.
        crawler, _ = make_crawler([])
        assert crawler._search_via_input('三亚') is False


class TestBodyExpansion:
    """The search list hands out an excerpt, and the card's own 阅读全文 holds the rest.

    Measured 2026-09-24 across eight answer cards: 35–109 characters before the click,
    223–2103 after, and the answer's own page agreed (308 both places for one row). No CSS
    clamp is involved — ``innerText`` equalled ``textContent`` at 109 characters — so this
    is not a rendering problem a wider read could fix: an unexpanded row is a truncated
    row, and the only way to the text is the click.
    """

    ANSWER = 'https://www.zhihu.com/question/123/answer/456'
    COLUMN = 'https://zhuanlan.zhihu.com/p/789'
    PREVIEW = '张三：海水温度舒适。'
    FULL = '海水温度舒适，适合游泳，三亚的冬天比北海暖，人还少。' * 6

    def _answer(self, **site):
        texts = dict(CARD_1)
        texts['.RichContent-inner .RichText'] = self.PREVIEW
        return _card(texts, CARD_1_BUTTONS, {'.ContentItem-title a': self.ANSWER}, module='AnswerItem', **site)

    def test_the_default_is_to_expand(self, make_crawler):
        # The matrix's checkbox and the crawler's own default are one number, pinned by
        # test_crawl_capabilities; what this pins is that a caller who says nothing (a
        # hand-written workflow JSON, a live test) gets the full body rather than the stub.
        card = self._answer(after={'.RichContent-inner .RichText': self.FULL})
        crawler, _ = make_crawler([card])
        assert crawler.search('三亚', target_count=1)[0]['正文'] == self.FULL

    def test_an_answer_card_is_clicked_and_its_text_replaces_the_excerpt(self, make_crawler):
        card = self._answer(after={'.RichContent-inner .RichText': self.FULL})
        crawler, _ = make_crawler([card])
        rows = crawler.search('三亚', target_count=1)
        assert card.clicks == 1, 'the card was harvested still an excerpt'
        assert rows[0]['正文'] == self.FULL

    def test_the_rest_of_the_row_stays_what_the_list_reported(self, make_crawler):
        # The same click moves the date label too (measured: 08-27 became
        # 编辑于2026-08-27 12:22) and drops the 作者名： prefix off the front of the body.
        # Re-scraping the row after expanding would leave 发布时间 holding two formats
        # across one column, decided by an internal retry, and empty 作者 on the rows the
        # fix was meant to improve.
        card = self._answer(
            after={
                '.RichContent-inner .RichText': self.FULL,
                '.SearchItem-time': None,
                '.ContentItem-time a, .ContentItem-time div': '编辑于2026-09-06 12:22',
            }
        )
        crawler, _ = make_crawler([card])
        row = crawler.search('三亚', target_count=1)[0]
        assert row['正文'] == self.FULL
        assert row['发布时间'] == '09-06'
        assert row['作者'] == '张三'
        assert row['赞同数'] == 128 and row['评论数'] == 12

    def test_a_column_card_is_never_clicked(self, make_crawler):
        # FakeCard.expand raises for a navigate card, so passing at all is the proof.
        card = _card(
            dict(CARD_2, **{'.RichContent-inner .RichText': '李四：清补凉必吃。'}),
            CARD_2_BUTTONS,
            {'.ContentItem-title a': self.COLUMN},
            module='PostItem',
            after={'.RichContent-inner .RichText': '一整篇专栏文章。' * 40},
        )
        crawler, _ = make_crawler([card])
        rows = crawler.search('三亚', target_count=1)
        assert card.clicks == 0
        assert rows[0]['正文'] == '李四：清补凉必吃。'

    def test_a_card_whose_anchor_never_mounted_is_not_clicked(self, make_crawler):
        # No link means no kind, and the kind is what says the click is safe. The nudge
        # path re-scrapes and still finds nothing; expanding on that guess is what used to
        # cost the whole crawl.
        card = self._answer(after={'.RichContent-inner .RichText': self.FULL})
        card._hrefs = {}
        crawler, _ = make_crawler([card])
        rows = crawler.search('三亚', target_count=1)
        assert card.clicks == 0
        assert rows[0]['正文'] == self.PREVIEW

    def test_a_card_with_no_control_is_not_reported_as_a_shortfall(self, make_crawler, caplog):
        # A short answer is a complete row, not a failed expansion; the difference is
        # whether the site offered a control at all.
        crawler, _ = make_crawler([self._answer()])
        with caplog.at_level('INFO'):
            rows = crawler.search('三亚', target_count=1)
        assert rows[0]['正文'] == self.PREVIEW
        assert i18n.t('crawl.zhihu.bodies_short', n=1) not in _lines(caplog)

    def test_a_control_that_answers_nothing_is_counted_and_said(self, make_crawler, caplog):
        crawler, _ = make_crawler([self._answer(silent=True)])
        with caplog.at_level('INFO'):
            rows = crawler.search('三亚', target_count=1)
        assert rows[0]['正文'] == self.PREVIEW, 'a silent card must keep its preview, not lose it'
        assert i18n.t('crawl.zhihu.bodies_short', n=1) in _lines(caplog)

    def test_three_silent_cards_stop_the_paying(self, make_crawler, caplog):
        # Each failed click costs the full wait. A site that answers three clicks with
        # nothing is not answering any more, so the crawl stops asking rather than
        # spending a minute per hundred rows on a mechanism that already stopped working.
        silent = [self._answer(silent=True) for _ in range(3)]
        would_grow = self._answer(after={'.RichContent-inner .RichText': self.FULL})
        crawler, _ = make_crawler(silent + [would_grow], no_more='亲，没有更多了~')
        with caplog.at_level('INFO'):
            rows = crawler.search('三亚', target_count=9)
        assert [c.clicks for c in silent] == [1, 1, 1]
        assert would_grow.clicks == 0, 'the crawl kept paying for a mechanism that stopped working'
        assert len(rows) == 4
        assert i18n.t('crawl.zhihu.expand_stopped', n=3) in _lines(caplog)
        assert i18n.t('crawl.zhihu.bodies_short', n=3) in _lines(caplog)

    def test_turning_expansion_off_costs_no_click_and_says_so(self, make_crawler, caplog):
        card = self._answer(after={'.RichContent-inner .RichText': self.FULL})
        crawler, _ = make_crawler([card])
        with caplog.at_level('INFO'):
            rows = crawler.search('三亚', target_count=1, full_body=False)
        assert card.clicks == 0
        assert rows[0]['正文'] == self.PREVIEW
        lines = _lines(caplog)
        assert i18n.t('crawl.zhihu.excerpt_only') in lines
        # Chosen truncation is not the same fact as failed truncation; saying both would
        # be one line too many about the same column.
        assert i18n.t('crawl.zhihu.bodies_short', n=1) not in lines

    def test_a_crawl_that_kept_nothing_says_nothing_about_bodies(self, make_crawler, caplog):
        # The short-excerpt lines describe a table. A run risk-controlled into zero rows
        # has no 正文 column, and reporting one would describe a run that never happened.
        crawler, _ = make_crawler([])
        with caplog.at_level('INFO'):
            assert crawler.search('三亚', target_count=3, full_body=False) == []
        assert i18n.t('crawl.zhihu.excerpt_only') not in _lines(caplog)


class FakeBoardDriver:
    """Answers the zhihu home page and the in-page 热榜 bridge.

    ``payload`` is what ``hot-lists/total`` returns; ``wall`` parks the browser on
    ``/signin`` from the navigation itself, which is what an anonymous session is
    actually answered with (measured) before the endpoint ever says 401.
    """

    def __init__(self, payload, wall=False):
        self.payload = payload
        self.wall = wall
        self.current_url = 'about:blank'
        self.visited = []
        self.fetched = []

    def get(self, url):
        self.visited.append(url)
        if self.wall:
            self.current_url = 'https://www.zhihu.com/signin?next=%2F'
            return
        self.current_url = url

    def set_script_timeout(self, seconds):
        pass

    def execute_async_script(self, script):
        match = re.search(r'fetch\("(.*?)"', script)
        self.fetched.append(match.group(1) if match else script[:80])
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def find_element(self, by, selector):
        if selector == 'body':
            return FakeElement('登录 二维码' if self.wall else '知乎 首页')
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        return []

    def quit(self):
        pass


def _hot_row(question='2086444635463705931', title='网民吐槽美团抽成太多', heat='398 万热度', author='用户'):
    """One board entry, shaped by the measured answer: the author object carries the
    literal 「用户」 for every row and 评论数 is 0 for every row."""
    return {
        'type': 'hot_list_feed',
        'detail_text': heat,
        'card_id': f'Q_{question}',
        'target': {
            'type': 'question',
            'id': question,
            'title': title,
            'url': f'https://api.zhihu.com/questions/{question}',
            'excerpt': '小时候夏夜躺在院子的摘要',
            'answer_count': 275,
            'comment_count': 0,
            'follower_count': 134,
            'created': 1790258301,
            'author': {'name': author, 'type': 'people'},
        },
    }


def _board(rows):
    return {'data': list(rows), 'paging': {'is_end': True, 'next': '', 'is_start': False, 'totals': 0}}


@pytest.fixture
def make_board(monkeypatch):
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(payload, wall=False):
        driver = FakeBoardDriver(payload, wall=wall)

        def fake_create(self, *a, **kw):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return ZhihuCrawler(headless=True), driver

    return _make


class TestZhihuHotBoard:
    def test_the_board_drops_the_two_columns_that_are_not_data(self, make_board):
        """Measured on all 30 rows: 作者 is the literal 「用户」 and 评论数 is 0. A column
        of one repeated word, or of a number the payload never varies, is read by the
        user as content — so neither is emitted, and the columns that ARE filled stay."""
        second = _hot_row(question='2', title='第二个问题', heat='238 万热度')
        crawler, _driver = make_board(_board([_hot_row(), second]))
        rows = crawler.hot(target_count=10)
        assert [set(row) for row in rows] == [{'排名', '标题', '链接', '热度', '回答数', '关注数', '摘要'}] * 2, rows
        assert rows[0]['回答数'] == 275 and rows[0]['关注数'] == 134

    def test_the_link_is_the_page_a_person_can_open(self, make_board):
        """The answer hands out ``api.zhihu.com/questions/<id>``, which is not a page."""
        crawler, _driver = make_board(_board([_hot_row(question='2068641114068988689')]))
        rows = crawler.hot(target_count=5)
        assert rows[0]['链接'] == 'https://www.zhihu.com/question/2068641114068988689'

    def test_the_heat_text_becomes_a_number(self, make_board):
        crawler, _driver = make_board(_board([_hot_row(heat='398 万热度')]))
        assert crawler.hot(target_count=5)[0]['热度'] == 3980000

    def test_a_walled_session_is_named_not_answered_with_an_empty_board(self, make_board):
        import i18n

        crawler, driver = make_board(_board([_hot_row()]), wall=True)
        with pytest.raises(RuntimeError) as caught:
            crawler.hot(target_count=10)
        assert str(caught.value) == i18n.t('crawl.zhihu.hotWall')
        assert driver.fetched == [], 'a session already held at the sign-in page must not pay for the endpoint'

    def test_an_answer_that_is_not_a_board_raises(self, make_board):
        import i18n

        crawler, _driver = make_board({'status': 401, 'error': {'code': 101, 'name': 'AuthenticationError'}})
        with pytest.raises(RuntimeError) as caught:
            crawler.hot(target_count=10)
        assert i18n.t('crawl.zhihu.hotRefused', answer='401') == str(caught.value)

    def test_the_board_is_asked_for_once_and_a_resume_answers_from_the_cursor(self, make_board):
        crawler, driver = make_board(_board([_hot_row(), _hot_row(question='2')]))
        crawler.hot(target_count=200)
        assert len(driver.fetched) == 1, 'every paging parameter is ignored by the site, so a loop replays it'
        # A finished board must not be re-paid: 继续 with the whole board already done
        # returns the stored rows without opening a browser at all.
        crawler2, driver2 = make_board(_board([_hot_row()]))
        rows = crawler2.hot(target_count=30, resume={'done': 30})
        assert driver2.fetched == [], 'the resume short circuit asked the site anyway'
        assert rows == []

    def test_a_target_above_the_board_says_the_site_capped_it(self, make_board, caplog):
        crawler, _driver = make_board(_board([_hot_row(), _hot_row(question='2')]))
        with caplog.at_level('INFO'):
            rows = crawler.hot(target_count=50)
        assert len(rows) == 2
        assert i18n.t('crawl.zhihu.hotCapped', board=2) in _lines(caplog)

    def test_a_row_the_answer_cannot_identify_is_not_emitted(self, make_board):
        crawler, _driver = make_board(_board([{'target': {'title': '没有问题 id'}}, _hot_row()]))
        rows = crawler.hot(target_count=10)
        assert [row['标题'] for row in rows] == ['网民吐槽美团抽成太多'], rows
