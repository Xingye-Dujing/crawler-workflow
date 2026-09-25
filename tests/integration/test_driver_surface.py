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
