"""The renderer health check: one bounded UA read, and a refusal that names itself.

A headless Chrome whose renderer stopped answering used to hang the whole launch, because
``execute_script`` never returned and the disguise waited out the driver's own timeout. The launch
now probes first — one UA read with a hard bound — and refuses the browser when it does not answer,
instead of carrying on un-masked with every later command parked behind the same socket.

Everything here is a fake driver on a fake clock: no Chrome, no socket, and no real sleep beyond a
fraction of a second.
"""

import threading
import time

import pytest
from core.config import Config
from selenium.common.exceptions import WebDriverException

import crawlers.core.browser as browser

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _machine_component_mode(monkeypatch):
    """These cases assert renderer health, not the component-source gate."""
    monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'system')


@pytest.fixture(autouse=True)
def _settings_from_config(monkeypatch):
    """The health bounds are settings now; these cases still patch the Config constants.

    Read them lazily so a ``monkeypatch.setattr(Config, ...)`` inside a test is what the
    launch sees, and answer a plausible value for every other key the launch asks.
    """

    def setting(key):
        return {
            'renderer_probe_timeout': Config.RENDERER_PROBE_TIMEOUT,
            'renderer_close_timeout': Config.RENDERER_CLOSE_TIMEOUT,
            'page_load_timeout': 40,
            'profile_lock_timeout': Config.PROFILE_LOCK_TIMEOUT,
            'window_size': '960x920',
        }.get(key, '')

    monkeypatch.setattr(browser, 'get_setting', setting)


UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/148.0.0.0 Safari/537.36'


class _Service:
    """The part of a Selenium ``Service`` this module reads: the driver's own process number."""

    class _Process:
        pid = 4321

    process = _Process()


class _FakeDriver:
    """A driver that answers as it is told to, and records the order it was asked."""

    def __init__(self, options=None, service=None):
        self.options = options
        self.service = _Service()
        self.journal = []
        self.cdp = []
        self.ua = UA
        self.script_error = None
        self.script_wait = 0.0
        self.quit_wait = 0.0

    def execute_script(self, script, *_args):
        self.journal.append('read_ua')
        if self.script_wait:
            time.sleep(self.script_wait)
        if self.script_error is not None:
            raise self.script_error
        return self.ua

    def execute_cdp_cmd(self, name, params=None):
        self.cdp.append((name, params or {}))
        self.journal.append(f'cdp {name}')

    def set_window_size(self, *_args):
        return None

    def set_page_load_timeout(self, _seconds):
        return None

    def quit(self):
        self.journal.append('quit')
        if self.quit_wait:
            time.sleep(self.quit_wait)


@pytest.fixture
def fake_chrome(monkeypatch):
    """Patch the two Selenium seams and hand back the driver the launch built."""
    built = {}

    def build(**traits):
        driver = _FakeDriver()
        for name, value in traits.items():
            setattr(driver, name, value)
        built['driver'] = driver
        return driver

    monkeypatch.setattr(browser, 'ChromeWebDriver', lambda options=None, service=None: build())
    monkeypatch.setattr(browser, 'Service', lambda executable_path=None: _Service())
    return built


@pytest.fixture
def reaper(monkeypatch):
    """Record what the OS reaper was aimed at, without killing anything."""
    calls = []
    monkeypatch.setattr(browser.procs, 'reap_process', lambda pid: (calls.append(pid), (True, ''))[1])
    return calls


def test_a_healthy_renderer_is_probed_once_before_the_disguise(fake_chrome):
    """The UA read is the health check, and the disguise reuses it.

    Reading twice would double the cost of every launch and — on a renderer that answers the first
    read and wedges on the second — put an unbounded call back into the disguise.
    """
    browser.launch(headless=True, profile_dir=None, needs_images=False, domain='zhihu')
    driver = fake_chrome['driver']

    assert driver.journal.count('read_ua') == 1, driver.journal
    assert driver.journal.index('read_ua') < driver.journal.index('cdp Network.setUserAgentOverride')
    names = [name for name, _params in driver.cdp]
    # The disguise's two commands come first, then the automation mask every browser gets.
    assert names[:2] == ['Network.setUserAgentOverride', 'Page.addScriptToEvaluateOnNewDocument'], names
    assert names[2:] == ['Page.addScriptToEvaluateOnNewDocument'], names
    override = dict(driver.cdp)['Network.setUserAgentOverride']
    assert 'Headless' not in override['userAgent'], 'the disguise still strips the headless token'


