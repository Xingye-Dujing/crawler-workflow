import contextlib
import json
import logging
import os
import re
import time

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
        (blank) account is not listed here; use :meth:`accounts_in_order` for the
        list a human chooses from, which includes it when its file exists.
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

    def accounts_in_order(self, platform: str) -> list:
        """Every account that HAS a file, oldest save first — ``''`` for the default included.

        Two questions the sorted list cannot answer, both asked by the user:

        * which login did this machine get first (「节点使用的账号默认都是第一个创建的账号」), and
        * does the platform have any cookie at all when the only one is a NAMED account
          (``exists(platform)`` is the blank file, and a ``zhihu@work_cookies.json`` is not it).

        Creation order is read from the filesystem rather than kept in a manifest: a manifest is
        a second source of truth that can be edited out of step with the files it describes, and
        these files are never renamed under us. ``st_ctime`` is the *creation* time on Windows
        (this is a local single-user tool, and the deploy branch is not) and an inode-change time
        elsewhere, so ``mtime`` is folded in as the tie-break and the answer degrades to "oldest
        known", never to alphabetical.
        """
        if not self.is_supported(platform):
            return []
        named = self.account_files(platform)
        entries = [''] if self.exists(platform) else []
        entries += named

        def _born(account: str) -> tuple:
            try:
                info = os.stat(self._path_for(platform, account))
            except OSError:
                return (float('inf'), account)
            return (min(info.st_ctime, info.st_mtime), account)

        return sorted(entries, key=_born)

    def has_any(self, platform: str) -> bool:
        """Whether this platform has a saved login for ANY account.

        The panel and the pre-run gate ask "is there a cookie here", and the blank file is not
        the whole answer: a user who saved every account under a name has nothing at
        ``zhihu_cookies.json`` and everything to crawl with.
        """
        return bool(self.accounts_in_order(platform))

    def next_free_account(self, platform: str) -> str:
        """The label to give a save that was asked to be the default while one already exists.

        「如果有多个留空就需要默认账号后面自动加数字」: the blank account is one file, and a second
        unnamed save would otherwise overwrite the first login with no sentence saying so. The
        generated label is ASCII (``default2``, ``default3``…) because it enters a filename — the
        *display* of it is 「默认账号2」, which is what the user reads (``account_label_key``).
        """
        if not self.exists(platform):
            return ''
        step = 2
        while self.exists(platform, f'default{step}'):
            step += 1
        return f'default{step}'

    @classmethod
    def account_label_key(cls, account: str) -> tuple:
        """``(i18n_key, extra)`` for how an account should be WORDed, never the bare label.

        ``''`` is 默认账号 and a generated ``default2`` is 默认账号2 — both are display names, so a
        machine label is only ever printed as-is when the user typed it themselves.
        """
        account = str(account or '').strip()
        if not account:
            return 'cookies.accountDefault', {}
        generated = re.fullmatch(r'default(\d+)', account)
        if generated:
            return 'cookies.accountDefaultNumbered', {'n': int(generated.group(1))}
        return None, {}

    def save(self, platform: str, cookies: list, account: str = ''):
        account = str(account or '').strip()
        path = self._path_for(platform, account)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        # The account belongs in the sentence: with one platform holding several logins, a line
        # that says only 「已保存 微博 的 Cookie」 leaves the user unable to tell which login he
        # just overwrote — and the console is the only record of the write.
        logger.info(t('cookie.savedAccount', platform=platform, account=self.label_of(account)))

    def label_of(self, account: str) -> str:
        """The WORD for an account in the current language (a typed label is already a word)."""
        label_key, label_args = self.account_label_key(account)
        return t(label_key, **label_args) if label_key else str(account or '').strip()

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

    def saved_at(self, platform: str, account: str = '') -> str:
        """When this login was last written, as a wall-clock string — or ``''`` if it is not there.

        The management view has to say WHICH of two accounts is the stale one, and a name alone
        cannot; the timestamp is metadata off the directory entry, so answering it never opens
        the jar.
        """
        try:
            stamp = os.path.getmtime(self._path_for(platform, account))
        except (OSError, ValueError):
            return ''
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(stamp))

    def entry_count(self, platform: str, account: str = '') -> int:
        """How many cookie rows are saved, counted without showing any of them."""
        return len(self.load(platform, account))

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
