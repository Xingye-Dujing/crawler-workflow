"""A browser that cannot be started is refused BY NAME, before anything is launched.

Three machine-level situations arrive at the same call in :func:`crawlers.core.browser.launch` and
used to leave the same unreadable answer: no Chrome installed at all, a 设置 path pointing at a file
that is not there, and a chromedriver that does not pair with the installed Chrome. Selenium's
response to each was an exception from a child process (or "The path is not a valid file" naming a
path the user never typed), which a run console cannot turn into an action. These tests are the
contract that it now does: one named sentence per cause, the user's own words kept inside it, and no
half-claimed browser profile left behind.
"""

import pytest
from core import machine
from selenium.common.exceptions import WebDriverException

import crawlers.core.browser as browser_module
import crawlers.core.crawler as base_module
from crawlers.platforms.zhihu.crawler import ZhihuCrawler

pytestmark = pytest.mark.unit


@pytest.fixture
def launches(monkeypatch, tmp_path):
    """Record what the launch path tried to do, and never start a process.

    Nothing here patches ``os.path.isfile`` — the existence questions are answered by real files in
    ``tmp_path`` and by paths that are simply absent, so a test cannot accidentally change what every
    other module in the process sees. The paths are built from ``tmp_path``, not written as drive
    letters: a literal ``C:/…`` as data would pass here and mean nothing on the Linux server this
    project also ships to, and the question these three tests ask ("does the path exist") has the
    same answer on all three systems.
    """
    chrome = tmp_path / 'browser-registry' / 'chrome'
    gone_browser = tmp_path / 'typo' / 'chrome'
    gone_driver = tmp_path / 'gone' / 'chromedriver'
    box = {
        'chrome': str(chrome),
        'gone_browser': str(gone_browser),
        'gone_driver': str(gone_driver),
        'settings': {'browser_binary': '', 'driver_path': '', 'window_size': '1920x1080'},
    }

    class FakeChrome:
        # A headless launch now health-checks its renderer with one bounded UA read, so the double
        # has to answer the way a live session does — anything less is a browser this suite would
        # (correctly) refuse.
        def __init__(self, options=None, service=None):
            box['constructed'] = True

        def execute_script(self, _script, *_args):
            return 'Mozilla/5.0 HeadlessChrome/148.0.0.0 Safari/537.36'

        def execute_cdp_cmd(self, _name, _params=None):
            return None

        def set_window_size(self, *_args):
            return None

        def set_page_load_timeout(self, _seconds):
            return None

    monkeypatch.setattr(browser_module, 'ChromeWebDriver', FakeChrome)
    monkeypatch.setattr(browser_module, 'Service', lambda executable_path=None: ('service', executable_path))
    monkeypatch.setattr(browser_module, 'get_setting', lambda key: box['settings'].get(key, ''))
    # These cases are the MACHINE-mode answers: the generic refusal and Selenium Manager's blank
    # driver only exist when the user chose 本机. The installer-mode cases below set it back.
    monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'system')

    def fake_find_chrome(explicit='', env=None):
        # Mirrors the real contract: an explicit path is the answer or nothing, so a typo is never
        # quietly answered by a different Chrome than the one the user pointed at.
        if explicit:
            return explicit if explicit == box['chrome'] else ''
        return box['chrome']

    monkeypatch.setattr(browser_module.machine, 'find_chrome', fake_find_chrome)
    return box


def _start():
    return ZhihuCrawler(headless=True)


def test_no_chrome_refuses_and_names_the_setting(launches):
    launches['chrome'] = ''
    with pytest.raises(ValueError) as caught:
        _start()
    message = str(caught.value)
    assert 'Chrome' in message
    assert '浏览器路径' in message, 'the sentence has to point at the setting that can fix it'
    # The executable name is the running system's own, read off the same table the probe uses — a
    # Linux refusal that says ``chrome.exe`` is a remedy nobody can act on, and the parity check
    # between the two languages cannot see it because both said the same Windows thing.
    assert machine.chrome_executable_name() in message
    assert 'constructed' not in launches, 'a browser was constructed after the refusal'


def test_installer_source_refuses_a_missing_installer_chrome(launches, monkeypatch):
    """安装器安装的 is strict: the machine's Chrome is not a fallback, so the refusal says so."""
    monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'bundled')
    launches['chrome'] = ''
    with pytest.raises(ValueError) as caught:
        _start()
    message = str(caught.value)
    assert '安装器' in message and '本机' in message
    assert 'constructed' not in launches


