"""Real Chrome: does the automation switch reach the browser, and can we even tell?

The user asked why every window the driver opens shows 「Chrome 正受到自动测试软件的控制」.
That banner is drawn because **chromedriver itself** adds ``--enable-automation`` to the
Chrome command line, and ``excludeSwitches`` is how a session asks for it to be left out
— by the switch's real name. The option in ``crawlers/base.py`` said ``'automation'``,
which chromedriver never adds, so the exclusion matched nothing while looking set.

Only the browser can answer whether a command-line switch arrived, and the page that
prints them is ``chrome://version``. Its *labels* are localized (so this file parses no
label — it asks for the page's text), and a switch string is not localized, which makes
the assertion above a measurement rather than a guess.

Both directions are measured: without the exclusion the switch must be visible (else
"absent" proves nothing — a page that reported no command line at all would pass that
half forever), and with ours it must be gone. Local pages only; no site is contacted.
"""

import pytest

from crawlers import get_crawler

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

#: A switch this project always passes, so a command line that does not carry it is a
#: page we cannot read — and the negative assertion below would be vacuous.
OUR_OWN_SWITCH = '--lang=zh-CN'


def _command_line(driver) -> str:
    driver.get('chrome://version')
    text = driver.execute_script('return document.body.innerText || "";') or ''
    assert OUR_OWN_SWITCH in text, f'chrome://version never reported the command line: {text[:240]!r}'
    return text


def _launch():
    try:
        return get_crawler('bilibili', headless=True, use_profile=False)
    except Exception as e:
        pytest.skip(f'Chrome/chromedriver unavailable: {e}')


def test_the_automation_switch_is_kept_out_of_the_command_line():
    crawler = _launch()
    try:
        line = _command_line(crawler.driver)
    finally:
        crawler.close()
    assert '--enable-automation' not in line, (
        f'excludeSwitches named no real switch; the banner is on screen: {line[:400]!r}'
    )


def test_the_same_browser_shows_the_switch_when_we_stop_excluding_it(monkeypatch):
    """The control: prove the previous test measured something.

    Dropping the ``excludeSwitches`` option must put ``--enable-automation`` back. If
    it did not, the switch was never there to begin with and "absent" would be worth
    nothing — which is the failure mode this tier keeps being bitten by.
    """
    from selenium.webdriver.chromium import options as chromium_options

    original = chromium_options.ChromiumOptions.add_experimental_option

    def without_exclude_switches(self, name, value):
        if name == 'excludeSwitches':
            return
        return original(self, name, value)

    monkeypatch.setattr(chromium_options.ChromiumOptions, 'add_experimental_option', without_exclude_switches)
    crawler = _launch()
    try:
        line = _command_line(crawler.driver)
    finally:
        crawler.close()
    assert '--enable-automation' in line, (
        'chromedriver did not add the switch this option exists to remove, so the '
        'exclusion above is excluding nothing and the real banner comes from elsewhere'
    )


# The reader the automation mask is judged by, scanning window property names the SAME way the
# mask decides what to delete (a ``cdc_`` substring plus the known unwrapped names) — not an
# anchored pattern that would miss the forms it claims to catch. about:blank is local (this tier
# contacts no site) and every field below is a browser-global, so the read does not depend on page
# content, and the chromedriver globals live on ``window`` regardless of which document is loaded.
_SURFACE_JS = r"""
const named = ['__driver_unwrapped', '__selenium_unwrapped', '__fxdriver_unwrapped', '_Selenium_IDE_Recorder'];
const globals = Object.getOwnPropertyNames(window).filter((k) => k.indexOf('cdc_') >= 0 || named.indexOf(k) >= 0);
return {
    webdriver: navigator.webdriver,
    globals: globals,
    languages: (navigator.languages || []).join(','),
};
"""


def _read_surface(crawler) -> dict:
    crawler.driver.get('about:blank')
    return crawler.driver.execute_script(_SURFACE_JS)


def test_the_page_visible_automation_surface_is_masked():
    """navigator.webdriver false, no chromedriver globals left on window, a genuine languages list
    with no ';q'. This measures the page-VISIBLE surface only — it does NOT claim a Google/Apple
    consent screen loads (the CDP attach, a brand-new untrusted profile, and a popup window that is a
    different CDP target are all outside what a launched-tab JS mask reaches — see crawler_notes.md),
    which is why the live gate, not this test, is the real answer.

    Viewport: headless Chrome (this driver's default launch), reading globals from ``about:blank``.
    """
    crawler = _launch()
    try:
        surface = _read_surface(crawler)
    finally:
        crawler.close()
    assert surface['webdriver'] is False, f'navigator.webdriver leaked: {surface}'
    assert surface['globals'] == [], f'chromedriver globals left on window: {surface["globals"]}'
    assert ';q' not in surface['languages'], f'languages leaked a q-value: {surface}'
    assert surface['languages'].lower().startswith('zh'), f'languages not the configured zh-CN: {surface}'


def test_the_mask_is_what_removes_the_globals_not_an_empty_page(monkeypatch):
    """Positive control (the other half, so the assertion above is not vacuous): with the mask
    disabled, the reader must SEE chromedriver globals on window — proving the reader measures the
    thing and the "[]" above is a masking result. If this build left none to begin with, this reds
    and the masked test would have been worth nothing.
    """
    from crawlers.base import Crawler

    monkeypatch.setattr(Crawler, '_apply_automation_stealth', lambda self: None)
    crawler = _launch()
    try:
        surface = _read_surface(crawler)
    finally:
        crawler.close()
    assert surface['globals'], (
        'without the mask the reader saw NO chromedriver globals, so the masked "[]" proves '
        'nothing — either this build injects none (nothing to mask) or the reader is not looking'
    )


def test_the_mask_is_measured_not_assumed(monkeypatch):
    """Two-sided control for webdriver: drop the blink flag, and it must read TRUE — proving the
    reader actually observes navigator.webdriver, so the ``False`` above is the flag's doing.
    """
    from selenium.webdriver.chromium import options as chromium_options

    original = chromium_options.ChromiumOptions.add_argument

    def without_blink_flag(self, arg, *rest):
        if arg == '--disable-blink-features=AutomationControlled':
            return
        return original(self, arg, *rest)

    monkeypatch.setattr(chromium_options.ChromiumOptions, 'add_argument', without_blink_flag)
    crawler = _launch()
    try:
        surface = _read_surface(crawler)
    finally:
        crawler.close()
    assert surface['webdriver'] is True, f'without the flag webdriver must read true (the reader works): {surface}'
