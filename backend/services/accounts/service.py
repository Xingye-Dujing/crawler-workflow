"""Accounts: bootstrapping, login, server-side sessions, password changes and admin operations.

Every rule lives here so the HTTP layer stays a thin translation of :class:`AccountError` into a
catalogue message. The service never returns a password hash: :meth:`public` is the only shape a
route may send to a browser.

Session lifetime is read from ``Config`` at call time (``CRAWLER_SESSION_IDLE_MINUTES`` /
``CRAWLER_SESSION_MAX_HOURS``) so a test can shorten it without a restart.
"""

import contextlib
import logging
import math
import os
import shutil
import threading
import time
import uuid

from core.config import Config
from runtime import paths

from i18n import t
from services.accounts import security
from services.accounts.errors import AccountError
from services.accounts.store import AccountsStore

logger = logging.getLogger(__name__)

#: Audit event names. Codes, not sentences — the panel translates them.
EVENT_LOGIN_OK = 'login_ok'
EVENT_LOGIN_FAIL = 'login_fail'
EVENT_LOGIN_LOCKED = 'login_locked'
EVENT_LOGOUT = 'logout'
EVENT_PASSWORD_CHANGE = 'password_change'
EVENT_ACCOUNT_CREATE = 'account_create'
EVENT_ACCOUNT_RESET = 'account_reset'
EVENT_ACCOUNT_DISABLE = 'account_disable'
EVENT_ACCOUNT_ENABLE = 'account_enable'
EVENT_ACCOUNT_DELETE = 'account_delete'
EVENT_SESSION_REVOKE = 'session_revoke'
EVENT_BOOTSTRAP = 'bootstrap'

ROLES = ('admin', 'user')
STATUSES = ('active', 'disabled')

#: A whole machine may fail a few logins (a stale tab, a typo); a script pays for the rest.
IP_WINDOW_SECONDS = 600
IP_FAILURE_LIMIT = 20
#: How many address+name windows the process remembers at all — see :meth:`_IpThrottle._bound`.
MAX_WINDOWS = 4096

#: Rewrite ``last_seen_at`` at most this often: one UPDATE per request would turn every static
#: asset into a database write. A CEILING, never the answer for a short idle window — see
#: :func:`_touch_interval_seconds`.
TOUCH_INTERVAL_SECONDS = 60


def _local_text(moment) -> str:
    """One epoch, read in the SERVER's zone, as the sentence the panel shows.

    '' for a moment that never happened (an account that never signed in) — the browser owns the WORD
    for that (``accounts.never``), because a missing value is data and a label is translation."""
    try:
        value = float(moment or 0)
    except (TypeError, ValueError):
        return ''
    if value <= 0:
        return ''
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(value))