def test_a_configured_browser_path_that_is_gone_is_not_replaced_by_a_found_one(launches):
    launches['settings']['browser_binary'] = launches['gone_browser']
    with pytest.raises(ValueError) as caught:
        _start()
    assert launches['gone_browser'] in str(caught.value)
    assert 'constructed' not in launches


def test_a_stale_driver_path_names_the_path_and_the_remedy(launches):
    launches['settings']['driver_path'] = launches['gone_driver']
    with pytest.raises(ValueError) as caught:
        _start()
    message = str(caught.value)
    assert launches['gone_driver'] in message
    assert 'Selenium' in message, 'the sentence must say how to get a driver that works'


def test_an_empty_driver_path_is_left_for_selenium_manager(launches, monkeypatch):
    """Blank is a real answer, not a missing file: it is what lets Selenium fetch a matching driver.

    The default used to be a hardcoded Program Files path that almost never exists, so this is the
    case that decides whether a fresh machine crawls at all.
    """
    seen = {}

    def record_service(executable_path=None):
        seen['path'] = executable_path
        return ('service', executable_path)

    launches['settings']['driver_path'] = ''
    monkeypatch.setattr(browser_module, 'Service', record_service)
    _start()
    assert seen['path'] == ''


def test_a_driver_that_exists_is_the_one_handed_to_the_service(launches, monkeypatch, tmp_path):
    # Named without an ``.exe`` on purpose: the question is "does the path the setting holds exist", and a
    # Linux driver is ``/usr/bin/chromedriver``. Pinning the Windows spelling here would let a real
    # portability bug through while still passing on the box that wrote it.
    driver = tmp_path / 'chromedriver'
    driver.write_bytes(b'MZ')  # existence is the whole question here
    seen = {}

    def record_service(executable_path=None):
        seen['path'] = executable_path
        return ('service', executable_path)

    launches['settings']['driver_path'] = str(driver)
    monkeypatch.setattr(browser_module, 'Service', record_service)
    _start()
    assert seen['path'] == str(driver)


def test_an_installer_driver_outranks_a_stale_empty_setting(launches, monkeypatch, tmp_path):
    """A settings.json from an older build holds ``driver_path: ''``; the installed driver must win.

    This is the exact first-run report: the installer's Chrome and chromedriver were both there, yet
    the blank stored setting sent the launch to Selenium Manager and the console blamed a version
    mismatch / first-use network fetch.
    """
    monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'bundled')
    components = tmp_path / 'components'
    driver = components / 'chromedriver' / '1.0' / 'chromedriver'
    driver.parent.mkdir(parents=True)
    driver.write_bytes(b'MZ')
    monkeypatch.setenv('CIXI_COMPONENTS_DIR', str(components))
    monkeypatch.setenv('CIXI_DRIVER_PATH', str(driver))
    launches['settings']['driver_path'] = ''
    seen = {}

    def record_service(executable_path=None):
        seen['path'] = executable_path
        return ('service', executable_path)

    monkeypatch.setattr(browser_module, 'Service', record_service)
    _start()
    assert seen['path'] == str(driver)


def test_installer_source_refuses_a_missing_installer_driver(launches, monkeypatch):
    """In installer mode a blank driver is not Selenium Manager's cue: it is a missing component."""
    monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'bundled')
    launches['settings']['driver_path'] = ''
    with pytest.raises(ValueError) as caught:
        _start()
    message = str(caught.value)
    assert '安装器' in message and 'chromedriver' in message
    assert 'constructed' not in launches


def test_a_driver_that_will_not_pair_keeps_its_own_words(launches, monkeypatch):
    def explode(options=None, service=None):
        raise WebDriverException(
            'session not created: This version of ChromeDriver only supports Chrome version 118\n'
            'please see https://example.invalid for details'
        )

    monkeypatch.setattr(browser_module, 'ChromeWebDriver', explode)
    with pytest.raises(ValueError) as caught:
        _start()
    message = str(caught.value)
    assert 'Chrome version 118' in message, 'the version the driver named is the fact to keep'
    assert 'example.invalid' not in message, 'only the first line of the driver is quoted'
    assert isinstance(caught.value.__cause__, WebDriverException)


def test_a_refusal_does_not_leave_the_profile_claimed(launches, monkeypatch):
    released = []
    launches['chrome'] = ''
    monkeypatch.setattr(browser_module, 'claim_profile', lambda profile_dir, abort: object())
    monkeypatch.setattr(base_module.Crawler, '_release_profile', lambda self: released.append(True))
    with pytest.raises(ValueError):
        _start()
    assert released == [True]
