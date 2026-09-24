"""Xiaohongshu's navigations, and what a driver that never settles has to do.

Measured failure, twice in one hour on the same tier and the same file
(``tests/live_site/test_live_xiaohongshu.py``): the crawl came back red with
``TimeoutException: Timed out receiving message from renderer: -0.001`` raised out of a
bare ``self.driver.get(url)`` — the search page's first navigation, and once the note
page's. The message is the point: the document was still building, which is the exact
state this crawler already answers honestly with ``crawl.xhs.page_timeout`` (keep polling,
and zero cards is a legitimate outcome). It never got the chance, because the navigation
itself threw and took the node down with a driver stack trace.

The fix is to enter the page the way every other platform does — through
``Crawler.open``, which survives the timeout, dismisses the site's first-run dialog and
records the request. These tests hold that line with a fake driver, including the two
things ``open`` must not turn into: a slow page is not a wall, and a lost note is not a
failed crawl.
"""

import pytest
from selenium.common.exceptions import NoSuchElementException, TimeoutException

import crawlers.base as base_module
from crawlers.base import Crawler
from crawlers.xiaohongshu import XiaohongshuCrawler as Xhs
from i18n import t

pytestmark = pytest.mark.unit

SEARCH = 'https://www.xiaohongshu.com/search_result?keyword=%E4%B8%89%E4%BA%9A&type=51'
NOTE = 'https://www.xiaohongshu.com/explore/abcdef?xsec_token=xyz'
RENDERER_TIMEOUT = 'timeout: Timed out receiving message from renderer: -0.001'


class SlowDriver:
    """A browser whose pages never finish loading, which is a real state on xhs.

    ``get`` raises the driver's own words and ``find_element`` keeps answering the way a
    building document does (``no such element``, not a crash), so nothing here pretends
    the page arrived.
    """

    def __init__(self, url=SEARCH, get_error=True):
        self.current_url = url
        self.visited = []
        self.get_error = get_error

    def get(self, url):
        self.visited.append(url)
        self.current_url = url
        if self.get_error:
            raise TimeoutException(RENDERER_TIMEOUT)

    def find_element(self, by, selector):
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        return ''

    def quit(self):
        pass


@pytest.fixture
def make_crawler(monkeypatch):
    """Build a real :class:`Xhs` over a fake driver, with every wait instant."""
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(**driver_attrs):
        driver = SlowDriver(**driver_attrs)

        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        crawler = Xhs(headless=True)
        return crawler, driver

    return _make


class TestSearchNavigation:
    def test_a_renderer_timeout_is_the_pages_own_answer_not_a_crash(self, make_crawler, caplog):
        crawler, _driver = make_crawler()
        with caplog.at_level('INFO'):
            rows = crawler.search('三亚', target_count=3)
        assert rows == [], 'a page that never settled cannot have produced notes'
        assert t('crawl.xhs.page_timeout') in [r.getMessage() for r in caplog.records], (
            'the crawl must say the page did not answer, in its own words'
        )

    def test_the_navigation_that_threw_is_still_paid_for(self, make_crawler):
        # ``requests`` is the cost ledger a mode's promise is tested against, and the
        # request reached the site — dropping it here would let a crawl look cheaper
        # than it was.
        crawler, driver = make_crawler()
        crawler.search('三亚', target_count=1)
        assert crawler.requests == driver.visited
        assert crawler.requests and '/search_result?keyword=' in crawler.requests[0]

    def test_a_slow_page_is_not_reported_as_a_dead_cookie(self, make_crawler):
        # The whole reason ``open`` judges only a persisted refusal: a search grid that
        # has not rendered is an empty document, not a login form, and the second verdict
        # would send the user off to re-save a session that works.
        crawler, _driver = make_crawler()
        crawler.search('三亚', target_count=1)
        assert crawler.login_wall is False


class TestNoteNavigation:
    def test_a_note_that_never_arrives_costs_its_row_and_not_the_crawl(self, make_crawler, monkeypatch):
        crawler, driver = make_crawler(get_error=False)

        class _Expired:
            def __init__(self, _driver, _timeout):
                pass

            def until(self, _condition):
                raise TimeoutException(RENDERER_TIMEOUT)

        monkeypatch.setattr('crawlers.xiaohongshu.WebDriverWait', _Expired)
        assert crawler._scrape_note(NOTE) is None
        assert crawler.requests == [NOTE], 'the detail visit is one of the crawl requests'
