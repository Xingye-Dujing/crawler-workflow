"""Shared base for the video platforms (was the core of ``crawlers/video.py``).

Bilibili (``crawlers.bilibili``) and Douyin (``crawlers.douyin``) both extend
:class:`VideoCrawler` and use the two generic row helpers below; keeping them here
means neither platform module re-declares them.
"""

import logging
from datetime import datetime, timedelta, timezone

from i18n import t

from .base import Crawler
from .engine import pagefetch

logger = logging.getLogger(__name__)


#: Chinese platforms stamp 发布时间 in Beijing time; render in that fixed zone so a crawler
#: on a UTC cloud server does not shift every timestamp back eight hours.
_CST = timezone(timedelta(hours=8))


def _stamp(value) -> str:
    """Unix seconds → the platform's Beijing-time datetime; blank when absent."""
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return ''
    return datetime.fromtimestamp(seconds, tz=_CST).strftime('%Y-%m-%d %H:%M:%S') if seconds else ''


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class VideoCrawler(Crawler):
    """Shared shape for the video platforms."""

    #: Flipped per platform once its search/detail/comment crawl exists.
    supports_crawl = False

    def _not_crawlable(self) -> RuntimeError:
        return RuntimeError(t('crawl.platformNotCrawlable', platform=self.domain))

    def _fetch_json(self, url: str) -> dict:
        """GET *url* from inside the open page, with the browser's own session.

        The endpoints authenticate the cookie the panel saved, so issuing the
        request in page is both the only way the credentials travel and the
        reason no signature has to be forged: measured ``code=0`` from the search
        page and from the video page alike. The mechanics live in
        :mod:`crawlers.engine.pagefetch` (one home for every page-context fetch);
        this keeps the platform's own ledger (``self.requests``) wired in.
        """
        # Counted alongside the navigations: "this board needs one request per page"
        # is a claim about the in-page fetches, not about ``open()``.
        return pagefetch.fetch_json(self.driver, url, requests=self.requests)

    def search(self, keyword: str, **_kwargs):
        raise self._not_crawlable()

    def get_detail(self, url: str) -> dict | None:
        raise self._not_crawlable()
