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


class _TextElement:
    """The one shape :meth:`Crawler._node_text` falls back to: an element with text."""

    def __init__(self, text):
        self.text = text


class SlowDriver:
    """A browser whose pages never finish loading, which is a real state on xhs.

    ``get`` raises the driver's own words and ``find_element`` keeps answering the way a
    building document does (``no such element``, not a crash), so nothing here pretends
    the page arrived. ``body_text`` is the refusal xhs serves INSTEAD of a slow grid:
    the search URL stays and the page becomes 安全验证 — measured 2026-09-25 on a
    session the site had stopped trusting mid-run.
    """

    def __init__(self, url=SEARCH, get_error=True, body_text=''):
        self.current_url = url
        self.visited = []
        self.get_error = get_error
        self.body_text = body_text

    def get(self, url):
        self.visited.append(url)
        # A renderer timeout means the document never swapped: the address bar keeps
        # showing whatever was there before. Re-modelling that is the whole point of
        # the stuck-on-new-tab case below — the real measured browser stayed on
        # ``chrome://new-tab-page`` while ``get`` was already throwing.
        if not self.get_error:
            self.current_url = url
        if self.get_error:
            raise TimeoutException(RENDERER_TIMEOUT)

    def find_element(self, by, selector):
        if selector == 'body' and self.body_text:
            return _TextElement(self.body_text)
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        # A real page answers innerText here, and a refusal page has to be able to hand
        # over ITS text: ``_node_text`` only falls back to ``element.text`` when the
        # script throws, so a script that returns nothing would show the wall
        # classifier a blank page and hide the very refusal this fake is built to prove.
        for arg in args:
            text = getattr(arg, 'text', None)
            if text:
                return text
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


class TestRiskControlStopsTheCrawl:
    """xhs walls a replayed session with a 风控 page, not a login redirect (docs red line).

    That refusal set ``risk_blocked`` but the search gate only tested ``check_login_wall``
    (verdict == 'login'), so the crawl fell through, scrolled a zero-card grid, and filed an
    empty table behind a ``page_timeout`` line — a silent "found nothing" that read as a
    finished crawl for a keyword that plainly has notes. The gate now stops on any refusal,
    the same rule zhihu and douyin already enforce.
    """

    def test_a_risk_control_answer_stops_the_walk_and_names_itself(self, make_crawler, caplog):
        crawler, _driver = make_crawler(body_text='安全验证，请完成验证后继续浏览')
        with caplog.at_level('INFO'):
            rows = crawler.search('三亚', target_count=3)
        assert rows == [], 'a refused page has no notes to file'
        assert crawler.risk_blocked is True, 'the refusal must be named as risk control, not swallowed'
        assert crawler.login_wall is False, 'a flagged session is not a dead cookie — the fix is to wait'
        messages = [r.getMessage() for r in caplog.records]
        assert t('crawl.xhs.page_timeout') not in messages, (
            'a named refusal must return at the gate, not fall through to the timeout-and-scroll '
            'path that produced the silent empty table'
        )

    def test_a_browser_that_never_left_its_own_page_is_a_named_refusal(self, make_crawler, caplog):
        """The 2026-09-25 visible-window shape: ``get`` threw mid-navigation and the
        address bar still reads chrome://new-tab-page — the site was never reached, so
        'ok' there would file an empty grid as a result. The internal page now classifies
        as a refusal the search gate stops on.
        """
        crawler, _driver = make_crawler(url='chrome://new-tab-page/')
        crawler.search('三亚', target_count=3)
        assert crawler.risk_blocked is True, 'a browser parked on its own page never arrived'
        assert crawler.login_wall is False, 'nothing asked for a login; the user must not be sent to re-save a cookie'


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
