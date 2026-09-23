"""Real Chrome: the profile setting has to reach the browser, and the directory has to persist.

Everything else about this feature is policy in Python (which directory, whether to
plant the saved cookie file). The one thing only a browser can answer is whether
``--user-data-dir`` is actually applied — a mistyped argument is silently ignored by
Chrome, which would leave every run looking successful while each one still started
as a brand-new device.

The effect is measured the way a localized browser allows: ``chrome://version`` prints
its labels in the UI language (个人资料路径 beside "Profile Path"), so rather than parse
that page this asks whether **Chrome wrote its own files into the directory we named** —
anything beside our marker. A browser that ignored the flag leaves that directory ours
alone. Local pages only: this tier performs no server writes and reaches no site.
"""

import contextlib
import os

import browser_profiles
import pytest

from crawlers import get_crawler

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def _chrome_files(path: str) -> set:
    """What Chrome itself put into this user-data-dir (our marker excluded)."""
    if not os.path.isdir(path):
        return set()
    return set(os.listdir(path)) - {browser_profiles.MARKER}


def _launch(cookie_dir=None):
    """A crawler browser, or a skip: this tier is not applicable without Chrome."""
    try:
        return get_crawler('bilibili', headless=True, cookie_dir=cookie_dir)
    except Exception as e:
        pytest.skip(f'Chrome/chromedriver unavailable: {e}')


def _booted(driver):
    """One navigation, so the browser has had a reason to open its profile."""
    with contextlib.suppress(Exception):
        driver.get('about:blank')


@pytest.fixture
def rooted(tmp_path, monkeypatch):
    root = str(tmp_path / 'profiles')
    monkeypatch.setattr(
        browser_profiles,
        'get_setting',
        lambda key: {'use_browser_profile': True, 'browser_profile_dir': root}[key],
    )
    return root


def test_chrome_populates_the_directory_it_was_given(rooted, tmp_path):
    crawler = _launch()
    try:
        _booted(crawler.driver)
        target = str(tmp_path / 'profiles' / 'bilibili')
        assert _chrome_files(target), f'--user-data-dir never reached the browser; {target} holds only our own files'
    finally:
        crawler.close()


def test_a_second_crawler_reuses_the_directory_and_stops_planting(rooted, tmp_path, monkeypatch):
    """The marker is what makes the second run keep its own session.

    ``_plant`` is spied rather than the crawl inspected, because the outcome that
    matters is "the saved snapshot was not pushed over a live profile" — a run that
    came back with rows would not show that at all.
    """
    from crawlers.base import Crawler

    planted = []

    def spy(self, cookies):
        planted.append(len(cookies))
        # Accepted, nothing left over: a spy that reported refusals would send
        # ``_load_cookies`` walking on to the next host and the count below would
        # measure the host list instead of the import policy.
        return len(cookies), []

    monkeypatch.setattr(Crawler, '_plant', spy)
    cookies = tmp_path / 'cookies'
    cookies.mkdir(parents=True, exist_ok=True)
    entry = '[{"name": "TESTONLY", "value": "x", "domain": ".bilibili.com"}]'
    (cookies / 'bilibili_cookies.json').write_text(entry, encoding='utf-8')
    target = str(tmp_path / 'profiles' / 'bilibili')

    first = _launch(cookie_dir=str(cookies))
    try:
        _booted(first.driver)
    finally:
        first.close()
    second = _launch(cookie_dir=str(cookies))
    try:
        _booted(second.driver)
    finally:
        second.close()

    assert planted == [1], f'expected one import and then silence, saw {planted}'
    assert browser_profiles.is_used('bilibili') and browser_profiles.is_imported('bilibili')
    assert _chrome_files(target), 'the second run did not boot in the first run’s profile either'


def test_turning_profiles_off_leaves_the_persistent_directory_untouched(rooted, tmp_path, monkeypatch):
    unused = tmp_path / 'unused'
    monkeypatch.setattr(
        browser_profiles,
        'get_setting',
        lambda key: {'use_browser_profile': False, 'browser_profile_dir': str(unused)}[key],
    )
    crawler = _launch()
    try:
        _booted(crawler.driver)
    finally:
        crawler.close()
    assert not unused.exists(), f'a disabled profile still created {unused}'
