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
    box = {}

    class FakeChrome:
        def __init__(self, options=None, service=None):
            box['options'] = options
            box['service'] = service

        def set_page_load_timeout(self, seconds):
            box['timeout'] = seconds

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


def _prefs(box):
    return (box['options'].experimental_options or {}).get('prefs') or {}


IMAGES_BLOCKED = {'profile.managed_default_content_settings': {'images': 2}}


def test_a_crawl_blocks_images_and_a_login_window_does_not(captured_options):
    """The blocker is the largest per-navigation saving a text crawler has — and it
    is fatal on the one window a human has to read: the QR code is an ``<img>``, so
    a login browser with images blocked shows nothing to scan. Reported by a user
    re-saving a weibo cookie and getting a page they could not complete.
    """
    crawler = ZhihuCrawler(headless=False)
    assert _prefs(captured_options) == IMAGES_BLOCKED
    crawler.driver = None

    login = ZhihuCrawler(headless=False, for_login=True)
    assert 'profile.managed_default_content_settings' not in _prefs(captured_options), (
        'the login window still blocks images, so no QR code can load'
    )
    login.driver = None


def test_a_platform_that_needs_images_still_gets_them(captured_options):
    """``for_login`` may only ever *widen* what loads: a platform that declares it
    needs images must not lose them because a caller asked for a crawl."""

    class NeedsImages(ZhihuCrawler):
        needs_images = True

    crawler = NeedsImages(headless=True)
    assert _prefs(captured_options) == {}
    crawler.driver = None


def test_get_crawler_passes_the_login_mode_through(captured_options):
    from crawlers import get_crawler

    crawler = get_crawler('zhihu', headless=False, for_login=True)
    assert crawler.needs_images is True
    assert 'profile.managed_default_content_settings' not in _prefs(captured_options)
    crawler.driver = None
