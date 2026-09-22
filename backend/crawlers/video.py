"""Video platforms: cookie-capable now, crawling deliberately not yet offered.

Bilibili and Douyin are added in two steps on purpose. This first step gives the
cookie panel a real session to capture against — the login page, the hosts the
cookies must be planted on, and the login-wall check — because every DOM decision
for video metadata and comments has to be read from a page this session can
actually reach. The crawl side is not implemented here, and the class says so:

* ``supports_crawl`` is False, so the workflow canvas never lists them as a data
  source and the execute endpoint refuses them early with a named reason.
* ``search`` / ``get_detail`` therefore cannot be reached by a saved workflow.
  They raise rather than returning an empty list, because an empty result would be
  indistinguishable from a real "this search found nothing" and would land in a
  dataset as if it were data — the same lesson WeChat comments just taught.

When the crawl lands, the selectors come from the live pages, not from memory.
"""

from i18n import t

from .base import Crawler


class VideoCrawler(Crawler):
    """Shared shape for cookie-only video platforms."""

    #: Flipped per platform once its search/detail/comment crawl exists.
    supports_crawl = False

    def _not_crawlable(self) -> RuntimeError:
        return RuntimeError(t('crawl.platformNotCrawlable', platform=self.domain))

    def search(self, keyword: str, **_kwargs):
        raise self._not_crawlable()

    def get_detail(self, url: str) -> dict | None:
        raise self._not_crawlable()


class BilibiliCrawler(VideoCrawler):
    """Bilibili (哔哩哔哩). Session capture only so far."""

    domain = 'www.bilibili.com'
    cookie_domains = ('bilibili.com', 'm.bilibili.com', 'api.bilibili.com')
    login_url = 'https://www.bilibili.com/'


class DouyinCrawler(VideoCrawler):
    """Douyin (抖音 web). Session capture only so far."""

    domain = 'www.douyin.com'
    cookie_domains = ('douyin.com', 'www.iesdouyin.com')
    login_url = 'https://www.douyin.com/'
