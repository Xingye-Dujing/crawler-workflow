"""Driver-construction unit test — the browser-mode contract, no browser.

Chrome is swapped for a recorder, so the assembled options can be asserted
directly: headless must mean --headless=new, and the three occlusion/
backgrounding flags must be present in BOTH modes (a login browser that gets
covered or minimized must keep loading exactly like a focused one — that used
to be an untested assumption; a crawl against a throttled window reads empty
pages that are only empty because Chrome decided to nap).
"""

import pytest

import crawlers.base as base_module
from crawlers.zhihu import ZhihuCrawler

pytestmark = pytest.mark.unit

OCCLUSION_FLAGS = (
    '--disable-backgrounding-occluded-windows',
    '--disable-background-timer-throttling',
    '--disable-renderer-backgrounding',
)


@pytest.fixture
def captured_options(monkeypatch):
    box = {'cdp': []}

    class FakeChrome:
        # A headless Chrome reports this UA; the disguise reads it back and strips the token, so
        # the recorder has to answer execute_script the way the real session would.
        SCRIPTED_UA = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
            'HeadlessChrome/148.0.0.0 Safari/537.36'
        )

        def __init__(self, options=None, service=None):
            box['options'] = options
            box['service'] = service

        def set_page_load_timeout(self, seconds):
            box['timeout'] = seconds

        def execute_script(self, script, *args):
            box.setdefault('scripts', []).append(script)
            return self.SCRIPTED_UA

        def execute_cdp_cmd(self, name, params=None):
            box['cdp'].append((name, params or {}))

    monkeypatch.setattr(base_module.webdriver, 'Chrome', FakeChrome)
    monkeypatch.setattr(base_module, 'Service', lambda executable_path=None: ('service', executable_path))
    return box


@pytest.mark.parametrize('headless', [True, False])
def test_driver_options_per_mode(captured_options, headless):
    crawler = ZhihuCrawler(headless=headless)
    args = captured_options['options'].arguments
    joined = ' '.join(args)
    assert ('--headless=new' in args) is headless, f'headless={headless}: {args}'
    for flag in OCCLUSION_FLAGS:
        assert flag in args, f'{flag} must be on in {"headless" if headless else "visible"} mode too'
    assert '--window-size=' in joined
    assert '--lang=zh-CN' in joined
    assert captured_options['service'][0] == 'service'
    crawler.driver = None  # nothing real to close


#: The switches chromedriver puts on every Chrome command line that we ask it to
#: leave out. These are **names of generated switches**, not descriptions: a name
#: chromedriver never adds is accepted silently and excludes nothing, which is
#: exactly what `'automation'` did here — the real one is `enable-automation`, and
#: without it every visible crawl window kept the 「受自动测试软件的控制」 banner.
#: The browser-side proof is in `tests/integration/test_browser_profile_launch.py`.
EXCLUDED_SWITCHES = ['enable-logging', 'enable-automation']


def test_excluded_switches_name_generated_switches_by_their_real_names(captured_options):
    crawler = ZhihuCrawler(headless=False)
    excluded = (captured_options['options'].experimental_options or {}).get('excludeSwitches')
    assert excluded == EXCLUDED_SWITCHES, f'excludeSwitches must name real generated switches: {excluded!r}'
    crawler.driver = None


def _prefs(box):
    return (box['options'].experimental_options or {}).get('prefs') or {}


IMAGES_BLOCKED = {'profile.managed_default_content_settings': {'images': 2}}

#: 1 = 允许, 2 = 封锁. The two are not interchangeable, and only one of them is
#: an answer: writing nothing leaves the decision to whatever the profile already
#: holds, which is what broke 登录窗口 (see ``test_a_login_window_overrides_a_profile_that_blocked``).
IMAGES_ALLOWED = {'profile.managed_default_content_settings': {'images': 1}}


