"""Assembling one Chrome, and holding the machine facts that decide whether it can be built.

The boundary this module draws is deliberate: everything here answers a question about **this
computer and this browser**, and nothing here knows what a crawl is. It never touches a cursor, a
sink, an end-reason or a wall flag — those are the session's, in :mod:`crawlers.core.crawler`. The
test for the line is "would this function still make sense if there were no site to read?" — which
is exactly what :class:`~crawlers.core.crawler.ProfileWarmer` needs: it builds a browser to produce a
profile directory and reads nothing.

Why it is not methods on ``Crawler``: the same assembly is needed by code that is not a crawl
(warming a template profile, a machine self-check), and a checker/CLI that imports the crawler base
should not have to import the crawl contract to ask how a window is launched.
"""

import contextlib
import json
import logging
import os
import re
import time

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeWebDriver
from sessions import profiles

from config import Config
from crawlers.core.faults import ProfileUnavailableError
from i18n import t
from settings_store import get_setting
from utils import machine_deps

logger = logging.getLogger(__name__)

#: Rewrites the screen/window geometry a headless Chrome reports before any site script runs.
#: A bare ``--headless=new`` sits on an 800×600 virtual display, which — together with the
#: ``HeadlessChrome`` token in its UA — is the whole fingerprint that gives a headless crawler away
#: against a REAL desktop window (measured 2026-09-26 in the #148 probes; navigator.webdriver and the
#: WebGL renderer already match a real window on this Chrome). ``__METRICS__`` is replaced with the
#: crawler's configured desktop size, so the window only ever reports those numbers.
#: It deliberately does NOT touch navigator.webdriver or navigator.languages: the blink flag
#: already makes webdriver a real ``false``, and a languages override leaked ``;q=0.9`` into
#: ``navigator.languages`` (measured) — both would *add* a mismatch instead of removing one.
#: The chromedriver ``cdc_`` globals were a SEPARATE leak (present on a driven VISIBLE window too,
#: so #148's headless-vs-desktop axis did not see them); they are stripped by ``_AUTOMATION_STEALTH_JS``
#: below, which runs on every browser.
_DESKTOP_GEOMETRY_JS = r"""
(function () {
    var M = __METRICS__;
    function rd(o, k, v) {
        try { Object.defineProperty(o, k, {get: function () { return v; }, configurable: true}); } catch (e) {}
    }
    var sw = M.sw, sh = M.sh;
    rd(window.screen, 'width', sw); rd(window.screen, 'height', sh);
    rd(window.screen, 'availWidth', sw); rd(window.screen, 'availHeight', sh);
    rd(window, 'outerWidth', sw); rd(window, 'outerHeight', sh);
    rd(window, 'innerWidth', sw); rd(window, 'innerHeight', sh);
})();
"""

#: The chromedriver-injected automation globals a modern bot-detector can read off ``window``,
#: masked on EVERY browser before its first page. It deletes ONLY those (this build injects bare
#: ``cdc_…`` properties a ``for…in`` scan sees; deleting them degrades Selenium's own wrappers to
#: their documented fallback). It deliberately does NOT: redefine ``navigator.webdriver`` (the blink
#: launch flag already yields a real ``false``); touch ``navigator.languages`` (``--lang`` already
#: yields a genuine list, and a JS override was measured to leak ``;q=0.9``); or fabricate
#: ``window.chrome.runtime`` — a normal page's ``chrome.runtime`` is **undefined** (it exists only in
#: extension contexts), so inventing it is a NEW mismatch and could trip a page gating an extension
#: bridge on ``chrome.runtime``. The measured headless-vs-visible fingerprints confirm ``chrome``/
#: ``runtime`` already match a real window; only ``cdc_`` was ever a leak. **Scope: the tab this
#: driver launched — not a popup a site opens later** (``addScriptToEvaluateOnNewDocument`` is
#: per-target), so this is anti-bot hygiene for the main page, not a promise that a Google/Apple SSO
#: popup will pass.
_AUTOMATION_STEALTH_JS = r"""
(function () {
    var named = ['__driver_unwrapped', '__selenium_unwrapped', '__fxdriver_unwrapped', '_Selenium_IDE_Recorder'];
    function leaky(key) { return key.indexOf('cdc_') >= 0 || named.indexOf(key) >= 0; }
    var found = [];
    for (var k in window) {
        try { if (leaky(k)) found.push(k); } catch (e) {}
    }
    for (var i = 0; i < found.length; i++) {
        try { delete window[found[i]]; } catch (e) {}
    }
})();
"""


