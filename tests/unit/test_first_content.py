"""Waiting for one page's first content, and what counts as proof that it will not come.

Three facts the rest of this suite keeps needing, all of them measured with
``backend/test_arrival_evidence.py`` on Chrome 148:

* a navigation the browser refuses leaves a **committed document** that calls itself
  ``chrome-error://chromewebdata`` and names its cause (``ERR_NAME_NOT_RESOLVED`` and
  friends), while ``driver.current_url`` goes on reporting the address that was asked
  for — so the only reading that can tell "refused" from "answered with nothing" is the
  document's own;
* a navigation that times out in the renderer leaves the **previous** document in place
  (same ``documentURI``, ``readyState`` complete, the old title), which is why a patient
  wait must not read a stale page as an arrival, and why nothing here treats
  ``current_url`` as fresh evidence;
* ``page_load_timeout`` bounds only the load *event*, so a slow document keeps building
  after it. That is the gap :attr:`Config.PAGE_WAIT_TIMEOUT` is for.

The second half of the file is the patience itself: it has to end on evidence, end on
停止, and refuse to be bought a third time.
"""

import pytest
from test_crawler_base import bare

import crawlers.base as base_module
from config import Config
from crawlers.base import Crawler, CrawlerStopped, PageNotArrivedError
from crawlers.engine.wall import classify

pytestmark = pytest.mark.unit

ASKED = 'https://www.douyin.com/search/%E4%B8%89%E4%BA%9A'
REFUSED = 'chrome-error://chromewebdata/'
DNS_PAGE = '无法访问此网站\n\n找不到该域名的服务器 IP 地址\n\nERR_NAME_NOT_RESOLVED'
LOGIN_PAGE = '扫描二维码登录 手机号登录'
CONTENT = '三亚五日游攻略 人均两千'


class Element:
    def __init__(self, text):
        self.text = text


class Browser:
    """A page that can be set to any of the measured arrival shapes, and that counts being read.

    ``execute_script`` answers only the ``documentURI`` question and refuses the node-text
    one, which is how :meth:`Crawler._node_text` reaches ``element.text`` — so a test that
    changes *what the document says* changes every reader at once, exactly as a real
    browser does.
    """

    def __init__(self, url=ASKED, document_uri='', body=''):
        self.url = url
        self.document_uri = document_uri
        self.body = body
        self.reads = 0
        self.visited = []

    @property
    def current_url(self):
        return self.url

    def get(self, url):
        self.visited.append(url)

    def find_element(self, by, selector):
        self.reads += 1
        return Element(self.body)

    def execute_script(self, script, *args):
        if 'documentURI' in script:
            return self.document_uri
        raise RuntimeError('this fake answers no node scripts')

    def quit(self):
        pass


@pytest.fixture
def no_sleep(monkeypatch):
    """Make the clocks free, so a 300-second budget costs no wall-clock seconds here.

    The same swap the arrival tests in ``test_crawler_base`` make, for the same reason:
    what is under test is the *decision*, not how long a real page takes.
    """
    monkeypatch.setattr(base_module.time, 'sleep', lambda _s: None)


def _crawler(browser, **attrs):
    return bare(browser, domain='www.douyin.com', login_url='https://www.douyin.com/', **attrs)


