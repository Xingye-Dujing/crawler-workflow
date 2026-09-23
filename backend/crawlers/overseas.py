"""Cookie capture for the overseas platform that still has no crawl.

Instagram is registered here so the Cookie panel can log a session in and store it
*before* a crawl exists for it — the shape Bilibili, Douyin, YouTube and X had
before theirs landed. ``supports_crawl`` stays False **and** it is absent from
``crawl_capabilities.CAPABILITIES``, so the canvas never offers it, validation
refuses it by node label (``engine.source_unknown_platform``) and the executor
again by name (``run.notCrawlable``) — instead of handing back an empty table that
would read as "this keyword found nothing".

Its crawl is blocked on a measurement, not on effort: the live probe found a
profile that renders its header (name, 104M followers, bio) and **zero** post
tiles, in a visible window with a valid session, headless, and logged out alike,
while a hashtag redirects to ``/accounts/login/``. Until a real post list is
observed, anything written against it would be a guess.

What each class carries is only the two facts the panel needs and cannot know on
its own: the hosts its cookies are valid on (which is also the allowlist a pasted
entry link is checked against) and the page a login starts from.
"""

import logging

from i18n import t

from .base import Crawler

logger = logging.getLogger(__name__)


class LoginOnlyCrawler(Crawler):
    """A platform the panel can log into, with no crawl behind it yet."""

    #: Flipped per platform once its search/detail/comment crawl exists.
    supports_crawl = False

    def _refusal(self) -> RuntimeError:
        return RuntimeError(t('crawl.platformNotCrawlable', platform=self.domain))

    def search(self, keyword: str, **_kwargs):
        raise self._refusal()

    def get_detail(self, url: str) -> dict | None:
        raise self._refusal()


class TwitterCrawler(LoginOnlyCrawler):
    """X (推特): ``x.com`` is the live host, and ``twitter.com`` is kept because
    it still serves the same session and is what people paste from an old tab.
    A crawl will need both ``auth_token`` and the CSRF pair ``ct0``."""

    domain = 'x.com'
    cookie_domains = ('twitter.com',)
    login_url = 'https://x.com/'


class InstagramCrawler(LoginOnlyCrawler):
    """Instagram: the web app serves both the profile/grid pages and the
    ``/api/v1/`` endpoints from ``www.instagram.com``, so one host is enough —
    ``cookie_flow`` accepts the bare ``instagram.com`` for a pasted link because
    the recorded host carries its ``www.`` prefix."""

    domain = 'www.instagram.com'
    login_url = 'https://www.instagram.com/'
