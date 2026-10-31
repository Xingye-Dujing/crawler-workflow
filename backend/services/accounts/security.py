"""Credentials, tokens and the rules that decide whether a password is acceptable.

Passwords are hashed with Werkzeug's ``scrypt`` method (the stdlib backend: no extra C library,
no extra package, salted per password and parameter-tagged in the stored string). Nothing in this
module ever logs, returns or formats a password or a hash — a caller only ever gets ``True/False``
or a new hash to store.

Session ids and CSRF tokens are random, and only their SHA-256 is stored in ``accounts.db``:
a leaked database file therefore does not hand out live cookies. (It does hold every other secret
this tool owns; that is what file permissions and backups are for.)
"""

import hashlib
import hmac
import re
import secrets
import threading

from werkzeug.security import check_password_hash, generate_password_hash

from services.accounts.errors import AccountError

#: What may become a username. It never becomes a path segment (the data folder is named after the
#: server-generated id), but it is still held to a shape that reads unambiguously in a log line and
#: in the management table.
USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,32}$')

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128

#: Five failures lock the account; each further failure doubles the wait, capped at an hour.
FAILURES_BEFORE_LOCK = 5
LOCK_SECONDS_BASE = 15 * 60
LOCK_SECONDS_MAX = 60 * 60

_dummy_lock = threading.Lock()
_dummy_hash = ''


def validate_username(username) -> str:
    """The one spelling a username is stored and compared under (trimmed; case fold at SQLite)."""
    text = str(username or '').strip()
    if not USERNAME_RE.match(text):
        raise AccountError('accounts.usernameInvalid')
    return text


def validate_password(password, username: str = '') -> str:
    text = str(password or '')
    if len(text) < MIN_PASSWORD_LENGTH:
        raise AccountError('accounts.passwordTooShort', n=MIN_PASSWORD_LENGTH)
    if len(text) > MAX_PASSWORD_LENGTH:
        raise AccountError('accounts.passwordTooLong', n=MAX_PASSWORD_LENGTH)
    if username and text.lower() == str(username).strip().lower():
        raise AccountError('accounts.passwordSameAsUsername')
    return text


def hash_password(password: str) -> str:
    return generate_password_hash(password, method='scrypt')


def verify_password(password, password_hash) -> bool:
    """``False`` for a mangled hash rather than an exception: a corrupt row refuses the login."""
    try:
        return check_password_hash(str(password_hash or ''), str(password or ''))
    except (ValueError, TypeError):
        return False


def burn_unknown_password(password) -> None:
    """Spend the same hashing time on an unknown username, so timing does not say "no such user"."""
    global _dummy_hash
    if not _dummy_hash:
        with _dummy_lock:
            if not _dummy_hash:
                _dummy_hash = hash_password('dummy-password-not-used')
    verify_password(password, _dummy_hash)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token) -> str:
    return hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def token_matches(given, expected) -> bool:
    return hmac.compare_digest(str(given or ''), str(expected or ''))


def lock_seconds(failures: int) -> int:
    """How long the Nth consecutive failure locks the account (0 below the threshold)."""
    if failures < FAILURES_BEFORE_LOCK:
        return 0
    return min(LOCK_SECONDS_BASE * (2 ** (failures - FAILURES_BEFORE_LOCK)), LOCK_SECONDS_MAX)
