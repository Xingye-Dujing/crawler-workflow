import json
import logging
import os

from i18n import t

logger = logging.getLogger(__name__)


def _has_expiry(row: dict):
    """The expiry a browser will honour, under either spelling it is stored with.

    ``expiry`` is what the W3C ``add_cookie`` payload takes (seconds since the epoch) and
    what ``save_cookies`` writes back from a driver; ``expirationDate`` is what Chrome's own
    export names it. Accepting only one would report a persistent cookie as a session one.
    """
    for key in ('expiry', 'expirationDate'):
        value = row.get(key)
        if value not in (None, '', 0):
            return value
    return None


class CookieManager:
    """Manages cookie persistence for different platforms.

    Only a listed platform gets a cookie file: the platform name arrives from
    the client and is part of a path, so an unknown one is refused instead of
    turning into ``../../x_cookies.json``. The list is who can *hold a session*,
    which is wider than who can be crawled — the overseas trio below has capture
    but no crawler yet, and WeChat is the reverse (crawled, needs no login).
    """

    PLATFORMS = ('zhihu', 'weibo', 'xiaohongshu', 'bilibili', 'douyin', 'twitter', 'instagram', 'youtube')

    def __init__(self, cookie_dir: str):
        self.cookie_dir = cookie_dir
        os.makedirs(cookie_dir, exist_ok=True)

    @classmethod
    def is_supported(cls, platform: str) -> bool:
        return str(platform or '') in cls.PLATFORMS

    def _path_for(self, platform: str) -> str:
        if not self.is_supported(platform):
            raise ValueError(f'Unsupported platform: {platform}')
        return os.path.join(self.cookie_dir, f'{platform}_cookies.json')

    def save(self, platform: str, cookies: list):
        path = self._path_for(platform)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        logger.info(t('cookie.saved', platform=platform))

    def load(self, platform: str) -> list:
        try:
            with open(self._path_for(platform), encoding='utf-8') as f:
                cookies = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return []
        return cookies if isinstance(cookies, list) else []

    def exists(self, platform: str) -> bool:
        if not self.is_supported(platform):
            return False
        return os.path.exists(self._path_for(platform))

    def session_only_count(self, platform: str) -> int:
        """How many saved entries carry no expiry, which is how long they will live.

        Measured on a real Chrome with a real profile directory: a cookie planted without an
        ``expiry`` is gone once that browser closes — persistent cookies are written to the
        profile's own store, session cookies are not. So a profile refresh keeps the part of
        the session the site meant to outlive a window and loses the part it did not, and the
        panel has to say the number rather than promise a full transfer.

        Counts only: no name and no value is read out of the file here.
        """
        return sum(1 for row in self.load(platform) if isinstance(row, dict) and not _has_expiry(row))

    def delete(self, platform: str):
        path = self._path_for(platform)
        if os.path.exists(path):
            os.remove(path)
            logger.info(t('cookie.deleted', platform=platform))
