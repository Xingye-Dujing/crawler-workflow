"""Cookie capture for the overseas platforms (X/Twitter, Instagram, YouTube).

These three are registered so the Cookie panel can log a session in and store it
*before* any crawl exists for them — the same shape Bilibili and Douyin had while
only their capture was built. ``supports_crawl`` stays False, so the canvas and
``/api/workflow/execute`` refuse them by node label
(``crawl.platformNotCrawlable``) instead of handing back an empty table that
would read as "this keyword found nothing".

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


class YouTubeCrawler(LoginOnlyCrawler):
    """YouTube.

    ``.google.com`` is deliberately NOT one of its hosts even though the sign-in
    passes through it: those cookies open Gmail and Drive, and a YouTube cookie
    file must not become a copy of the whole Google account. The session YouTube
    actually sends lives on ``.youtube.com`` (``SID``/``__Secure-1PSID`` and
    friends), which is what the panel stores after pulling the browser back to
    its own page.
    """

    domain = 'www.youtube.com'
    login_url = 'https://www.youtube.com/'