def test_a_crawl_blocks_images_and_a_login_window_undoes_it(captured_options):
    """The blocker is the largest per-navigation saving a text crawler has — and it
    is fatal on the one window a human has to read: the QR code is an ``<img>``, so
    a login browser with images blocked shows nothing to scan. Reported by a user
    re-saving a weibo cookie and getting a page they could not complete.
    """
    crawler = ZhihuCrawler(headless=False)
    assert _prefs(captured_options) == IMAGES_BLOCKED
    crawler.driver = None

    login = ZhihuCrawler(headless=False, for_login=True)
    assert _prefs(captured_options) == IMAGES_ALLOWED, 'the login window must say 允许, not nothing'
    login.driver = None


def test_a_login_window_overrides_a_profile_that_blocked_images():
    """The contract the first fix missed, which is why the bug came back.

    A crawl writes its blocker into the *persistent* profile directory and it
    outlives the session, so a later login window on that same directory that
    simply omits the preference inherits the block. Absence is therefore not a
    usable answer for a human-facing window; only an explicit 允许 is. This checks
    the shape of that answer without a browser; the round trip through Chrome's own
    ``Preferences`` file is measured in
    ``tests/integration/test_browser_profile_launch.py``.
    """

    def session(**attrs):
        crawler = ZhihuCrawler.__new__(ZhihuCrawler)
        crawler.needs_images = False
        for key, value in attrs.items():
            setattr(crawler, key, value)
        return crawler._content_prefs()

    assert session()['profile.managed_default_content_settings']['images'] == 2
    allowed = session(needs_images=True)
    assert allowed['profile.managed_default_content_settings']['images'] == 1, (
        'a login window that inherits the profile block shows a page with no QR code'
    )


def test_a_platform_that_needs_images_still_gets_them(captured_options):
    """``for_login`` may only ever *widen* what loads: a platform that declares it
    needs images must not lose them because a caller asked for a crawl."""

    class NeedsImages(ZhihuCrawler):
        needs_images = True

    crawler = NeedsImages(headless=True)
    assert _prefs(captured_options) == IMAGES_ALLOWED
    crawler.driver = None


def test_get_crawler_passes_the_login_mode_through(captured_options):
    from crawlers import get_crawler

    crawler = get_crawler('zhihu', headless=False, for_login=True)
    assert crawler.needs_images is True
    assert _prefs(captured_options) == IMAGES_ALLOWED
    crawler.driver = None


def _cdp_names(box):
    return [name for name, _params in box['cdp']]


def test_a_headless_session_is_disguised_as_a_desktop_window(captured_options):
    """#148: a headless browser must not announce itself as headless.

    Measured on this Chrome, the ONLY things a bare ``--headless=new`` reveals that a real
    window does not are the ``HeadlessChrome`` token in the UA and an 800×600 virtual display.
    Both are rewritten through CDP right after the session is built. Asserting the *names* of
    the CDP commands (not their pixel values) keeps this browser-free: the values are pinned
    against the visible window by the #148 probes and the live tier.
    """
    ZhihuCrawler(headless=True)
    names = _cdp_names(captured_options)
    assert 'Network.setUserAgentOverride' in names, names
    assert 'Page.addScriptToEvaluateOnNewDocument' in names, names
    ua_cmd = dict(captured_options['cdp'])['Network.setUserAgentOverride']
    assert 'Headless' not in ua_cmd['userAgent'], 'the UA override must strip the headless token'
    assert ua_cmd['userAgent'], 'an empty UA override would be worse than none'
    # navigator.webdriver is NOT redefined — the blink flag already yields a real false, and
    # forcing undefined was measured to open a NEW gap against a real window (docs #148).
    injected = ' '.join(s for s in captured_options.get('scripts', [])) + ' '.join(
        (p.get('source', '') for _n, p in captured_options['cdp'])
    )
    assert 'navigator.webdriver' not in injected


def test_a_visible_window_is_left_alone(captured_options):
    """The disguise is for headless only — a visible browser already is a real window, and
    overriding its UA/metrics would fight what the user watches on screen."""
    ZhihuCrawler(headless=False)
    assert captured_options['cdp'] == [], f'a visible window must not be CDP-touched: {captured_options["cdp"]}'
