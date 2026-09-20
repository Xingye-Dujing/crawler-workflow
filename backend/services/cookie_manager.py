import json
import logging
import os

from i18n import t

logger = logging.getLogger(__name__)


class CookieManager:
    """Manages cookie persistence for different platforms."""

    def __init__(self, cookie_dir: str):
        self.cookie_dir = cookie_dir
        os.makedirs(cookie_dir, exist_ok=True)

    def save(self, platform: str, cookies: list):
        path = os.path.join(self.cookie_dir, f'{platform}_cookies.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        logger.info(t('cookie.saved', platform=platform))

    def load(self, platform: str) -> list:
        path = os.path.join(self.cookie_dir, f'{platform}_cookies.json')
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def exists(self, platform: str) -> bool:
        path = os.path.join(self.cookie_dir, f'{platform}_cookies.json')
        return os.path.exists(path)

    def delete(self, platform: str):
        path = os.path.join(self.cookie_dir, f'{platform}_cookies.json')
        if os.path.exists(path):
            os.remove(path)
            logger.info(t('cookie.deleted', platform=platform))
