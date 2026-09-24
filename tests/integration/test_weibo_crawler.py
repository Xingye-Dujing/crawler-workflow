"""Weibo redirect-facade tests on a fake driver — no browser needed.

s.weibo.com answers a fresh search with a passport QR frame and only a moment
later bounces the (already logged-in) session back to the feed. The crawler
must wait for that bounce instead of reading the intermediate URL as a login
wall — the exact bug that made valid cookies "expire". These tests pin the
settle behavior of ``WeiboCrawler._await_search_page``.
"""

import pytest
from selenium.common.exceptions import NoSuchElementException

import crawlers.weibo as weibo_module
from crawlers.base import Crawler
from crawlers.weibo import WeiboCrawler

pytestmark = pytest.mark.unit

PASSPORT = 'https://passport.weibo.com/sso/signin?entry=miniblog&source=s.weibo.com'
FEED = 'https://s.weibo.com/weibo?q=%E4%B8%89%E4%BA%9A&typeall=1&suball=1&Refer=g'


class FakeEl:
    def __init__(self, text=''):
        self.text = text

    def get_attribute(self, name):
        return ''


class FakeWeiboDriver:
    """One search page with a switchable final state.

    ``cards``/``no_result`` model what the DOM holds once the redirect settles;
    ``appear_after`` delays the first card sighting by N probes, which is how
    the QR→feed bounce looks from inside the poll loop. ``current_url`` starts
    at whatever the last ``get`` was handed, mirroring the real driver.
    ``total_pages`` feeds the pager text the crawl reads its depth from, and
    ``wall_from_get`` parks the browser on passport from that navigation on —
    the deep-page refusal a parallel crawl meets.
    """

    def __init__(
        self, final_url=PASSPORT, cards=True, no_result=False, appear_after=0, total_pages=50, wall_from_get=None
    ):
        self.current_url = final_url
        self._cards = cards
        self._no_result = no_result
        self._appear_after = appear_after
        self._card_probes = 0
        self._total_pages = total_pages
        self._wall_from_get = wall_from_get
        self._gets = 0
        self.visited = []

    def get(self, url):
        self._gets += 1
        self.visited.append(url)
        self.current_url = url
        self._card_probes = 0
        if self._wall_from_get is not None and self._gets >= self._wall_from_get:
            # From here on the site answers passport with no feed, however often
            # this browser asks — the session, not the window, got flagged.
            self._cards = False
            self.current_url = PASSPORT

    def find_element(self, by, selector):
        if selector == '.card-wrap':
            if not self._cards:
                raise NoSuchElementException(selector)
            self._card_probes += 1
            if self._card_probes <= self._appear_after:
                # The QR frame is still on screen; the feed has not bounced back yet.
                self.current_url = PASSPORT
                raise NoSuchElementException(selector)
            self.current_url = FEED
            return FakeEl()
        if selector == '.card-no-result':
            if self._no_result:
                return FakeEl()
            raise NoSuchElementException(selector)
        if selector == '.page-info':
            if not self._cards:
                raise NoSuchElementException(selector)
            return FakeEl(f'共{self._total_pages}页/{self._total_pages * 10}条')
        if selector in ('body', 'html'):
            # A real page's body reflects where it actually is: the QR screen
            # only shows while the browser is parked on passport.
            if 'passport' in self.current_url:
                return FakeEl('扫描二维码登录 手机号登录')
            return FakeEl('微博搜索 结果列表')
        raise NoSuchElementException(selector)

    def quit(self):
        pass


@pytest.fixture
def make_crawler(monkeypatch):
    """WeiboCrawler whose _create_driver installs a FakeWeiboDriver and whose
    poll sleeps are instant. Returns (crawler, driver)."""
    monkeypatch.setattr(weibo_module.time, 'sleep', lambda s: None)

    def _make(**driver_kwargs):
        driver = FakeWeiboDriver(**driver_kwargs)

        def fake_create(self, *a, **kw):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return WeiboCrawler(headless=True), driver

    return _make