def _touch_interval_seconds(idle_seconds: int) -> int:
    """How often a live session may refresh ``last_seen_at`` for this idle window.

    The idle test compares against ``last_seen_at``, which only advances on a touch: with a fixed
    60 s floor and ``CRAWLER_SESSION_IDLE_MINUTES=1`` the two thresholds collide, and someone
    actively typing is revoked anyway (the touch lands at the same moment the expiry is measured).
    A third of the window keeps the proof of life strictly inside it.
    """
    return max(1, min(TOUCH_INTERVAL_SECONDS, int(idle_seconds) // 3))


def accounts_mode() -> bool:
    """Whether this process has accounts at all.

    Cloud mode always does. A local install turns them on by configuring a bootstrap password or
    by already having an ``accounts.db`` — there is no silent downgrade back to "everyone is the
    owner" while an account registry exists.
    """
    return bool(Config.CLOUD_MODE or str(Config.ADMIN_PASSWORD or '').strip() or os.path.exists(Config.ACCOUNTS_DB))


class _IpThrottle:
    """In-memory failed-login window, keyed by address AND the name it was typing.

    The address alone is the wrong grain: behind the documented reverse proxy every visitor
    shares one ``remote_addr``, so twenty mistyped passwords (or one attacker spraying them)
    locked the whole server out for the window — an availability hole a stranger could open at
    will. A wrong name costs its own window; a successful login clears the pair.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    @staticmethod
    def _key(ip: str, username: str) -> str:
        return f'{str(ip or "")}|{str(username or "").strip().lower()}'

    def _prune(self, key: str, now: float) -> list:
        hits = [ts for ts in self._hits.get(key, []) if now - ts < IP_WINDOW_SECONDS]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def _sweep(self, now: float) -> None:
        """Drop every window whose hits all aged out. Caller holds the lock."""
        stale = [key for key, hits in self._hits.items() if not any(now - ts < IP_WINDOW_SECONDS for ts in hits)]
        for key in stale:
            self._hits.pop(key, None)

    def blocked(self, ip: str, username: str = '') -> bool:
        with self._lock:
            return len(self._prune(self._key(ip, username), time.time())) >= IP_FAILURE_LIMIT

    def record(self, ip: str, username: str = '') -> None:
        with self._lock:
            now = time.time()
            key = self._key(ip, username)
            hits = self._prune(key, now)
            hits.append(now)
            self._hits[key] = hits
            self._bound(now)

    def _bound(self, now: float) -> None:
        """Keep the window dictionary bounded by a size, not by how polite the traffic is.

        ``_prune`` only ever cleans the key a login just touched, so a stranger typing a thousand
        random usernames leaves a thousand entries that nothing revisits: memory grows with the
        attack and every later login pays for a longer scan. Aged-out windows go first; if a live
        spray still exceeds the cap, the OLDEST are dropped. Losing an hour-old window for a name
        nobody typed again costs nothing — the per-account ``failed_attempts`` lock, which is the
        real gate, lives in the database and is not affected.
        """
        if len(self._hits) <= MAX_WINDOWS:
            return
        self._sweep(now)
        if len(self._hits) <= MAX_WINDOWS:
            return
        oldest = sorted(self._hits.items(), key=lambda item: item[1][-1] if item[1] else 0)
        for key, _hits in oldest[: len(self._hits) - MAX_WINDOWS]:
            self._hits.pop(key, None)

    def clear(self, ip: str, username: str = '') -> None:
        """Forget this address's windows. With no name given, every name it tried."""
        with self._lock:
            prefix = f'{str(ip or "")}|'
            if not username:
                for key in [key for key in self._hits if key.startswith(prefix)]:
                    self._hits.pop(key, None)
                return
            self._hits.pop(self._key(ip, username), None)


_throttle = _IpThrottle()


def reset_throttle() -> None:
    """Forget every failed-login window (tests)."""
    global _throttle
    _throttle = _IpThrottle()


class SessionTicket:
    """What a successful login hands the HTTP layer: cookie value, CSRF token and identity."""

    def __init__(self, token: str, csrf_token: str, account):
        self.token = token
        self.csrf_token = csrf_token
        self.account = account


class AccountService:
    """Business rules over one :class:`AccountsStore`."""

    def __init__(self, store: AccountsStore = None):
        self._store = store
        self._store_lock = threading.Lock()
        # Serialises the check-then-write admin rules (last active admin, username uniqueness).
        # The store's lock covers one statement; these rules span a read and a write, and two
        # administrators acting at the same moment used to be able to disable each other.
        self._write_lock = threading.RLock()

    @property
    def store(self) -> AccountsStore:
        if self._store is None:
            with self._store_lock:
                if self._store is None:
                    self._store = AccountsStore()
        return self._store

    # ─── startup ───

    def has_users(self) -> bool:
        """Whether an account exists, WITHOUT creating the database as a side effect."""
        if self._store is None and not os.path.exists(Config.ACCOUNTS_DB):
            return False
        return self.store.has_users()

    def bootstrap(self):
        """Seed the first administrator from the environment, once.

        An existing registry is never touched: a stale ``CRAWLER_ADMIN_PASSWORD`` in a unit file
        would otherwise be a silent password reset on every restart.
        """
        if self.store.has_users():
            if str(Config.ADMIN_PASSWORD or '').strip():
                logger.info(t('accounts.bootstrapEnvIgnored'))
            return None
        username = security.validate_username(Config.ADMIN_USER)
        password = security.validate_password(Config.ADMIN_PASSWORD, username)
        account = self._create(
            username, password, 'admin', must_change_password=Config.CLOUD_MODE, event=EVENT_BOOTSTRAP
        )
        logger.info(t('accounts.bootstrapCreated', user=account['username']))
        return account

    # ─── login and sessions ───

    def authenticate(self, username, password, ip: str = '', user_agent: str = '') -> SessionTicket:
        now = time.time()
        ip = str(ip or '')
        name = str(username or '').strip()
        password_text = str(password or '')
        if _throttle.blocked(ip, name):
            self._audit(EVENT_LOGIN_FAIL, username=name, ip=ip, detail='ip-throttled', now=now)
            raise AccountError('accounts.tooManyAttempts')
        if len(password_text) > security.MAX_PASSWORD_LENGTH:
            # A multi-megabyte "password" still costs a scrypt run if handed to the verifier.
            # It can never be a valid credential, so refuse it at the same rate as a wrong one.
            security.burn_unknown_password('')
            _throttle.record(ip, name)
            self._audit(EVENT_LOGIN_FAIL, username=name, ip=ip, detail='oversized-password', now=now)
            raise AccountError('auth.badCredentials')
        row = self.store.get_user_by_username(name)
        if row is None:
            security.burn_unknown_password(password)
            _throttle.record(ip, name)
            self._audit(EVENT_LOGIN_FAIL, username=name, ip=ip, detail='unknown-user', now=now)
            raise AccountError('auth.badCredentials')
        # The password is verified FIRST, whatever the row says about a lock or a status. That
        # ordering is what keeps the promise the docs make — “统一文案（不区分用户名是否存在）”:
        # answering “登录失败次数过多” before the check let anyone with a wrong password tell a
        # registered username from an unregistered one, and a locked row also skipped the hashing,
        # so the timing said the same thing.
        if not security.verify_password(password, row['password_hash']):
            failures = self.store.bump_failure(row['user_id'], now)
            locked_until = now + security.lock_seconds(failures) if security.lock_seconds(failures) else 0
            if locked_until:
                self.store.set_locked_until(row['user_id'], locked_until, failures)
            _throttle.record(ip, row['username'])
            self._audit(
                EVENT_LOGIN_FAIL,
                user_id=row['user_id'],
                username=row['username'],
                ip=ip,
                detail='locked' if locked_until else 'bad-password',
                now=now,
            )
            raise AccountError('auth.badCredentials')
        if float(row['locked_until'] or 0) > now:
            minutes = max(1, math.ceil((float(row['locked_until']) - now) / 60))
            self._audit(
                EVENT_LOGIN_LOCKED,
                user_id=row['user_id'],
                username=row['username'],
                ip=ip,
                detail=f'{minutes}m',
                now=now,
            )
            raise AccountError('accounts.lockedOut', minutes=minutes)
        if row['status'] != 'active':
            self._audit(
                EVENT_LOGIN_FAIL, user_id=row['user_id'], username=row['username'], ip=ip, detail='disabled', now=now
            )
            raise AccountError('accounts.accountDisabled')
        self.store.record_login(row['user_id'], now, ip)
        _throttle.clear(ip)
        token = security.new_session_token()
        csrf_token = security.new_csrf_token()
        self.store.insert_session(
            sid_hash=security.token_hash(token),
            user_id=row['user_id'],
            csrf_token=csrf_token,
            created_at=now,
            expires_at=now + max(1, int(Config.SESSION_MAX_HOURS)) * 3600,
            user_agent=user_agent,
            ip=ip,
        )
        self._audit(EVENT_LOGIN_OK, user_id=row['user_id'], username=row['username'], ip=ip, now=now)
        self.store.purge_expired_sessions(now)
        return SessionTicket(token, csrf_token, self._account(row, csrf_token))

    def resolve(self, token) -> object | None:
        """The live identity behind a cookie value, or ``None``.

        A revoked, expired or idle session is refused; an idle one is revoked on the spot so a
        cookie found in a drawer cannot be resurrected by waiting. A disabled account's sessions
        are revoked together.
        """
        if not token:
            return None
        sid_hash = security.token_hash(token)
        row = self.store.get_session(sid_hash)
        if row is None:
            return None
        now = time.time()
        if row['revoked_at'] is not None or float(row['expires_at'] or 0) <= now:
            self.store.revoke_session(sid_hash, now)
            return None
        idle_seconds = max(1, int(Config.SESSION_IDLE_MINUTES)) * 60
        if now - float(row['last_seen_at'] or 0) > idle_seconds:
            self.store.revoke_session(sid_hash, now)
            return None
        if row['status'] != 'active':
            self.store.revoke_user_sessions(row['user_id'], now)
            return None
        if now - float(row['last_seen_at'] or 0) >= _touch_interval_seconds(idle_seconds):
            self.store.touch_session(sid_hash, now)
        return self._account(row, row['csrf_token'], must_change=bool(row['must_change_password']))

    def logout(self, token) -> None:
        if not token:
            return
        self.store.revoke_session(security.token_hash(token), time.time())

    def audit_logout(self, account, ip: str = '') -> None:
        """Record who signed out. Called after :meth:`logout`, with the identity still bound."""
        if account is None:
            return
        self._audit(EVENT_LOGOUT, user_id=account.user_id, username=account.username, ip=ip)

    def change_password(self, account, current_password, new_password, token, ip: str = '') -> dict:
        """Spend the password debt (or answer a voluntary change).

        The current password gets the same window as a login attempt. Without one, anyone holding a
        live session — a shared unlocked browser, a same-origin script — could guess it without
        limit, and every guess costs this server a scrypt run: an unauthenticated-by-usability
        denial of service on the one endpoint that also proves the password.
        """
        row = self.store.get_user(account.user_id)
        if row is None:
            raise AccountError('accounts.notFound')
        window = f'change:{row["user_id"]}'
        if _throttle.blocked(ip, window):
            raise AccountError('accounts.tooManyAttempts')
        if not security.verify_password(current_password, row['password_hash']):
            _throttle.record(ip, window)
            raise AccountError('accounts.currentPasswordWrong')
        _throttle.clear(ip, window)
        password = security.validate_password(new_password, row['username'])
        if password == str(current_password or ''):
            raise AccountError('accounts.passwordUnchanged')
        self.store.update_password(
            row['user_id'], security.hash_password(password), must_change_password=False, now=time.time()
        )
        self.store.revoke_user_sessions(row['user_id'], time.time(), keep_sid_hash=security.token_hash(token))
        self._audit(EVENT_PASSWORD_CHANGE, user_id=row['user_id'], username=row['username'])
        result = self.public(row)
        # What the write above did to the row: the debt is spent, and nothing else changed.
        result['must_change_password'] = False
        return result

    # ─── administration ───

    def list_users(self, actor) -> list:
        self._require_admin(actor)
        return [self.public(row) for row in self.store.list_users()]

    def create_user(self, actor, username, password, role: str = 'user') -> dict:
        with self._write_lock:
            self._require_admin(actor)
            if role not in ROLES:
                raise AccountError('accounts.roleInvalid')
            name = security.validate_username(username)
            security.validate_password(password, name)
            if self.store.get_user_by_username(name) is not None:
                raise AccountError('accounts.usernameTaken', user=name)
            account = self._create(
                name, password, role, must_change_password=True, event=EVENT_ACCOUNT_CREATE, actor=actor
            )
        return account

    def reset_password(self, actor, user_id: str, password, must_change: bool = True) -> dict:
        with self._write_lock:
            self._require_admin(actor)
            row = self.store.get_user(user_id)
            if row is None:
                raise AccountError('accounts.notFound')
            new_password = security.validate_password(password, row['username'])
            now = time.time()
            self.store.update_password(
                row['user_id'], security.hash_password(new_password), must_change_password=bool(must_change), now=now
            )
            self.store.revoke_user_sessions(row['user_id'], now)
            self._audit(
                EVENT_ACCOUNT_RESET,
                user_id=row['user_id'],
                username=row['username'],
                actor=actor,
                detail='must-change' if must_change else '',
            )
            # Described from the row in hand: a concurrent delete would make a fresh read ``None``
            # and turn an operation that succeeded into a TypeError.
            result = self.public(row)
            result['must_change_password'] = bool(must_change)
            return result

    def set_status(self, actor, user_id: str, status: str) -> dict:
        if status not in STATUSES:
            raise AccountError('accounts.statusInvalid')
        with self._write_lock:
            self._require_admin(actor)
            row = self.store.get_user(user_id)
            if row is None:
                raise AccountError('accounts.notFound')
            if status == 'disabled':
                if row['user_id'] == actor.user_id:
                    raise AccountError('accounts.cannotDisableSelf')
                if (
                    row['role'] == 'admin'
                    and row['status'] == 'active'
                    and self.store.count_active_admins(excluding=row['user_id']) == 0
                ):
                    raise AccountError('accounts.lastAdmin')
            now = time.time()
            self.store.set_status(row['user_id'], status, now)
            if status == 'disabled':
                self.store.revoke_user_sessions(row['user_id'], now)
            self._audit(
                EVENT_ACCOUNT_ENABLE if status == 'active' else EVENT_ACCOUNT_DISABLE,
                user_id=row['user_id'],
                username=row['username'],
                actor=actor,
            )
            result = self.public(row)
            result['status'] = status
            return result

    def force_logout(self, actor, user_id: str) -> dict:
        self._require_admin(actor)
        row = self.store.get_user(user_id)
        if row is None:
            raise AccountError('accounts.notFound')
        self.store.revoke_user_sessions(row['user_id'], time.time())
        self._audit(EVENT_SESSION_REVOKE, user_id=row['user_id'], username=row['username'], actor=actor)
        return self.public(row)

    def delete_user(self, actor, user_id: str, confirm_username: str) -> dict:
        """Remove the account and MOVE its data tree into ``users/.trash/``.

        Deletion never destroys crawl results in place: the tree is moved, the audit rows stay,
        and an operator can recover or purge it deliberately. The row and the tree move together:
        a registry row that survives its own deletion would leave an account that still logs in
        over a tree that is gone, so a failed move is undone before the refusal is raised.
        """
        with self._write_lock:
            row = self._deletion_target(actor, user_id, confirm_username)
            trashed = self.trash_data(row['user_id'])
            try:
                self.store.delete_user(row['user_id'])
            except Exception:
                # Put the tree back where the account can still find it, then let the caller
                # report the failure: half a deletion is the one outcome nobody can read.
                if trashed:
                    with contextlib.suppress(OSError):
                        shutil.move(trashed, paths.user_root(row['user_id']))
                raise
            self._audit(
                EVENT_ACCOUNT_DELETE, user_id=row['user_id'], username=row['username'], actor=actor, detail=trashed
            )
            result = self.public(row)
            result['trashed_to'] = trashed
            return result

    def check_deletable(self, actor, user_id: str, confirm_username: str) -> dict:
        """The delete rules, WITHOUT deleting anything.

        The route has to close the account's SQLite handles before the tree can move (Windows
        refuses to rename a directory holding an open database), so it must first know it is
        ALLOWED to — otherwise a refusal (a wrong confirmation, a non-admin) would arrive after
        the handles were already pulled out from under a live writer.

        The answer is :meth:`public`, never the row: a probe that returns a ``users`` row carries
        ``password_hash`` out of the service, and this is the only delete-path value a route could
        ever echo. The route discards it today — that is one line of luck, not a rule.
        """
        return self.public(self._deletion_target(actor, user_id, confirm_username))

    def _deletion_target(self, actor, user_id: str, confirm_username: str) -> dict:
        self._require_admin(actor)
        row = self.store.get_user(user_id)
        if row is None:
            raise AccountError('accounts.notFound')
        if row['user_id'] == actor.user_id:
            raise AccountError('accounts.cannotDeleteSelf')
        if str(confirm_username or '').strip().lower() != str(row['username']).lower():
            raise AccountError('accounts.confirmMismatch')
        if (
            row['role'] == 'admin'
            and row['status'] == 'active'
            and self.store.count_active_admins(excluding=row['user_id']) == 0
        ):
            raise AccountError('accounts.lastAdmin')
        return row

    def assert_admin(self, actor) -> None:
        """The public door for a route that wants to authorize BEFORE it probes another account.

        ``_guard_idle`` answers with a run id — somebody else's fact — so it may only run once the
        caller is proved to be an enabled administrator.
        """
        self._require_admin(actor)

    def trash_data(self, user_id: str) -> str:
        """Move one account's tree into ``users/.trash/<id>-<timestamp>`` (best effort)."""
        source = paths.user_root(user_id)
        if not os.path.isdir(source):
            return ''
        os.makedirs(paths.trash_root(), exist_ok=True)
        target = os.path.join(paths.trash_root(), f'{user_id}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:4]}')
        shutil.move(source, target)
        return target

    def list_audit(self, actor, limit: int = 200) -> list:
        self._require_admin(actor)
        rows = self.store.list_audit(limit)
        # Same rule as the account table: the moment is rendered where it was recorded, not where
        # the page happens to be open.
        for row in rows:
            row['ts_local'] = _local_text(row.get('ts'))
        return rows

    # ─── shape helpers ───

    @staticmethod
    def public(row) -> dict:
        """The only account shape a route may serialise. No hash, no IP.

        Every moment ships twice: the number (a client that needs to sort) and the server's own
        reading of it (``*_local``). The panel renders the second — a browser formatting an epoch
        prints the VIEWER's zone, so an administrator on UTC+8 and the audit line in the server log
        disagree by eight hours about when someone signed in. ``scheduling`` already answers this way
        with ``next_run_local``/``last_run_local``."""
        return {
            'user_id': row['user_id'],
            'username': row['username'],
            'role': row['role'],
            'status': row['status'],
            'must_change_password': bool(row['must_change_password']),
            'created_at': float(row['created_at'] or 0),
            'created_local': _local_text(row['created_at']),
            'last_login_at': float(row['last_login_at']) if row['last_login_at'] is not None else None,
            'last_login_local': _local_text(row['last_login_at']),
        }

    # ─── internals ───

    def _account(self, row, csrf_token: str, must_change=None):
        from runtime.account_context import Account

        return Account(
            user_id=row['user_id'],
            username=row['username'],
            role=row['role'],
            must_change_password=bool(row['must_change_password']) if must_change is None else bool(must_change),
            csrf_token=str(csrf_token or ''),
        )

    def _create(
        self, username: str, password: str, role: str, *, must_change_password: bool, event: str, actor=None
    ) -> dict:
        user_id = 'u_' + uuid.uuid4().hex[:12]
        row = self.store.insert_user(
            user_id=user_id,
            username=username,
            password_hash=security.hash_password(password),
            role=role,
            must_change_password=must_change_password,
            now=time.time(),
        )
        root = paths.for_user(user_id).ensure().data_dir
        if os.name == 'posix':
            # Windows has no POSIX mode; there the operator's own ACL is the boundary.
            os.chmod(root, 0o700)
        self._audit(event, user_id=user_id, username=username, actor=actor)
        return self.public(row)

    def _audit(
        self,
        event: str,
        *,
        user_id: str = '',
        username: str = '',
        actor=None,
        ip: str = '',
        detail: str = '',
        now: float = None,
    ) -> None:
        entry_user = user_id or (actor.user_id if actor is not None else '')
        entry_name = username or (actor.username if actor is not None else '')
        if actor is not None and user_id and actor.user_id != user_id:
            detail = (detail + ' ' if detail else '') + f'by={actor.username}'
        # A login refusal carries whatever the form said; an oversized or newline-laden value
        # must not become a multi-megabyte audit row or forge extra lines in a viewer.
        self.store.audit(
            event=event,
            user_id=str(entry_user or '')[:64],
            username=str(entry_name or '')[:64],
            ip=str(ip or '')[:64],
            detail=str(detail or '')[:300],
            now=now if now is not None else time.time(),
        )

    def _require_admin(self, actor) -> None:
        """The actor must still BE an enabled administrator in the registry.

        The role on a bound session is a snapshot. Re-reading it inside (or just before) the
        write is what stops two administrators disabling each other at the same moment — the
        second one's bound identity was revoked a millisecond earlier.
        """
        if actor is None or not getattr(actor, 'is_admin', False):
            raise AccountError('accounts.adminRequired')
        row = self.store.get_user(getattr(actor, 'user_id', ''))
        if row is None or row['role'] != 'admin' or row['status'] != 'active':
            raise AccountError('accounts.adminRequired')


#: The process-wide service. Lazy so importing this module does not open the database.
_SERVICE = None
_SERVICE_LOCK = threading.Lock()


def get_account_service() -> AccountService:
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = AccountService()
    return _SERVICE


def reset_service(service: AccountService = None) -> None:
    """Replace (or clear) the process singleton — the seam tests and the app fixture use.

    The replaced service's database handle is closed on the way out. Dropping the object is not
    dropping the connection: ``AccountsStore`` holds one SQLite handle for its lifetime, so every
    test that logged in left a live ``accounts.db`` connection (and its ``-wal``/``-shm``) behind,
    which on Windows is also the directory that cannot be deleted.
    """
    global _SERVICE
    with _SERVICE_LOCK:
        previous, _SERVICE = _SERVICE, service
    if previous is not None and previous is not service:
        with contextlib.suppress(Exception):
            previous.store.close()


#: Addresses that can only ever reach this machine.
_LOOPBACK_HOSTS = ('127.0.0.1', '::1', 'localhost')


def public_bind_refusal(host: str) -> str | None:
    """Refuse a bind outside this machine when nothing gates it, or ``None`` when it is safe.

    :func:`startup_error` can only see the DECLARED shape (``cloud``, a bootstrap password, an
    existing ``accounts.db``); the observable one is the socket. Without a registry the gate
    answers ``None`` for every request, so ``HOST=0.0.0.0`` publishes every saved crawl cookie,
    dataset and run record — and the ability to start a crawl on the owner's accounts — to anyone
    who can route to the port. A container default or a typo in a unit file must not be enough.
    """
    text = str(host or '').strip()
    if not text or text in _LOOPBACK_HOSTS or accounts_mode():
        return None
    return t('auth.publicBindNeedsAccounts', host=text)


def startup_error() -> str | None:
    """The named refusal ``app.py`` raises at import time, or ``None`` when the shape is safe.

    Side-effect-light on purpose: an absent ``accounts.db`` is not created just to answer the
    question, so a refused cloud boot leaves nothing behind.
    """
    if not accounts_mode():
        return None
    if Config.SECRET_KEY == Config.DEFAULT_SECRET_KEY:
        return t('auth.loginNeedsSecretKey')
    service = get_account_service()
    if service.has_users():
        return None
    if not str(Config.ADMIN_PASSWORD or '').strip():
        return t('accounts.bootstrapNeeded')
    try:
        username = security.validate_username(Config.ADMIN_USER)
        security.validate_password(Config.ADMIN_PASSWORD, username)
    except AccountError as exc:
        return t(exc.key, **exc.params)
    return None
