"""Accounts: bootstrapping, login, server-side sessions, password changes and admin operations.

Every rule lives here so the HTTP layer stays a thin translation of :class:`AccountError` into a
catalogue message. The service never returns a password hash: :meth:`public` is the only shape a
route may send to a browser.

Session lifetime is read from ``Config`` at call time (``CRAWLER_SESSION_IDLE_MINUTES`` /
``CRAWLER_SESSION_MAX_HOURS``) so a test can shorten it without a restart.
"""

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

#: Rewrite ``last_seen_at`` at most this often: one UPDATE per request would turn every static
#: asset into a database write.
TOUCH_INTERVAL_SECONDS = 60


def accounts_mode() -> bool:
    """Whether this process has accounts at all.

    Cloud mode always does. A local install turns them on by configuring a bootstrap password or
    by already having an ``accounts.db`` — there is no silent downgrade back to "everyone is the
    owner" while an account registry exists.
    """
    return bool(Config.CLOUD_MODE or str(Config.ADMIN_PASSWORD or '').strip() or os.path.exists(Config.ACCOUNTS_DB))


class _IpThrottle:
    """In-memory failed-login window per client address. Reset by a successful login."""

    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def _prune(self, ip: str, now: float) -> list:
        hits = [ts for ts in self._hits.get(ip, []) if now - ts < IP_WINDOW_SECONDS]
        if hits:
            self._hits[ip] = hits
        else:
            self._hits.pop(ip, None)
        return hits

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._prune(str(ip or ''), time.time())) >= IP_FAILURE_LIMIT

    def record(self, ip: str) -> None:
        with self._lock:
            now = time.time()
            hits = self._prune(str(ip or ''), now)
            hits.append(now)
            self._hits[str(ip or '')] = hits

    def clear(self, ip: str) -> None:
        with self._lock:
            self._hits.pop(str(ip or ''), None)


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
        if _throttle.blocked(ip):
            self._audit(EVENT_LOGIN_FAIL, username=name, ip=ip, detail='ip-throttled', now=now)
            raise AccountError('accounts.tooManyAttempts')
        row = self.store.get_user_by_username(name)
        if row is None:
            security.burn_unknown_password(password)
            _throttle.record(ip)
            self._audit(EVENT_LOGIN_FAIL, username=name, ip=ip, detail='unknown-user', now=now)
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
        if not security.verify_password(password, row['password_hash']):
            failures = int(row['failed_attempts'] or 0) + 1
            locked_until = now + security.lock_seconds(failures) if security.lock_seconds(failures) else 0
            self.store.record_failure(row['user_id'], failures, locked_until, now)
            _throttle.record(ip)
            self._audit(
                EVENT_LOGIN_FAIL,
                user_id=row['user_id'],
                username=row['username'],
                ip=ip,
                detail='bad-password',
                now=now,
            )
            if locked_until:
                raise AccountError('accounts.lockedOut', minutes=math.ceil(security.lock_seconds(failures) / 60))
            raise AccountError('auth.badCredentials')
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
        if now - float(row['last_seen_at'] or 0) >= TOUCH_INTERVAL_SECONDS:
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

    def change_password(self, account, current_password, new_password, token) -> None:
        row = self.store.get_user(account.user_id)
        if row is None:
            raise AccountError('accounts.notFound')
        if not security.verify_password(current_password, row['password_hash']):
            raise AccountError('accounts.currentPasswordWrong')
        password = security.validate_password(new_password, row['username'])
        if password == str(current_password or ''):
            raise AccountError('accounts.passwordUnchanged')
        self.store.update_password(
            row['user_id'], security.hash_password(password), must_change_password=False, now=time.time()
        )
        self.store.revoke_user_sessions(row['user_id'], time.time(), keep_sid_hash=security.token_hash(token))
        self._audit(EVENT_PASSWORD_CHANGE, user_id=row['user_id'], username=row['username'])
        return self.public(self.store.get_user(row['user_id']))

    # ─── administration ───

    def list_users(self, actor) -> list:
        self._require_admin(actor)
        return [self.public(row) for row in self.store.list_users()]

    def create_user(self, actor, username, password, role: str = 'user') -> dict:
        self._require_admin(actor)
        if role not in ROLES:
            raise AccountError('accounts.roleInvalid')
        name = security.validate_username(username)
        security.validate_password(password, name)
        if self.store.get_user_by_username(name) is not None:
            raise AccountError('accounts.usernameTaken', user=name)
        account = self._create(name, password, role, must_change_password=True, event=EVENT_ACCOUNT_CREATE, actor=actor)
        return account

    def reset_password(self, actor, user_id: str, password, must_change: bool = True) -> dict:
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
        return self.public(self.store.get_user(row['user_id']))

    def set_status(self, actor, user_id: str, status: str) -> dict:
        self._require_admin(actor)
        if status not in STATUSES:
            raise AccountError('accounts.statusInvalid')
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
        return self.public(self.store.get_user(row['user_id']))

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
        and an operator can recover or purge it deliberately.
        """
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
        trashed = self.trash_data(row['user_id'])
        self.store.delete_user(row['user_id'])
        self._audit(EVENT_ACCOUNT_DELETE, user_id=row['user_id'], username=row['username'], actor=actor, detail=trashed)
        result = self.public(row)
        result['trashed_to'] = trashed
        return result

    def trash_data(self, user_id: str) -> str:
        """Move one account's tree into ``users/.trash/<id>-<timestamp>`` (best effort)."""
        source = os.path.join(paths.users_root(), user_id)
        if not os.path.isdir(source):
            return ''
        os.makedirs(paths.trash_root(), exist_ok=True)
        target = os.path.join(paths.trash_root(), f'{user_id}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:4]}')
        shutil.move(source, target)
        return target

    def list_audit(self, actor, limit: int = 200) -> list:
        self._require_admin(actor)
        return self.store.list_audit(limit)

    # ─── shape helpers ───

    @staticmethod
    def public(row) -> dict:
        """The only account shape a route may serialise. No hash, no IP."""
        return {
            'user_id': row['user_id'],
            'username': row['username'],
            'role': row['role'],
            'status': row['status'],
            'must_change_password': bool(row['must_change_password']),
            'created_at': float(row['created_at'] or 0),
            'last_login_at': float(row['last_login_at']) if row['last_login_at'] is not None else None,
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
        self.store.audit(
            event=event,
            user_id=entry_user,
            username=entry_name,
            ip=ip,
            detail=detail,
            now=now if now is not None else time.time(),
        )

    @staticmethod
    def _require_admin(actor) -> None:
        if actor is None or not getattr(actor, 'is_admin', False):
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
    """Replace (or clear) the process singleton — the seam tests and the app fixture use."""
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = service


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
