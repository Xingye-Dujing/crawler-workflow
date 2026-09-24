"""The Crawler base: cookie planting, navigation, and the three page verdicts.

None of this had unit coverage before: the cookie loop, :meth:`Crawler.open` and
the login/blocked classification were only ever exercised by a real browser. They
are now the shared plumbing under nine platforms, so each branch is pinned here
against a fake driver — including the two confusions that each cost a debugging
session: a risk-control page read as a dead cookie, and a profile request the
router dropped at the site root read as "this account has no posts".
"""

import json
import re
from pathlib import Path

import pytest

import crawlers.base as base_module
from crawlers.base import Crawler, as_index

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# A cookie for the parent domain (accepted anywhere below it), one pinned to a
# sibling host (only that host will take it), and one the sanitizer drops.
PARENT_COOKIE = {'name': 'sid', 'value': 'x', 'domain': '.douyin.com', 'path': '/', 'secure': True}
SIBLING_COOKIE = {'name': 'bound', 'value': 'y', 'domain': 'www.iesdouyin.com', 'path': '/'}
NAMELESS_COOKIE = {'value': 'no name'}


class PlantDriver:
    """A browser that accepts a cookie only when the open page's host fits it."""

    def __init__(self, start='https://www.douyin.com/'):
        self.planted = []
        self.visited = []
        self._url = start
        self.url_error = False
        self.failing_hosts = ()
        self.timeout_hosts = ()

    @property
    def current_url(self):
        # A session that died answers nothing at all, which is a state of its own.
        if self.url_error:
            raise RuntimeError('session died')
        return self._url

    @current_url.setter
    def current_url(self, value):
        self._url = value

    def get(self, url):
        self.visited.append(url)
        host = url.split('//')[1].split('/')[0]
        if host in self.failing_hosts:
            raise RuntimeError('connection reset')
        self.current_url = url

    def add_cookie(self, payload):
        host = self.current_url.split('//')[1].split('/')[0]
        domain = str(payload.get('domain') or host).lstrip('.')
        if not (host == domain or host.endswith('.' + domain)):
            raise RuntimeError('invalid cookie domain')
        self.planted.append(payload['name'])

    def find_element(self, by, selector):
        raise RuntimeError('no body element')

    def execute_script(self, script, *args):
        return ''

    def quit(self):
        pass


class Probe(Crawler):
    """A concrete platform with no behaviour of its own.

    ``Crawler`` is abstract on purpose, so the only honest way to test its
    plumbing is a subclass that adds nothing but the two required methods.
    """

    def search(self, keyword, **kwargs):
        return []

    def get_detail(self, url):
        return None


def bare(driver, **attrs):
    """A crawler with no browser: the plumbing needs no Selenium to be tested.

    ``Crawler.__init__`` buys a real Chrome, so the instance is built with ``__new__``
    and its state written out here. That means **this list has to be kept in step
    with ``__init__``** every time the base class gains an attribute (it drifted once,
    when ``requests`` arrived).
    """
    crawler = Probe.__new__(Probe)
    crawler.driver = driver
    crawler.headless = True
    crawler.cookie_path = None
    crawler.domain = 'www.douyin.com'
    crawler.cookie_domains = ('douyin.com', 'www.iesdouyin.com')
    crawler.login_url = 'https://www.douyin.com/'
    crawler.prompts = ()
    crawler.login_wall = False
    crawler.risk_blocked = False
    crawler.cookies_loaded = 0
    crawler.requests = []
    crawler._collected = []
    crawler._cursor = {}
    crawler._sink = None
    crawler._cursor_sink = None
    for key, value in attrs.items():
        setattr(crawler, key, value)
    return crawler


@pytest.fixture
def write_cookies(tmp_path):
    def _write(entries, name='douyin'):
        path = tmp_path / f'{name}_cookies.json'
        path.write_text(json.dumps(entries), encoding='utf-8')
        return str(path)

    return _write


