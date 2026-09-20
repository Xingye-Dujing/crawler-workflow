import json
import logging
import os

from i18n import t

logger = logging.getLogger(__name__)


class CookieManager:
    """Manages cookie persistence for different platforms.

    Only the four platforms the app can crawl get a cookie file: the platform
    name arrives from the client and is part of a path, so an unknown one is
    refused instead of turning into ``../../x_cookies.json``.
    """

    PLATFORMS = ('zhihu', 'weibo', 'xiaohongshu', 'wechat')

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

    def delete(self, platform: str):
        path = self._path_for(platform)
        if os.path.exists(path):
            os.remove(path)
            logger.info(t('cookie.deleted', platform=platform))