class TestAwaitSearchPage:
    def test_qr_redirect_with_url_still_on_passport_is_not_a_wall(self, make_crawler):
        # The facade in its purest form: the URL says passport, but the feed
        # DOM is already rendered. The old code read the URL first and died.
        crawler, driver = make_crawler(final_url=PASSPORT, cards=True)
        assert crawler._await_search_page(PASSPORT) is True
        assert crawler.login_wall is False

    def test_bounce_that_takes_a_few_probes_is_awaited(self, make_crawler):
        crawler, _ = make_crawler(final_url=PASSPORT, cards=True, appear_after=3)
        assert crawler._await_search_page(PASSPORT) is True
        assert crawler.login_wall is False

    def test_persistent_passport_page_without_cards_sets_the_wall(self, make_crawler):
        crawler, _ = make_crawler(final_url=PASSPORT, cards=False)
        assert crawler._await_search_page(PASSPORT) is False
        assert crawler.login_wall is True

    def test_no_result_plate_is_an_empty_window_not_a_wall(self, make_crawler):
        crawler, _ = make_crawler(final_url=FEED, cards=False, no_result=True)
        assert crawler._await_search_page(FEED) is False
        assert crawler.login_wall is False

    def test_slow_page_that_never_shows_cards_is_a_timeout_not_a_wall(self, make_crawler):
        crawler, _ = make_crawler(final_url=FEED, cards=False)
        assert crawler._await_search_page(FEED) is False
        assert crawler.login_wall is False

    def test_navigation_happens_exactly_once_per_call(self, make_crawler):
        crawler, driver = make_crawler(final_url=FEED, cards=True)
        crawler._await_search_page(FEED)
        assert driver.visited == [FEED]


class TestPagingWalk:
    """How deep ``_scrape_single_search`` walks a keyword feed.

    The old crawler capped the walk at five pages however deep the pager said
    and however empty the target still was — a "共50页" feed quit at page 5 with
    no line explaining why. The walk now answers to two things only: the target
    (stop when full) and the wall (stop when refused, keeping every row).

    ``_harvest`` is replaced with one-row-per-page emissions: the card DOM is
    another test's subject, and here it is the *visited URLs* that carry the
    contract.
    """

    @pytest.fixture
    def make_walker(self, make_crawler, monkeypatch):
        def _make(target, **driver_kwargs):
            crawler, driver = make_crawler(cards=True, **driver_kwargs)
            monkeypatch.setattr(Crawler, '_polite_pause', staticmethod(lambda *a: None))
            page_counter = {'n': 0}

            def harvest(_target):
                page_counter['n'] += 1
                item = {'正文': f'p{page_counter["n"]}'}
                crawler.emit(item)
                return [item]

            monkeypatch.setattr(crawler, '_harvest', harvest)
            return crawler, driver

        return _make

    @staticmethod
    def _paged_urls(driver):
        return [u for u in driver.visited if 'page=' in u]

    def test_a_deep_pager_is_walked_to_its_own_end_not_to_a_hard_cap(self, make_walker):
        crawler, driver = make_walker(WeiboCrawler.DEFAULT_TARGET, total_pages=50)
        crawler._scrape_single_search(FEED, WeiboCrawler.DEFAULT_TARGET)
        assert self._paged_urls(driver) == [f'{FEED}&page={n}' for n in range(2, 51)]
        assert crawler.collected() == 50

    def test_the_walk_stops_the_moment_the_target_is_full(self, make_walker):
        crawler, driver = make_walker(4, total_pages=50)
        crawler._scrape_single_search(FEED, 4)
        assert crawler.collected() == 4
        assert self._paged_urls(driver) == [f'{FEED}&page={n}' for n in (2, 3, 4)]

    def test_a_wall_met_while_paging_keeps_the_rows_and_stops_the_walk(self, make_walker):
        # The parallel-session refusal: pages 2 answers, page 3 parks on passport.
        crawler, driver = make_walker(WeiboCrawler.DEFAULT_TARGET, total_pages=50, wall_from_get=3)
        scraped = crawler._scrape_single_search(FEED, WeiboCrawler.DEFAULT_TARGET)
        assert crawler.login_wall is True
        assert len(scraped) == 2, 'the rows paid for before the wall must still be handed back'
        assert self._paged_urls(driver) == [f'{FEED}&page={n}' for n in (2, 3)], (
            'the walk may pay for the request that discovers the wall, never one past it'
        )