def test_a_healthy_session_gets_the_automation_mask_after_the_disguise(fake_chrome):
    """Order matters: the UA override and geometry must be registered before the mask's new-document
    hook, and both before the first navigation (the cookie plant)."""
    browser.launch(headless=True, profile_dir=None, needs_images=False, domain='zhihu')
    journal = fake_chrome['driver'].journal
    assert journal.index('cdp Network.setUserAgentOverride') < journal.index(
        'cdp Page.addScriptToEvaluateOnNewDocument'
    )


def test_a_renderer_that_never_answers_is_refused_by_name(fake_chrome, reaper, monkeypatch):
    """A wedged renderer costs the probe's bound, not the driver's 120 s timeout — and then the
    launch refuses with a sentence the user can act on (delete the profile / use a throwaway one).
    Nothing is disguised: a browser that cannot answer has no business crawling."""
    monkeypatch.setattr(Config, 'RENDERER_PROBE_TIMEOUT', 0.2)
    monkeypatch.setattr(Config, 'RENDERER_CLOSE_TIMEOUT', 0.1)
    driver = _FakeDriver()
    driver.script_wait = 0.4
    driver.quit_wait = 0.4
    monkeypatch.setattr(browser, 'ChromeWebDriver', lambda options=None, service=None: driver)

    started = time.monotonic()
    with pytest.raises(ValueError) as raised:
        browser.launch(headless=True, profile_dir=None, needs_images=False, domain='zhihu')
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f'the refusal waited {elapsed:.1f}s on a wedged renderer'
    assert 'zhihu' in str(raised.value)
    assert driver.cdp == [], 'a renderer that failed the probe must not be disguised'
    assert 'quit' in driver.journal, 'the useless browser must be closed'
    assert reaper == [4321], 'a quit that never returns has to end in a reap of that session'


def test_a_probe_error_is_refused_and_carries_the_drivers_words(fake_chrome, monkeypatch):
    """An unreadable session is a refusal too — not a silent bare-headless crawl."""
    monkeypatch.setattr(Config, 'RENDERER_CLOSE_TIMEOUT', 0.1)
    driver = _FakeDriver()
    driver.script_error = WebDriverException('no such session')
    monkeypatch.setattr(browser, 'ChromeWebDriver', lambda options=None, service=None: driver)

    with pytest.raises(ValueError, match='no such session'):
        browser.launch(headless=True, profile_dir=None, needs_images=False, domain='zhihu')
    assert driver.cdp == []


def test_a_visible_window_is_not_health_checked(fake_chrome):
    """The visible login window is the user's own: it gets no probe delay and no disguise, and a
    slow window is the user's to judge (the cookie job has its own grace)."""
    browser.launch(headless=False, profile_dir=None, needs_images=True, domain='weibo')
    assert 'read_ua' not in fake_chrome['driver'].journal
    assert [name for name, _params in fake_chrome['driver'].cdp] == ['Page.addScriptToEvaluateOnNewDocument']


def test_a_wedged_quit_does_not_hold_the_teardown(reaper, monkeypatch):
    """``close`` runs in a ``finally``; a renderer that stopped answering must not park the worker
    there. The quit is abandoned after its grace and the process is reaped by PID instead."""
    monkeypatch.setattr(Config, 'RENDERER_CLOSE_TIMEOUT', 0.1)
    driver = _FakeDriver()
    driver.quit_wait = 0.5

    started = time.monotonic()
    browser.close_driver(driver)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f'close waited {elapsed:.1f}s on a wedged quit()'
    assert reaper == [4321]


def test_a_stopped_session_closes_silently(monkeypatch):
    """Teardown may not raise: a session replaced by ``DeadDriver`` answers ``quit`` and must not
    turn its own stop into a second exception from the ``finally`` that is closing it."""
    monkeypatch.setattr(Config, 'RENDERER_CLOSE_TIMEOUT', 0.1)

    class _Dead:
        def quit(self):
            raise SystemExit('stop')

    browser.close_driver(_Dead())  # no exception escapes the teardown


def test_the_abandoned_probe_thread_is_a_daemon(fake_chrome, monkeypatch, reaper):
    """A pool thread would be joined at interpreter exit, turning the bound into a second wait."""
    monkeypatch.setattr(Config, 'RENDERER_PROBE_TIMEOUT', 0.05)
    monkeypatch.setattr(Config, 'RENDERER_CLOSE_TIMEOUT', 0.05)
    driver = _FakeDriver()
    driver.script_wait = 0.3
    monkeypatch.setattr(browser, 'ChromeWebDriver', lambda options=None, service=None: driver)

    with pytest.raises(ValueError):
        browser.launch(headless=True, profile_dir=None, needs_images=False, domain='zhihu')

    probes = [t for t in threading.enumerate() if t.name.startswith('browser-probe')]
    assert probes and all(t.daemon for t in probes), f'a probe thread outlived its bound: {probes}'