class TestCookiePlanting:
    def test_a_host_that_takes_everything_ends_the_loop(self, write_cookies):
        """Each extra host is a full page load — measured ~2.3 s apiece on douyin,
        one of which was a pure redirect — so it is visited only when a cookie
        actually needs it."""
        driver = PlantDriver()
        crawler = bare(driver, cookie_path=write_cookies([PARENT_COOKIE]), cookie_domains=('douyin.com',))
        crawler._load_cookies()
        assert driver.visited == ['https://www.douyin.com']
        assert driver.planted == ['sid']
        assert crawler.cookies_loaded == 1

    def test_only_the_refused_cookies_send_it_on_to_the_next_host(self, write_cookies):
        driver = PlantDriver()
        crawler = bare(driver, cookie_path=write_cookies([PARENT_COOKIE, SIBLING_COOKIE]))
        crawler._load_cookies()
        # The parent-domain cookie is taken by the first host; the sibling-pinned
        # one raises there and is what earns the second (and third) visit.
        assert driver.visited[0] == 'https://www.douyin.com'
        assert 'https://www.iesdouyin.com' in driver.visited
        assert sorted(driver.planted) == ['bound', 'sid']

    def test_a_nameless_entry_is_dropped_without_a_visit_of_its_own(self, write_cookies):
        driver = PlantDriver()
        crawler = bare(driver, cookie_path=write_cookies([PARENT_COOKIE, NAMELESS_COOKIE]), cookie_domains=())
        crawler._load_cookies()
        assert driver.planted == ['sid']
        assert len(driver.visited) == 1

    @pytest.mark.parametrize('payload', ['{}', '[]', 'not json at all', ''])
    def test_an_unusable_file_is_not_an_error(self, write_cookies, tmp_path, payload):
        path = tmp_path / 'odd.json'
        path.write_text(payload, encoding='utf-8')
        crawler = bare(PlantDriver(), cookie_path=str(path))
        crawler._load_cookies()
        assert crawler.cookies_loaded == 0

    def test_a_missing_file_costs_no_browser_traffic(self):
        driver = PlantDriver()
        crawler = bare(driver, cookie_path='no-such-file.json')
        crawler._load_cookies()
        assert driver.visited == []

    def test_a_host_that_fails_to_load_does_not_abort_the_others(self, write_cookies):
        driver = PlantDriver()
        driver.failing_hosts = ('www.iesdouyin.com',)
        crawler = bare(driver, cookie_path=write_cookies([PARENT_COOKIE, SIBLING_COOKIE]))
        crawler._load_cookies()
        assert 'sid' in driver.planted


class TestNavigation:
    def test_every_navigation_is_ledgered_in_order(self):
        """``requests`` is what makes a crawl's cost model testable at all: a mode
        that promises "one request per page" can only be held to it by counting, and
        a timeout still reached the site — so it is recorded before the driver is
        asked, not after it answers."""
        crawler = bare(PlantDriver())
        assert crawler.open('https://www.douyin.com/') is True
        assert crawler.open('https://www.douyin.com/hot') is True
        assert crawler.requests == ['https://www.douyin.com/', 'https://www.douyin.com/hot']

        driver = PlantDriver()

        def slow(url):
            raise RuntimeError('Timed out receiving message from renderer')

        driver.get = slow
        walled = bare(driver)
        assert walled.open('https://www.douyin.com/') is False
        assert walled.requests == ['https://www.douyin.com/'], 'a slow navigation still happened'

    def test_a_renderer_timeout_is_survived_and_reported(self):
        """Douyin's root never fires ``load`` inside the timeout (measured ~40 s);
        the document still builds, so the crawl must continue and the platform's
        own poll decides readiness. ``False`` is the signal, not an exception."""
        driver = PlantDriver()

        def slow(url):
            driver.visited.append(url)
            raise RuntimeError('Timed out receiving message from renderer')

        driver.get = slow
        crawler = bare(driver)
        assert crawler.open('https://www.douyin.com/') is False
        assert driver.visited == ['https://www.douyin.com/']

    def test_the_bounce_check_uses_the_requested_url_not_the_landing_one(self):
        """The bounce verdict needs both sides; if ``open`` passed only the current
        URL the comparison would always be "same page, no bounce"."""
        seen = {}
        crawler = bare(PlantDriver(start='https://www.instagram.com/'))
        # Spied on ``verdict`` rather than ``check_intercept`` because that is where the
        # comparison happens now: ``open`` re-reads a suspected wall before recording it,
        # so a page that is fine never reaches the latching call at all.
        crawler.verdict = lambda request_url='': seen.update(request=request_url) or 'ok'
        crawler.open('https://www.instagram.com/nasa/')
        assert seen == {'request': 'https://www.instagram.com/nasa/'}

    def test_a_bounce_to_the_site_root_is_a_refusal_not_an_empty_account(self):
        """Instagram answers a challenged profile request with ``/#`` plus a login
        form, and no URL marker the old detector knew."""
        driver = PlantDriver(start='https://www.instagram.com/')
        crawler = bare(driver, domain='www.instagram.com', login_url='https://www.instagram.com/')
        crawler._body_text = lambda *a, **k: '手机号、账号或邮箱 密码 登录 忘记密码了？ 创建新账户'
        verdict = crawler.check_intercept(
            'https://www.instagram.com/nasa/', request_url='https://www.instagram.com/nasa/'
        )
        assert verdict == 'login'
        assert crawler.login_wall is True

    def test_risk_control_is_recorded_apart_from_a_dead_cookie(self):
        """A headless zhihu search answered by code 40362 is a real outcome of that
        mode; calling it a dead cookie would send the user to re-save a good one."""
        driver = PlantDriver(start='https://www.zhihu.com/search?q=x')
        crawler = bare(driver, domain='www.zhihu.com')
        crawler._body_text = lambda *a, **k: '40362 当前请求存在异常'
        assert crawler.check_intercept('https://www.zhihu.com/search?q=x') == 'blocked'
        assert crawler.risk_blocked is True
        assert crawler.login_wall is False

    def test_a_healthy_page_sets_neither_flag(self):
        driver = PlantDriver(start='https://www.zhihu.com/search?q=x')
        crawler = bare(driver, domain='www.zhihu.com')
        crawler._body_text = lambda *a, **k: '三亚五日游攻略 人均两千'
        assert crawler.check_intercept('https://www.zhihu.com/search?q=x') == 'ok'
        assert (crawler.login_wall, crawler.risk_blocked) == (False, False)

    def test_a_driver_that_cannot_answer_reads_as_no_wall(self):
        """Aborting a crawl that is producing rows is the worse mistake."""
        driver = PlantDriver()
        driver.url_error = True
        crawler = bare(driver)
        assert crawler.check_intercept('https://www.douyin.com/') == 'ok'
        assert crawler.login_wall is False