def desktop_metrics() -> tuple:
    """The display size to report, from the configured ``window_size`` (default 1920×1080).

    Parsed rather than hardcoded so the reported desktop tracks what the user actually set —
    an invented 1707×1000 was measured to be *itself* a mismatch against a real window, which
    is the opposite of a disguise.
    """
    raw = str(get_setting('window_size') or '1920x1080')
    parts = re.split(r'[x*,\s]+', raw.strip()) if raw.strip() else []

    def positive(value, fallback: int) -> int:
        try:
            return max(800, int(value))
        except (TypeError, ValueError):
            return fallback

    width = positive(parts[0] if parts else '', 1920)
    height = positive(parts[1] if len(parts) > 1 else '', 1080)
    return width, height


def content_prefs(needs_images: bool) -> dict:
    """Chrome content preferences for this session — always an explicit answer.

    Both branches *write* a value, and that is the whole point. A crawl's blocker
    is persisted into the profile directory it ran on (measured: after one weibo
    crawl, ``data/chrome_profile/weibo/Default/Preferences`` carried
    ``managed_default_content_settings.images = 2``), so a later human-facing
    window that merely *omits* the preference inherits the block from the device
    it shares with that crawl — and the login page it shows has no QR code to
    scan, because a QR code is an ``<img>``. Saying 允许 explicitly is what makes
    「打开浏览器登录」 completable on a profile that has already crawled; the
    block itself stays the crawl default, since it is the largest per-navigation
    saving a text-and-attribute crawler has (see ``needs_images``).
    """
    return {'profile.managed_default_content_settings': {'images': 1 if needs_images else 2}}


def build_options(headless: bool, profile_dir: str | None, needs_images: bool) -> Options:
    """The launch configuration: headless shape, profile, window, language, blockers.

    Every switch here is a measured answer, not a list copied from a blog post, and the comments
    stay attached to the switch they justify — several of these were added because Chrome's own
    default made a crawl read an empty page that was only empty because the browser napped.
    """
    opts = Options()
    if headless:
        opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    # A background or occluded window must behave exactly like a visible
    # one. Chrome's default backgrounding throttles timers and freezes
    # rendering of occluded windows, which makes virtualised/lazy pages
    # stop loading — the crawl then reads an empty page that is only empty
    # because the browser decided to nap. (Headless is unaffected either
    # way; this covers the login browser and headless=False crawls.)
    opts.add_argument('--disable-backgrounding-occluded-windows')
    opts.add_argument('--disable-background-timer-throttling')
    opts.add_argument('--disable-renderer-backgrounding')
    if profile_dir:
        # Chrome creates the user-data-dir itself, so a missing directory is the
        # normal first run and not an error to handle here.
        opts.add_argument(f'--user-data-dir={profile_dir}')
    # Machine-local choices (driver / browser / window) come from the
    # settings store, editable in the frontend 设置 panel.
    opts.add_argument(f'--window-size={get_setting("window_size")}')
    opts.add_argument('--lang=zh-CN')
    # Sites' risk control treats navigator.webdriver as proof of a bot and
    # hard-blocks content pages (search keeps working, which is why the block
    # looked selective). Hide the automation flag on both surfaces.
    opts.add_argument('--disable-blink-features=AutomationControlled')
    # These are names of switches CHROMEDRIVER adds to every Chrome it starts, and
    # a name it never adds buys nothing: this list said 'automation' since it was
    # written, so `--enable-automation` stayed in the command line and every
    # visible crawl window carried the 「受自动测试软件的控制」 banner the option
    # was supposed to remove (the user asked about it on 2026-09-25).
    opts.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
    # ``eager`` returns as soon as the DOM is parseable instead of waiting
    # for every image, font and analytics beacon. A crawler reads text and
    # attributes, so the wait buys nothing — and on douyin the full ``load``
    # event was measured to never arrive at all (a 40 s TimeoutException on
    # the very first navigation), which no amount of timeout tuning fixes.
    opts.page_load_strategy = 'eager'
    opts.add_experimental_option('prefs', content_prefs(needs_images))
    return opts