class TestReadingTheDocument:
    def test_a_refused_navigation_latches_its_own_flag_and_neither_other(self):
        """The whole point of the fourth word: six call sites read ``risk_blocked`` as
        "re-save your cookie", and a DNS failure says nothing about a cookie."""
        crawler = _crawler(Browser(document_uri=REFUSED, body=DNS_PAGE))
        crawler.open(ASKED)
        assert (crawler.unreachable, crawler.login_wall, crawler.risk_blocked) == (True, False, False)

    def test_the_asked_for_address_is_still_what_a_refusal_names(self):
        """The console has to quote the address the user meant, because the document's own
        URI says only 'error' and the browser keeps the request in the address bar."""
        crawler = _crawler(Browser(document_uri=REFUSED, body=DNS_PAGE))
        crawler.open(ASKED)
        assert ASKED in crawler.requests

    def test_a_refusal_is_answered_on_the_first_reading(self, no_sleep):
        """The settle window guards against a redirect *flash*. A committed error document
        cannot change without a new navigation, so paying five readings for it would tax
        every row of a per-page crawl to re-learn what the page already said."""
        crawler = _crawler(Browser(document_uri=REFUSED, body=DNS_PAGE))
        crawler.open(ASKED)
        # One reading to judge the page, one to read the token out of it for the message —
        # and no more. A flash-shaped refusal would have cost Crawler.WALL_PROOFS.
        assert crawler.driver.reads < Crawler.WALL_PROOFS, f'a provable death was re-read {crawler.driver.reads} times'
        assert crawler.unreachable is True

    def test_a_login_page_is_still_proved_before_it_is_believed(self, no_sleep):
        """The other side of that fast exit: widening it to every non-'ok' answer would
        make weibo's passport flash a permanent wall again."""
        crawler = _crawler(Browser(url='https://passport.weibo.com/sso/signin', body=LOGIN_PAGE))
        crawler.open('https://s.weibo.com/weibo?q=x')
        assert crawler.driver.reads >= Crawler.WALL_PROOFS
        assert crawler.login_wall is True

    def test_a_browser_that_cannot_run_scripts_reports_no_refusal(self):
        """No evidence is 'ok', never 'unreachable': a test double without scripting and a
        session mid-teardown must not abort a crawl that is otherwise producing rows."""
        browser = Browser(document_uri=REFUSED, body=DNS_PAGE)

        def no_scripts(script, *args):
            raise RuntimeError('session is gone')

        browser.execute_script = no_scripts
        crawler = _crawler(browser)
        assert crawler.verdict() == 'ok'
        assert classify(browser.current_url, DNS_PAGE, document_uri='') == 'ok'

    def test_a_normal_page_stays_normal(self):
        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT))
        crawler.open(ASKED)
        assert (crawler.unreachable, crawler.login_wall, crawler.risk_blocked) == (False, False, False)

    def test_the_token_is_named_when_the_page_names_it(self):
        crawler = _crawler(Browser(document_uri=REFUSED, body=DNS_PAGE))
        crawler.verdict()
        assert 'ERR_NAME_NOT_RESOLVED' in crawler._error_detail()

    def test_an_unreadable_token_is_left_out_rather_than_invented(self):
        """A fabricated ``ERR_UNKNOWN`` would be a claim about a fact nobody observed."""
        crawler = _crawler(Browser(document_uri=REFUSED, body='无法访问此网站'))
        crawler.verdict()
        assert crawler._error_detail() == ''


