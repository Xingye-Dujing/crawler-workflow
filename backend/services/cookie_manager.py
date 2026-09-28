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
#:
#: The character set is "what a path segment may say and what this tool may fold safely":
#: letters, digits, ``_`` and ``-``. ``.`` and ``..`` are out because they are path parts,
#: ``/`` ``\\`` ``@`` because they are structure, and a space because the panel writes the
#: name into filenames that a shell or a script has to quote afterwards. Uppercase IS
#: accepted at the box, but it is not a distinct account: the key is lowercased here, on a
#: filesystem where ``Work`` and ``work`` are the same file — two spellings of one login is
#: exactly the thing this file refuses to keep.
ACCOUNT_RE = re.compile(r'^[a-z0-9_-]{1,24}$')


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

    #: The platform's own login has a NAME like any other account — ``default`` — because one
    #: thing cannot have two rules. It is also the only name that is spelled two ways: the
    #: empty string is its historical spelling (every file, node parameter and workflow written
    #: before multi-account support left it blank), so both arrive here and one path leaves.
    #: :meth:`key` is the single place that folds them together; nothing else may test for
    #: ``''`` to mean 「the default account」.
    DEFAULT_ACCOUNT = 'default'

    # The character rule is the module-level ``ACCOUNT_RE`` and this is that same object, not
    # a second literal: a rule written twice is a rule that can drift into two (it did — the
    # filename pattern gained ``-`` while the copy below still refused it).
    _ACCOUNT_RE = ACCOUNT_RE

    @classmethod
    def key(cls, account: str) -> str:
        """The one spelling of an account label: blank folds to ``default``.

        Returns the *name*, which is what lists, labels and node parameters carry. Path
        building uses the reverse (:meth:`path_segment`), because the default login's file
        name predates the name.
        """
        text = str(account or '').strip().lower()
        return cls.DEFAULT_ACCOUNT if text == '' else text

    @classmethod
    def is_default(cls, account: str) -> bool:
        """Whether *account* names the platform's own login, under either spelling."""
        return cls.key(account) == cls.DEFAULT_ACCOUNT

    @classmethod
    def path_segment(cls, account: str) -> str:
        """The segment the FILE and the KEY use: ``''`` for the default login, the label for the rest.

        Historical and deliberate — ``zhihu_cookies.json`` must stay ``zhihu_cookies.json`` for
        a user who never named an account, and the same is true of every workflow file and run
        record written before this name existed. Public because the preflight cache keys by
        account too, and a ``default`` probe that keyed itself apart from a blank one would
        ask the same question twice and answer it twice.
        """
        return '' if cls.is_default(account) else cls.key(account)

    def __init__(self, cookie_dir: str):
        self.cookie_dir = cookie_dir
        os.makedirs(cookie_dir, exist_ok=True)

    @classmethod
    def is_supported(cls, platform: str) -> bool:
        return str(platform or '') in cls.PLATFORMS

    @classmethod
    def is_account(cls, account: str) -> bool:
        """Whether *account* is a usable label — one rule for every account, default included.

        ``default`` matches the character rule like any other name, and the empty string is
        accepted because it is that same account's historical spelling, not a second kind of
        account. Folding happens in :meth:`key`, so no caller tests for ``''``.
        """
        text = str(account or '').strip().lower()
        return text == '' or bool(cls._ACCOUNT_RE.match(text))

    def path_for(self, platform: str, account: str = '') -> str:
        """Where this account's session lives — the one answer to that question.

        Public because the API layer has to ask it too (the management view reports
        whether a profile still matches the file it was planted from), and a filename
        built twice is a naming rule that can drift into two different accounts. It
        refuses an unsupported platform and a malformed account for exactly that reason:
        a path handed to a caller that never checked is how ``../`` becomes a session.

        ``default`` and ``''`` answer with the SAME path (the unsuffixed historical name);
        every other label is nested under ``@``.
        """
        if not self.is_supported(platform):
            raise ValueError(f'Unsupported platform: {platform}')
        account = self.key(account)
        if not self._ACCOUNT_RE.match(account):
            raise ValueError(f'Invalid account: {account}')
        segment = self.path_segment(account)
        stem = f'{platform}@{segment}' if segment else platform
        return os.path.join(self.cookie_dir, f'{stem}_cookies.json')

    def account_files(self, platform: str) -> list:
        """The named accounts that already have a saved cookie file, sorted.

        Read off the filenames only — no file is opened, so this answers "which
        accounts can be chosen" without touching any session value. The default account
        is not listed here (its file carries no account segment to read back); use
        :meth:`accounts_in_order` for the list a human chooses from, which includes it
        under its real name when its file exists.
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
                if account == self.DEFAULT_ACCOUNT:
                    # A file named ``zhihu@default_cookies.json`` would be a SECOND name for
                    # the platform's own login, which the path rule above never writes. Ignored
                    # rather than listed, so the panel cannot offer two entries that save to
                    # different files while meaning the same account.
                    continue
                if self._ACCOUNT_RE.match(account):
                    out.append(account)
        return sorted(out)

    def accounts_in_order(self, platform: str) -> list:
        """Every account that HAS a file, oldest save first — ``default`` spelled as a name.

        Two questions the sorted list cannot answer, both asked by the user:

        * which login did this machine get first (「节点使用的账号默认都是第一个创建的账号」), and
        * does the platform have any cookie at all when the only one is a NAMED account
          (``exists(platform)`` is the default file, and a ``zhihu@work_cookies.json`` is not it).

        Creation order is read from the filesystem rather than kept in a manifest: a manifest is
        a second source of truth that can be edited out of step with the files it describes, and
        a rename is the one thing that may touch these files — which is why it goes through
        :meth:`rename` and never through a shell. ``st_ctime`` is the *creation* time on Windows
        (this is a local single-user tool, and the deploy branch is not) and an inode-change time
        elsewhere, so ``mtime`` is folded in as the tie-break and the answer degrades to "oldest
        known", never to alphabetical.
        """
        if not self.is_supported(platform):
            return []
        named = self.account_files(platform)
        entries = [self.DEFAULT_ACCOUNT] if self.exists(platform) else []
        entries += named

        def _born(account: str) -> tuple:
            try:
                info = os.stat(self.path_for(platform, account))
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

        「如果有多个留空就需要默认账号后面自动加数字」: the default file is one file, and a second
        unnamed save would otherwise overwrite the first login with no sentence saying so. The
        generated label is ASCII (``default2``, ``default3``…) because it enters a filename — the
        *display* of it is 「默认账号2」, which is what the user reads (``account_label_key``).

        A platform with no default login yet answers ``default`` — the name of that slot — so
        every account the panel lists is spelled the same way: a word that fits the rule.
        """
        if not self.exists(platform):
            return self.DEFAULT_ACCOUNT
        step = 2
        while self.exists(platform, f'default{step}'):
            step += 1
        return f'default{step}'

    @classmethod
    def account_label_key(cls, account: str) -> tuple:
        """``(i18n_key, extra)`` for how an account should be WORDed, never the bare label.

        ``default`` (and its historical blank spelling) is 默认账号 and a generated ``default2``
        is 默认账号2 — both are display names, so a machine label is only ever printed as-is when
        the user typed it themselves.
        """
        account = cls.key(account)
        if account == cls.DEFAULT_ACCOUNT:
            return 'cookies.accountDefault', {}
        generated = re.fullmatch(r'default(\d+)', account)
        if generated:
            return 'cookies.accountDefaultNumbered', {'n': int(generated.group(1))}
        return None, {}

    def save(self, platform: str, cookies: list, account: str = ''):
        account = str(account or '').strip()
        path = self.path_for(platform, account)
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
            with open(self.path_for(platform, account), encoding='utf-8') as f:
                cookies = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return []
        return cookies if isinstance(cookies, list) else []

    def exists(self, platform: str, account: str = '') -> bool:
        if not self.is_supported(platform):
            return False
        return os.path.exists(self.path_for(platform, account))

    def saved_at(self, platform: str, account: str = '') -> str:
        """When this login was last written, as a wall-clock string — or ``''`` if it is not there.

        The management view has to say WHICH of two accounts is the stale one, and a name alone
        cannot; the timestamp is metadata off the directory entry, so answering it never opens
        the jar.
        """
        try:
            stamp = os.path.getmtime(self.path_for(platform, account))
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
        path = self.path_for(platform, account)
        if os.path.exists(path):
            os.remove(path)
            logger.info(t('cookie.deleted', platform=platform))

    def rename(self, platform: str, account: str, to: str) -> bool:
        """Move a saved login to a new label. True when the file moved, False when it did not exist.

        Renaming is a *file move*, never a rewrite: the jar's bytes are the user's session and
        reading them to copy them would put a login through a second process (and a second
        chance to leak). Both refusals belong here and not only in the route, because a path is
        built from both names and this is the only place that knows what those names point at:

        * ``default`` (the platform's own login, whose file keeps the historical
          ``<platform>_cookies.json`` name) has no file of its own to detach either — it IS the
          name every other account of that platform is nested under on the device side, so the
          route refuses it before asking;
        * a target that already holds a login is refused rather than overwritten, because the
          silent loser of a rename is the session nobody asked to delete.
        """
        account = str(account or '').strip().lower()
        to = str(to or '').strip().lower()
        if not account or account == self.DEFAULT_ACCOUNT:
            raise ValueError('default account cannot be renamed')
        if not self.is_account(to):
            raise ValueError(f'Invalid account: {to}')
        source = self.path_for(platform, account)
        target = self.path_for(platform, to)
        if os.path.exists(target):
            raise ValueError(f'Target account already exists: {to}')
        if not os.path.exists(source):
            return False
        os.replace(source, target)
        # No log line here on purpose: only the caller knows whether the account's browser
        # directory came along, and the sentence has to say which of the two actually happened.
        return True