def resolve_browser(opts: Options) -> None:
    """Point *opts* at the configured browser, or refuse by name before anything launches.

    Refuse before chromedriver is tried, and name the thing to fix. Three situations look
    identical from here (no Chrome at all, a 设置 path that points at nothing, a driver that
    cannot speak to the installed browser), and Selenium's own answer to the first two is an
    exception from a child process. The probe is :mod:`utils.machine_deps`, shared with the
    desktop launcher's self-check, so the two can never disagree about this machine.
    """
    browser_binary = str(get_setting('browser_binary') or '').strip()
    resolved = machine_deps.find_chrome(browser_binary)
    if browser_binary and not resolved:
        # An explicit path is the answer or nothing: falling back to a different Chrome than the one
        # the user pointed at would start a browser he did not ask for and blame the wrong machine.
        raise ValueError(t('crawl.browserBinaryMissing', path=browser_binary))
    if not resolved:
        # The executable name is this system's own, read off the table the probe uses: a Linux
        # sentence telling the user to point 设置 at ``chrome.exe`` is a refusal nobody can act on.
        raise ValueError(t('crawl.chromeMissing', browser=machine_deps.chrome_executable_name()))
    if browser_binary:
        opts.binary_location = browser_binary


def make_service() -> Service:
    """The driver service: a configured path must be a file, a blank one is Selenium Manager's."""
    driver_path = str(get_setting('driver_path') or '').strip()
    if driver_path and not os.path.isfile(driver_path):
        # Blank means "let Selenium Manager resolve a matching driver", which is the normal
        # answer on a fresh machine; a filled-in path that is not a file is a stale setting,
        # and Selenium Manager would be skipped because a path WAS given.
        raise ValueError(t('crawl.driverMissing', path=driver_path))
    return Service(executable_path=driver_path)


def apply_stealth(driver, domain: str) -> None:
    """Hide the page-visible automation tells on EVERY browser, before its first page.

    The launch already makes ``navigator.webdriver`` false (blink flag) and a real
    ``navigator.languages`` (``--lang``); what a modern bot-detector can still read from the page
    is the bare ``cdc_…`` chromedriver globals this build injects onto ``window``. This registers a
    new-document script that deletes them. It runs for the VISIBLE login window too — the browser
    that has to face a site's risk control — which is the reason this exists (``docs/crawler_notes.md``).

    It is deliberately NOT redefining webdriver or languages, and NOT fabricating
    ``window.chrome.runtime`` (a normal page's is undefined; inventing one is a new mismatch) —
    each of those was measured or argued to ADD a tell, not remove one. Scope: the tab this driver
    launched; a popup a site opens on click (Google/Apple SSO) is a different CDP target the mask
    does not reach, so this is not a promise that third-party login passes. A CDP failure (an old
    driver, a session mid-teardown) degrades to "still the blink-flag browser" and only logs — a
    fingerprint helper must never tear down a browser that came up correctly.
    """
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': _AUTOMATION_STEALTH_JS})
    except Exception as e:
        logger.debug('automation stealth not applied for %s: %s', domain, e)


def disguise_headless(driver) -> None:
    """Remove the two headless tells (UA, virtual-display metrics) on the live session.

    The UA is read back from this very Chrome and de-Headlessed, so its version can never rot
    against the installed build and the HTTP UA, ``navigator.userAgent`` and the Client-Hints
    platform all stay consistent — a hand-written UA string would drift out of the match. The
    geometry is registered to run before any page script. A CDP command that fails (an old
    driver, a session already mid-teardown) degrades to "still a plain headless browser", which is
    a *sanctioned* degradation and therefore has to be SAID: this is the one failure with a
    measured row-count consequence (a bare headless 知乎 author page answers 0 rows), so a short
    crawl that never saw this line would blame the site for a mask that did not install.
    """
    try:
        real_ua = str(driver.execute_script('return navigator.userAgent;') or '')
    except Exception as e:  # an unreadable session: leave the browser as a plain headless one
        logger.warning(t('crawl.disguiseUnreadable', err=e))
        return
    desktop_ua = real_ua.replace('HeadlessChrome', 'Chrome')
    width, height = desktop_metrics()
    script = _DESKTOP_GEOMETRY_JS.replace('__METRICS__', json.dumps({'sw': width, 'sh': height}))
    try:
        driver.execute_cdp_cmd(
            'Network.setUserAgentOverride',
            # The platform token is this system's own (``Win32`` on Windows is what a real 64-bit
            # Chrome reports there, not a typo): pairing a Linux UA with a Windows platform is the
            # invented mismatch #148 measured as a tell in the other direction.
            {'userAgent': desktop_ua, 'platform': machine_deps.navigator_platform()},
        )
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': script})
    except Exception as e:  # a partial disguise beats none; it only costs this browser the mask
        logger.warning(t('crawl.disguisePartial', err=e))