class TestWaitingForTheFirstContent:
    def test_a_page_that_arrives_costs_one_look_and_clears_the_streak(self, no_sleep):
        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT))
        crawler.pending_waits = 1
        outcome = crawler.wait_for_first_content()
        assert outcome['arrived'] is True
        assert crawler.pending_waits == 0

    def test_the_default_probe_needs_text_the_site_wrote(self):
        """The browser's own page is full of text, so 'body is non-empty' cannot be the
        test — that would report a network failure as a page that loaded."""
        crawler = _crawler(Browser(document_uri=REFUSED, body=DNS_PAGE))
        assert crawler._rendered_by_the_site() is False
        crawler = _crawler(Browser(document_uri=ASKED, body='   \n  '))
        assert crawler._rendered_by_the_site() is False

    def test_the_caller_asks_its_own_question(self, no_sleep):
        """Douyin's list mounts as 16 skeleton rows with no anchor: 'is there text' is
        true long before 'is there a card', and the platform owns that difference."""
        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT))
        asked = []

        def no_cards():
            asked.append(1)
            return []

        outcome = crawler.wait_for_first_content(has_content=no_cards, timeout=2)
        assert outcome['arrived'] is False
        assert len(asked) >= 2, "the caller's probe was not what drove the wait"

    def test_a_wall_ends_the_wait_early(self, no_sleep):
        """Waiting out a refusal costs the user the budget and changes nothing, and the
        verdict is an answer the caller can act on."""
        crawler = _crawler(Browser(document_uri='https://www.douyin.com/x', body=LOGIN_PAGE))
        outcome = crawler.wait_for_first_content(has_content=lambda: [], timeout=300)
        assert outcome['arrived'] is False
        assert outcome['verdict'] == 'login'

    def test_a_refused_document_ends_the_wait_at_once(self, no_sleep):
        """The circuit breaker's cheapest form: this is provable, so the patience budget
        is never paid for it. Measured against the number of looks rather than the clock,
        because the clock is free in this file."""
        looks = []
        crawler = _crawler(Browser(document_uri=REFUSED, body=DNS_PAGE))

        def no_cards():
            looks.append(1)
            return []

        outcome = crawler.wait_for_first_content(has_content=no_cards, timeout=300)
        assert outcome['verdict'] == 'unreachable'
        assert len(looks) == 1, f'a provable death was waited out for {len(looks)} looks'

    def test_the_platform_can_say_stop_earlier_than_the_engine_hears_it(self, no_sleep):
        """Douyin's 验证码中间页 speaks in the tab title, which the shared classifier does
        not read. Without the callback the patient wait would sit out its budget on it."""
        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT))
        outcome = crawler.wait_for_first_content(has_content=lambda: [], stalled=lambda: True, timeout=300)
        assert outcome['arrived'] is False
        # The verdict is still the engine's own word, never a word invented for the caller.
        assert outcome['verdict'] == 'wall'

    def test_a_stopped_run_leaves_the_wait_immediately(self, no_sleep):
        """With a 300 s budget, a wait that ignored 停止 would be the longest thing in the
        program, and 停止 is the user's only way out of it."""
        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT), _abort=lambda: True)
        with pytest.raises(CrawlerStopped):
            crawler.wait_for_first_content(has_content=lambda: [], timeout=Config.PAGE_WAIT_TIMEOUT)

    def test_a_probe_that_cannot_answer_is_not_a_page_that_arrived(self, no_sleep):
        def broken():
            raise RuntimeError('the site renamed the card class')

        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT))
        outcome = crawler.wait_for_first_content(has_content=broken, timeout=1)
        assert outcome['arrived'] is False

    def test_the_budget_is_the_configured_one(self, no_sleep, monkeypatch):
        """Pinned by tick count rather than by a clock, because the sleeps are free here:
        what is being held is the promise that the configured number is the number, not a
        per-platform figure that quietly decides a slow network is a refused one."""
        looks = []

        def no_cards():
            looks.append(1)
            return []

        monkeypatch.setattr(Config, 'PAGE_WAIT_TIMEOUT', 7)
        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT))
        outcome = crawler.wait_for_first_content(has_content=no_cards)
        assert outcome['arrived'] is False
        assert len(looks) >= 7, f'the wait gave up after {len(looks)} looks at a 7-second budget'

    def test_an_expiry_is_counted_and_a_third_one_is_not_bought(self, no_sleep):
        """The breaker that makes the patience survivable: a crawl that opens a page per
        row would otherwise spend 行数 × 300 s discovering the network is down."""
        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT))
        first = crawler.wait_for_first_content(has_content=lambda: [], timeout=1)
        second = crawler.wait_for_first_content(has_content=lambda: [], timeout=1)
        assert (first['gave_up'], second['gave_up']) == (1, 2)
        third = crawler.wait_for_first_content(has_content=lambda: [], timeout=300)
        assert third['arrived'] is False
        assert third['waited'] == 0.0
        assert third['verdict'] == 'breaker'
        assert third['gave_up'] == 2

    def test_a_page_that_arrives_resets_the_breaker(self, no_sleep):
        crawler = _crawler(Browser(document_uri=ASKED, body=CONTENT))
        crawler.pending_waits = crawler.MAX_PENDING_WAITS
        assert crawler.wait_for_first_content(has_content=lambda: ['card'])['arrived'] is True
        assert crawler.pending_waits == 0


class TestTheRefusalCarriesItsNumbers:
    def test_the_exception_keeps_what_only_the_wait_knows(self):
        """The executor's sentence has to say how long it waited and whether this is the
        second page it failed on — neither of which the platform's own wording can carry."""
        error = PageNotArrivedError('页面没有内容', waited=301.4, verdict='ok', gave_up=2)
        assert (error.waited, error.verdict, error.gave_up) == (301.4, 'ok', 2)
        assert str(error) == '页面没有内容'

    def test_a_bare_raise_still_answers(self):
        error = PageNotArrivedError('没有内容')
        assert (error.waited, error.verdict, error.gave_up) == (0.0, '', 0)

    def test_it_is_an_ordinary_error_so_the_node_runner_settles_it(self):
        """Deliberately not a ``CrawlerStopped``: a page that did not arrive is a refusal
        to be reported (partial where there are rows, failed where there are none), not a
        press of the user's button."""
        assert issubclass(PageNotArrivedError, Exception)
        assert not issubclass(PageNotArrivedError, CrawlerStopped)
