import contextlib
import json
import logging
import os
import re

from i18n import t

logger = logging.getLogger(__name__)

#: An account label is the ONLY extra segment a cookie filename gains, and it comes from
#: a text box in the panel, so it is held to the same shape as a platform name: it enters
#: a filesystem path. ``@`` separates platform from account and no part may contain it,
#: which is what keeps ``zhihu@work_cookies.json`` unambiguously "zhihu, account work".
#: The empty account is the platform's default login and keeps the pre-multi-account
#: filename byte-for-byte, so an existing single-account user's files never move.
_ACCOUNT_RE = re.compile(r'^[a-z0-9_]{1,24}$')


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
    """Manages cookie persistence for different platforms, and for several accounts
    of one platform.

    Only a listed platform gets a cookie file: the platform name arrives from
    the client and is part of a path, so an unknown one is refused instead of
    turning into ``../../x_cookies.json``. The list is who can *hold a session*,
    which is wider than who can be crawled — the overseas trio below has capture
    but no crawler yet, and WeChat is the reverse (crawled, needs no login).

    A platform holds one session per **account**: the default (unnamed) file keeps
    its exact historical name, and an extra account gets ``<platform>@<account>_cookies.json``
    so one rate-limited account is not the whole platform's ceiling (weibo especially).
    The account label enters the filename, so it is validated to the same shape as the
    platform: an unknown one is refused, never turned into a path.
    """

    PLATFORMS = ('zhihu', 'weibo', 'xiaohongshu', 'bilibili', 'douyin', 'twitter', 'instagram', 'youtube')

    # The account label reaches a filename, so it may only be a lowercase word —
    # the same reason the platform must be on the whitelist above: neither may
    # carry a separator, an extension, or a path escape.
    _ACCOUNT_RE = re.compile(r'^[a-z0-9_]{1,24}$')

    def __init__(self, cookie_dir: str):
        self.cookie_dir = cookie_dir
        os.makedirs(cookie_dir, exist_ok=True)

    @classmethod
    def is_supported(cls, platform: str) -> bool:
        return str(platform or '') in cls.PLATFORMS

    @classmethod
    def is_account(cls, account: str) -> bool:
        """Whether *account* is a usable label (or the blank default)."""
        account = str(account or '').strip()
        return account == '' or bool(cls._ACCOUNT_RE.match(account))

    def _path_for(self, platform: str, account: str = '') -> str:
        if not self.is_supported(platform):
            raise ValueError(f'Unsupported platform: {platform}')
        account = str(account or '').strip()
        if account and not self._ACCOUNT_RE.match(account):
            raise ValueError(f'Invalid account: {account}')
        stem = f'{platform}@{account}' if account else platform
        return os.path.join(self.cookie_dir, f'{stem}_cookies.json')

    def account_files(self, platform: str) -> list:
        """The named accounts that already have a saved cookie file, sorted.

        Read off the filenames only — no file is opened, so this answers "which
        accounts can be chosen" without touching any session value. The default
        (blank) account is not listed here; it is always a valid choice and the
        caller offers it separately.
        """
        if not self.is_supported(platform):
            return []
        prefix = f'{platform}@'
        out = []
        with contextlib.suppress(OSError):
            for name in os.listdir(self.cookie_dir):
                if not name.startswith(prefix) or not name.endswith('_cookies.json'):
                    continue
                account = name[len(prefix) : -len('_cookies.json')]
                if self._ACCOUNT_RE.match(account):
                    out.append(account)
        return sorted(out)

    def save(self, platform: str, cookies: list, account: str = ''):
        path = self._path_for(platform, account)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        logger.info(t('cookie.saved', platform=platform))

    def load(self, platform: str, account: str = '') -> list:
        try:
            with open(self._path_for(platform, account), encoding='utf-8') as f:
                cookies = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return []
        return cookies if isinstance(cookies, list) else []

    def exists(self, platform: str, account: str = '') -> bool:
        if not self.is_supported(platform):
            return False
        return os.path.exists(self._path_for(platform, account))

    def session_only_count(self, platform: str, account: str = '') -> int:
        """How many saved entries carry no expiry, which is how long they will live.

        Measured on a real Chrome with a real profile directory: a cookie planted without an
        ``expiry`` is gone once that browser closes — persistent cookies are written to the
        profile's own store, session cookies are not. So a profile refresh keeps the part of
        the session the site meant to outlive a window and loses the part it did not, and the
        panel has to say the number rather than promise a full transfer.

        Counts only: no name and no value is read out of the file here.
        """
        return sum(1 for row in self.load(platform, account) if isinstance(row, dict) and not _has_expiry(row))

    def delete(self, platform: str, account: str = ''):
        path = self._path_for(platform, account)
        if os.path.exists(path):
            os.remove(path)
            logger.info(t('cookie.deleted', platform=platform))