def launch(headless: bool, profile_dir: str | None, needs_images: bool, domain: str) -> ChromeWebDriver:
    """Build one Chrome exactly as a crawl session wants it, and hand back the live driver.

    A headless browser must not announce itself as headless. Measured 2026-09-26 (#148): a
    bare --headless=new reveals only two things a desktop does not — a UA containing
    "HeadlessChrome", and an 800×600 virtual display. Zhihu's 某作者的作品 page hands the
    bare headless a silent 0-row plate but renders 20→40 cards once BOTH are removed, so the
    platform was being served by forcing a VISIBLE window; we now fix the fingerprint and let
    headless stay headless instead (see :func:`disguise_headless`).

    The two masks run before anything navigates, because the cookie plant that follows is the
    session's first page load and the hook must already be installed when it runs.
    """
    opts = build_options(headless, profile_dir, needs_images)
    resolve_browser(opts)
    service = make_service()
    try:
        # The class itself, not ``webdriver.Chrome``: that name is a re-export the package
        # builds at import time, which no type checker can see as callable, so annotating with
        # it read as an error and needed a suppression. Importing the real class states what is
        # constructed and keeps the declared type honest.
        driver = ChromeWebDriver(options=opts, service=service)
    except WebDriverException as exc:
        # Kept as a refusal with the driver's own words inside it: that sentence names the
        # versions it tried to pair, which is what the user has to act on. No single cause is
        # claimed, because a version mismatch, a first-run download with no network and a
        # profile Chrome refuses to share all arrive here.
        raise ValueError(
            t('crawl.browserStartFailed', err=str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc))
        ) from exc
    if headless:
        disguise_headless(driver)
    # Hide the page-visible automation tells on EVERY browser (the visible login window
    # included), before any navigation.
    apply_stealth(driver, domain)
    # Apply the configured 窗口大小 to the *live* window, not just the launch hint.
    # ``--window-size`` is only a startup argument: a persistent profile restores its
    # own saved window bounds and overrides it, and a visible Chrome may open at a
    # default size — so the value the user set in 设置 never resized a real crawl
    # window until set_window_size is called on the session itself.
    try:
        driver.set_window_size(*desktop_metrics())
    except Exception as e:
        # A driver that rejects the resize (a mid-teardown session) keeps the launch
        # size; a crawl must not die over window geometry.
        logger.debug('set_window_size failed, keeping the launch size: %s', e)
    # A timeout the driver rejects (bad value, dead session) must not kill
    # the session — the crawl can still run on the default timeout.
    with contextlib.suppress(Exception):
        driver.set_page_load_timeout(int(get_setting('page_load_timeout')))
    return driver


def claim_profile(profile_dir: str | None, abort):
    """Take exclusive use of this platform's profile directory, if there is one.

    chromedriver pre-writes the profile's ``Default/Preferences`` before Chrome
    starts, so two sessions created in one directory at the same moment cannot
    both come up — measured, and it surfaces as ``session not created: failed to
    write prefs file`` on whichever node loses. One profile is one device, so the
    answer is to wait for the other crawl rather than to hand out a second
    directory and throw the device identity away.
    """
    if not profile_dir:
        return None
    started = time.monotonic()
    lock = profiles.acquire_profile(profile_dir, abort=abort)
    if lock is None:
        if abort is not None and abort():
            # Not a stuck profile — the user stopped this run while it queued.
            # Saying so matters: the other message blames a window that never
            # closed and sends the user hunting a browser that is not there.
            raise ProfileUnavailableError(t('crawl.profile_gave_up', dir=profile_dir))
        raise ProfileUnavailableError(
            t('crawl.profile_stuck', dir=profile_dir, seconds=round(Config.PROFILE_LOCK_TIMEOUT))
        )
    waited = time.monotonic() - started
    if waited >= 0.2:
        # Said once, before the wait it describes. No heartbeat: a crawl behind
        # this line is already running and the console is not a progress bar.
        logger.info(t('crawl.profile_wait', seconds=round(waited), dir=profile_dir))
    return lock


def release_profile(lock) -> None:
    """Give the profile back. Safe to call with ``None`` (a throwaway session never claimed one)."""
    profiles.release_profile(lock)
