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
