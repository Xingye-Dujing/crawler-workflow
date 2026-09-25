"""Real Chrome: the fourth verdict, and what the patience budget must not be paid for (#135).

The offline tiers can prove the crawler branches on ``documentURI``; only a browser proves
``documentURI`` is where the truth lives. Both halves of that claim are asserted here, on the
measured shapes (``backend/test_arrival_evidence.py``): a refused navigation commits a document
that calls itself ``chrome-error://chromewebdata`` and prints ``net::ERR_…``, while
``driver.current_url`` goes on reporting the address that was asked for.

The second test is the expensive one to skip: with ``Config.PAGE_WAIT_TIMEOUT`` at 300 seconds,
a wait that could not see a provable death would cost five minutes per row of a per-page crawl.
That is timed here with real sleeps, because "it returns early" is exactly the kind of promise a
monkeypatched clock cannot keep.

Local navigation only — no site is contacted and nothing is written to the server's data dir.
"""

import time

import pytest

from config import Config
from crawlers import get_crawler
from crawlers.base import CrawlerStopped

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

#: A name no resolver on earth has an answer for (RFC 6761's ``.invalid`` TLD).
DEAD_HOST = 'http://no-host-for-arrival-evidence.invalid/'
#: The whole budget, plus a browser's own DNS failure. A wait that only notices the refused
#: document at its deadline would blow through the tight bound below.
FAST_BUDGET = 30.0


def _launch():
    """A crawler browser, or a skip: this tier is not applicable without Chrome."""
    try:
        return get_crawler('bilibili', headless=True, use_profile=False)
    except Exception as e:
        pytest.skip(f'Chrome/chromedriver unavailable: {e}')


@pytest.fixture(scope='class')
def browser_crawler():
    """**One** browser for the class.

    This tier already runs several tests that each buy a Chrome, and the machine at the far
    end of them answers with ``SessionNotCreatedException`` — measured, two different
    neighbours of this file failed that way once six more sessions were added. The
    assertions below are about one navigation each, so they share a browser and reset the
    latches between tests instead of buying six.
    """
    crawler = _launch()
    try:
        yield crawler
    finally:
        crawler.close()


@pytest.fixture(autouse=True)
def clean_slate(browser_crawler):
    """The three wall latches are one-way by design (a crawl must not walk past one), so a
    shared browser would otherwise carry the previous test's refusal into the next one."""
    browser_crawler.login_wall = False
    browser_crawler.risk_blocked = False
    browser_crawler.unreachable = False
    browser_crawler.pending_waits = 0
    browser_crawler._abort = None


@pytest.fixture
def local_page(tmp_path):
    """A page this machine really serves, for the control side of every assertion.

    ``file:///`` (a directory) is not that: measured here, Chrome answers it with its own
    error document, which would make the control test prove the opposite of what it means.
    """
    page = tmp_path / 'arrival-control.html'
    page.write_text('<html><head><title>local ok</title></head><body>正文在这里</body></html>', encoding='utf-8')
    return page.as_uri()


class TestTheFourthVerdictOnARealBrowser:
    def test_a_refused_navigation_is_read_from_the_document_not_the_address_bar(self, browser_crawler):
        crawler = browser_crawler
        crawler.open(DEAD_HOST)
        assert crawler.unreachable is True, 'the browser wrote this page itself and nothing said so'
        # The two flags a refusal must NOT set: both of them end in 请重新保存 Cookie, and the
        # site never saw this session at all.
        assert (crawler.login_wall, crawler.risk_blocked) == (False, False)
        assert crawler.verdict() == 'unreachable'

    def test_the_address_bar_is_the_trap_this_exists_for(self, browser_crawler):
        """If ``current_url`` reported the error page, ``documentURI`` would be decoration.
        Measured the opposite, and the assertion is what keeps the extra round trip honest."""
        crawler = browser_crawler
        crawler.open(DEAD_HOST)
        assert crawler.driver.current_url == DEAD_HOST, 'the address bar moved, so the design changed'
        document_uri = crawler._document_uri()
        assert document_uri.startswith('chrome-error://'), document_uri

    def test_the_machine_names_its_own_token(self, browser_crawler):
        """The console quotes what the page printed, and prints nothing it did not read — so
        the token has to be findable in a real Chrome's error body, not just in a fixture."""
        crawler = browser_crawler
        crawler.open(DEAD_HOST)
        assert 'ERR_' in crawler._error_detail(), crawler._body_text(limit=2000)

    def test_a_page_that_arrived_is_not_a_refusal(self, browser_crawler, local_page):
        crawler = browser_crawler
        crawler.open(local_page)
        assert crawler.verdict() == 'ok'
        assert crawler.unreachable is False

    def test_a_provable_death_is_not_waited_out(self, browser_crawler):
        """The real-clock proof: patience is for a page that may still be coming, and this
        one is not. Bounded far below ``PAGE_WAIT_TIMEOUT`` and far above one navigation."""
        crawler = browser_crawler
        crawler.open(DEAD_HOST)
        started = time.monotonic()
        outcome = crawler.wait_for_first_content(has_content=lambda: [], timeout=Config.PAGE_WAIT_TIMEOUT)
        spent = time.monotonic() - started
        assert outcome['arrived'] is False
        assert outcome['verdict'] == 'unreachable'
        assert spent < FAST_BUDGET, f'a provable death cost {spent:.1f}s of a {Config.PAGE_WAIT_TIMEOUT}s budget'

    def test_the_stopped_run_leaves_the_patient_wait_immediately(self, browser_crawler, local_page):
        """300 seconds of waiting is survivable only because 停止 reaches inside it."""
        crawler = browser_crawler
        crawler.open(local_page)  # a document, so the wait is genuinely about to be patient
        crawler._abort = lambda: True
        started = time.monotonic()
        with pytest.raises(CrawlerStopped):
            crawler.wait_for_first_content(has_content=lambda: [], timeout=Config.PAGE_WAIT_TIMEOUT)
        assert time.monotonic() - started < 5.0