class TestStreamingPlumbing:
    def test_a_broken_sink_keeps_the_row_and_the_crawl(self):
        """Persistence is best-effort: the row still travels downstream."""
        crawler = bare(PlantDriver())

        def hostile(_item):
            raise OSError('disk full')

        crawler.set_sink(hostile)
        assert crawler.emit({'链接': 'u'}) is True
        assert crawler.collected() == 1

    def test_an_item_the_sink_already_had_is_not_counted_twice(self):
        crawler = bare(PlantDriver())
        crawler.set_sink(lambda item: False)
        assert crawler.emit({'链接': 'u'}) is False
        assert crawler.collected() == 0

    def test_emit_of_nothing_is_a_no(self):
        crawler = bare(PlantDriver())
        assert crawler.emit(None) is False

    def test_a_resumed_crawler_counts_what_is_already_stored(self):
        """The target is compared against ``collected()``, so a seed that did not
        land would refill the whole table instead of the missing 20 rows."""
        crawler = bare(PlantDriver())
        crawler.seed([{'链接': 'a'}, {'链接': 'b'}])
        assert crawler.collected() == 2
        crawler.seed([])
        assert crawler.collected() == 2

    def test_positions_merge_rather_than_replace(self):
        crawler = bare(PlantDriver())
        seen = []
        crawler.set_cursor_sink(seen.append)
        crawler.mark_position(page=2)
        crawler.mark_position(done=7)
        assert crawler.position == {'page': 2, 'done': 7}
        assert seen[-1] == {'page': 2, 'done': 7}

    def test_a_cursor_write_that_raises_does_not_break_the_crawl(self):
        crawler = bare(PlantDriver())
        crawler.set_cursor_sink(lambda position: (_ for _ in ()).throw(OSError('locked db')))
        crawler.mark_position(page=4)
        assert crawler.position == {'page': 4}

    def test_a_crawler_handed_no_resume_starts_clean(self):
        assert Crawler.resume_of({'resume': {'page': 3}}) == {'page': 3}
        assert Crawler.resume_of({'resume': 'garbage'}) == {}
        assert Crawler.resume_of(None) == {}


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('8', 8),
        (12, 12),
        (None, 0),
        ('', 0),
        ('nonsense', 0),
        # A float-shaped cursor is not "page 8.7": it is a value this code never
        # wrote, so the crawl restarts rather than trusting a corrupt position.
        ('8.7', 0),
        (8.7, 8),
        (-3, 0),
        (True, 1),
    ],
)
def test_a_cursor_field_that_is_not_a_number_degrades_to_the_start(value, expected):
    assert as_index(value) == expected


def test_a_bad_cursor_field_uses_the_callers_default():
    assert as_index('nonsense', default=1) == 1
    assert as_index(None, default=5) == 5


class FlashingDriver:
    """A page with a story: every reading of it sees the next entry of *pages*.

    ``current_url`` peeks and ``body`` advances, which is the order
    :meth:`Crawler.verdict` reads them in, so one reading is one coherent page rather
    than the head of one mixed with the tail of the next.
    """

    def __init__(self, pages):
        self.pages = list(pages)
        self.step = 0
        self.visited = []

    @property
    def current_url(self):
        return self.pages[min(self.step, len(self.pages) - 1)][0]

    def body(self):
        text = self.pages[min(self.step, len(self.pages) - 1)][1]
        self.step += 1
        return text

    def get(self, url):
        self.visited.append(url)

    def find_element(self, by, selector):
        raise RuntimeError('the fake answers no element lookups')

    def execute_script(self, script, *args):
        return ''

    def quit(self):
        pass


