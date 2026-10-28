"""The shared fake platform and browser-less crawler used by several crawler tests.

Lived inside ``tests/unit/crawlers/test_crawler_base.py`` until the Stage 10 test-tree split put
that file a directory away from ``tests/unit/runs/test_stop_wiring.py`` and
``tests/unit/test_first_content.py``; a test module imported by path-relative name is a helper
looking for a home, so it is one now.
"""

from crawlers.core.crawler import Crawler


class Probe(Crawler):
    """A concrete platform with no behaviour of its own.

    ``Crawler`` is abstract on purpose, so the only honest way to test its
    plumbing is a subclass that adds nothing but the two required methods.
    """

    def search(self, keyword, **kwargs):
        return []

    def get_detail(self, url):
        return None


def bare(driver, **attrs):
    """A crawler with no browser: the plumbing needs no Selenium to be tested.

    ``Crawler.__init__`` buys a real Chrome, so the instance is built with ``__new__``
    and its state written out here. That means **this list has to be kept in step
    with ``__init__``** every time the base class gains an attribute (it drifted once,
    when ``requests`` arrived).
    """
    crawler = Probe.__new__(Probe)
    crawler.driver = driver
    crawler.headless = True
    crawler.cookie_path = None
    crawler.domain = 'www.douyin.com'
    crawler.cookie_domains = ('douyin.com', 'www.iesdouyin.com')
    crawler.login_url = 'https://www.douyin.com/'
    crawler.prompts = ()
    crawler.login_wall = False
    crawler.risk_blocked = False
    crawler.unreachable = False
    crawler.pending_waits = 0
    crawler.profile_dir = None
    crawler._profile_lock = None
    crawler._abort = None
    crawler.cookies_loaded = 0
    crawler.requests = []
    crawler._collected = []
    crawler._cursor = {}
    crawler.watermark = ''
    crawler._watermark_hit = False
    crawler._watermark_candidate = ''
    crawler._sink = None
    crawler._cursor_sink = None
    for key, value in attrs.items():
        setattr(crawler, key, value)
    return crawler
