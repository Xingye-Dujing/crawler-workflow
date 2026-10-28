"""Driver-construction unit test — the browser-mode contract, no browser.

Chrome is swapped for a recorder, so the assembled options can be asserted
directly: headless must mean --headless=new, and the three occlusion/
backgrounding flags must be present in BOTH modes (a login browser that gets
covered or minimized must keep loading exactly like a focused one — that used
to be an untested assumption; a crawl against a throttled window reads empty
pages that are only empty because Chrome decided to nap).
"""

import pytest

import crawlers.core.browser as browser
from crawlers.platforms.zhihu.crawler import ZhihuCrawler

pytestmark = pytest.mark.unit

OCCLUSION_FLAGS = (
    '--disable-backgrounding-occluded-windows',
    '--disable-background-timer-throttling',
    '--disable-renderer-backgrounding',
)


@pytest.fixture
def captured_options(monkeypatch):
    box = {'cdp': [], 'journal': []}

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
            box['journal'].append('construct')

        def set_page_load_timeout(self, seconds):
            box['timeout'] = seconds
            box['journal'].append('set_page_load_timeout')

        def set_window_size(self, width, height):
            box['journal'].append(f'window_size {width}x{height}')

        def get(self, url):
            box['journal'].append(f'get {url}')

        def add_cookie(self, payload):
            box['journal'].append(f'add_cookie {payload.get("name")}')
            # A cookie whose domain does not match this document raises, exactly as on a real browser.
            return None

        @property
        def current_url(self):
            # A real driver exposes this as a property and the plant reads it as one, so an
            # attribute holding a method would have the parked-page check answer about the wrong
            # thing — and a navigation that looks parked is silently re-driven forever.
            return 'https://www.douyin.com'

        def execute_script(self, script, *args):
            box.setdefault('scripts', []).append(script)
            box['journal'].append('read_ua' if 'userAgent' in script else 'script')
            return self.SCRIPTED_UA

        def execute_cdp_cmd(self, name, params=None):
            box['cdp'].append((name, params or {}))
            box['journal'].append(f'cdp {name}')

    # Patched on the module that constructs it: browser.py imports the Chrome WebDriver class by
    # name (selenium re-exports it lazily through ``__getattr__``, which no checker can see as
    # callable), so the seam is the class, not an attribute of the ``selenium.webdriver`` package.
    monkeypatch.setattr(browser, 'ChromeWebDriver', FakeChrome)
    monkeypatch.setattr(browser, 'Service', lambda executable_path=None: ('service', executable_path))
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
        # ``content_prefs`` takes the one declared fact it acts on, and a session that never
        # considered the question declares it False — exactly what ``Crawler`` defaults on the class.
        return browser.content_prefs(bool(attrs.get('needs_images', False)))

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


def test_a_visible_window_gets_the_mask_but_not_the_headless_disguise(captured_options):
    """The UA/geometry disguise stays headless-only — a visible browser already IS a real window,
    and overriding its UA would fight what the user watches. The automation-tell MASK, however,
    runs on every browser: the visible login window is the one that has to face Google/Apple."""
    ZhihuCrawler(headless=False)
    names = _cdp_names(captured_options)
    assert 'Network.setUserAgentOverride' not in names, f'a visible window must not be UA-overridden: {names}'
    assert names == ['Page.addScriptToEvaluateOnNewDocument'], (
        f'the only CDP call on a visible window is the mask: {names}'
    )


def test_the_blink_flag_still_hides_the_automation(captured_options):
    """navigator.webdriver is made false by the launch flag, not a JS override — the flag must stay
    in the command line for every mode (the mask deliberately does not redefine webdriver)."""
    for headless in (True, False):
        ZhihuCrawler(headless=headless)
        assert '--disable-blink-features=AutomationControlled' in captured_options['options'].arguments, headless


@pytest.mark.parametrize('headless', [True, False])
def test_the_automation_mask_runs_on_every_browser_and_cannot_self_defeat(captured_options, headless):
    """The mask strips the chromedriver ``cdc_`` globals and must NOT re-add the tells measured worse
    than none: no ``navigator.webdriver`` redefine (blink flag owns it), no ``navigator.languages``
    override (that leaked ``;q=0.9``), and NO fabricated ``chrome.runtime`` (a normal page's is
    undefined — inventing it is a new mismatch). Runs in BOTH modes (headless crawls and the visible
    login window)."""
    ZhihuCrawler(headless=headless)
    sources = ' '.join(
        params.get('source', '')
        for name, params in captured_options['cdp']
        if name == 'Page.addScriptToEvaluateOnNewDocument'
    )
    assert "indexOf('cdc_')" in sources, f'the mask must strip the chromedriver globals, headless={headless}'
    assert 'navigator.webdriver' not in sources, 'the mask must not redefine webdriver (the blink flag owns it)'
    assert 'navigator.languages' not in sources, 'the mask must not redefine languages (the --lang leak)'
    assert ';q' not in sources, 'a languages q-value must never reappear in the mask'
    assert 'chrome.runtime' not in sources, 'the mask must not fabricate window.chrome.runtime'


def test_the_mask_is_installed_before_the_session_ever_loads_a_page(captured_options, tmp_path):
    """The one ordering rule the split moved out of a single function body.

    ``Page.addScriptToEvaluateOnNewDocument`` only reaches documents that load *after* it is
    registered, and the cookie plant is the session's very first navigation — the launch seeds a
    cookie by loading ``https://<domain>``, and a page that painted before the mask exists is a page
    where chromedriver's ``cdc_`` globals were readable. When the assembly and the plant were one
    method body this was structural (the plant was the last statement); after the split it is a
    convention across two modules, so it is asserted on the journal of one real launch.
    """
    cookie_file = tmp_path / 'zhihu@default.json'
    cookie_file.write_text(
        '[{"name": "sid", "value": "secret", "domain": ".zhihu.com", "path": "/"}]', encoding='utf-8'
    )
    crawler = ZhihuCrawler(headless=True, cookie_path=str(cookie_file))
    journal = captured_options['journal']
    try:
        masks = [i for i, step in enumerate(journal) if step == 'cdp Page.addScriptToEvaluateOnNewDocument']
        first_load = next((i for i, step in enumerate(journal) if step.startswith('get ')), None)
        assert masks, f'no new-document hook was ever registered: {journal}'
        assert first_load is not None, f'the session never loaded a page: {journal}'
        assert min(masks) < first_load, f'the mask was installed after the first page load: {journal}'
        assert any(step.startswith('add_cookie sid') for step in journal[first_load:]), (
            f'the cookie was never offered to the page that loaded: {journal}'
        )
        assert journal[0] == 'construct', f'something was asked of a driver that does not exist yet: {journal}'
    finally:
        crawler.driver = None
        crawler.close()