def _arriving(pages, monkeypatch, **attrs):
    """A crawler whose next navigation lands on *pages*, with the settle polls free."""
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)
    driver = FlashingDriver(pages)
    crawler = bare(driver, **attrs)
    crawler._body_text = driver.body
    return crawler, driver


class TestAWallMustSurviveBeingJudged:
    """:meth:`Crawler.open` may not let a page on its way somewhere else end a crawl.

    Measured on weibo: a logged-in visit to a search URL flashes ``passport.weibo.com/sso``
    and is bounced back to the results about a second later. Judging that flash latched
    ``login_wall``, which stops the harvest loop, turns the run into a 继续 candidate and
    tells the user to re-save a cookie that is fine — the worst available mistake, because
    the crawl was working.
    """

    PASSPORT = 'https://passport.weibo.com/sso/signin'
    RESULTS = 'https://s.weibo.com/weibo?q=%E4%B8%89%E4%BA%9A'
    BODY = '三亚五日游攻略 人均两千'

    def _weibo(self, pages, monkeypatch):
        return _arriving(pages, monkeypatch, domain='www.weibo.com', login_url='https://www.weibo.com/')

    def test_a_redirect_that_flashes_the_login_page_is_not_a_wall(self, monkeypatch):
        crawler, driver = self._weibo([(self.PASSPORT, ''), (self.RESULTS, self.BODY)], monkeypatch)
        assert crawler.open(self.RESULTS) is True
        assert (crawler.login_wall, crawler.risk_blocked) == (False, False), 'the flash was believed'
        assert driver.step >= 2, 'the page was never re-read, so nothing proved it settled'

    def test_a_login_page_that_stays_is_still_a_wall(self, monkeypatch):
        crawler, driver = self._weibo([(self.PASSPORT, '')] * 8, monkeypatch)
        crawler.open(self.RESULTS)
        assert crawler.login_wall is True, 'a refusal that never moved must still be reported'
        assert driver.step >= Crawler.WALL_PROOFS, 'it was latched before the settle window was spent'

    def test_a_healthy_landing_costs_one_reading(self, monkeypatch):
        # The settle window is a defence against a flash, not a tax on every navigation:
        # a per-row detail crawl pays this once per row, so a clean page must be answered
        # on the first look.
        crawler, driver = self._weibo([(self.RESULTS, self.BODY)] * 4, monkeypatch)
        assert crawler.open(self.RESULTS) is True
        assert driver.step == 1, f'a clean page cost {driver.step} readings'
        assert crawler.login_wall is False

    def test_risk_control_that_stays_is_still_not_a_dead_cookie(self, monkeypatch):
        crawler, _driver = _arriving(
            [('https://www.zhihu.com/search?q=x', '40362 当前请求存在异常')] * 8,
            monkeypatch,
            domain='www.zhihu.com',
            login_url='https://www.zhihu.com/',
        )
        crawler.open('https://www.zhihu.com/search?q=x')
        assert (crawler.risk_blocked, crawler.login_wall) == (True, False)


#: Every navigation the shipped code still issues straight at the driver instead of
#: through :meth:`Crawler.open` — which owns surviving a slow renderer, dismissing the
#: site's first-run dialog and recording the request in :attr:`Crawler.requests`. Each
#: entry is a place where a page that answers late becomes an exception out of the node
#: instead of the platform's own "the page is not ready" line, and the xiaohongshu search
#: page is measured doing exactly that. Pinned both ways: a new one is red, and so is a
#: stale entry once a site has been moved onto ``open``.
BARE_NAVIGATIONS = {
    'backend/app.py': 2,
    'backend/crawlers/base.py': 3,  # ``open`` itself, cookie planting, the cookie probe
    'backend/crawlers/comments.py': 7,
    'backend/crawlers/wechat.py': 1,
    'backend/crawlers/weibo.py': 1,
    'backend/crawlers/zhihu.py': 2,
}


class TestNavigationGoesThroughOpen:
    def test_a_page_entered_past_open_is_an_accounted_debt(self):
        """The rule is only real while somebody counts it (see ``BARE_NAVIGATIONS``)."""
        found = {}
        for path in sorted((REPO_ROOT / 'backend').rglob('*.py')):
            if path.name.startswith('test_'):
                continue  # the probe scripts are the sanctioned place to drive a browser
            hits = len(re.findall(r'\.driver\.get\(', path.read_text(encoding='utf-8')))
            if hits:
                found[path.relative_to(REPO_ROOT).as_posix()] = hits
        assert found == BARE_NAVIGATIONS, (
            f'navigations outside open changed: {found} vs {BARE_NAVIGATIONS}\n'
            'a new one should go through Crawler.open; a removed one must leave the table too'
        )
