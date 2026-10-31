"""Who a unit of work speaks for: the one place a request, a run or a scheduled fire says so.

The server is a local single-user tool that can also host several accounts. Rather than thread a
``user_id`` through a hundred route signatures, the identity is a context variable: a Flask request
binds it in ``before_request``, a run worker and the scheduler bind it around their own body, and
everything below — path resolution (``runtime/paths.py``), store selection (``runtime/stores.py``),
the dataset cache — asks :func:`current`.

Why ``ContextVar`` and not Flask's ``g``: the run worker and the scheduler clock are plain threads
that never see a request, and a cache or a store must not be able to import Flask to answer "which
account is this". A context variable is copied into the threads those helpers start and is reset by
``token`` in ``finally``, so an exception cannot leave a context behind.

``None`` is meaningful: no account bound means the local, login-free owner — the checkout-level
``data/`` tree, exactly how the app behaved before accounts existed.
"""

import contextlib
import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    """The identity every layer agrees on. Never carries a password or a password hash."""

    user_id: str
    username: str
    role: str = 'user'
    must_change_password: bool = False
    #: The session's CSRF token, handed to the page through ``/api/config``. Empty when the
    #: account was reconstructed outside a session (tests, scheduled work); no request is then
    #: asking the token question.
    csrf_token: str = ''

    @property
    def is_admin(self) -> bool:
        return self.role == 'admin'


_current: contextvars.ContextVar[Account | None] = contextvars.ContextVar('current_account', default=None)


def current() -> Account | None:
    """The account bound to this thread/task, or ``None`` for the local owner."""
    return _current.get()


def scope_key() -> str:
    """The key every per-account cache and store dictionary is filed under.

    ``'system'`` is the local owner's scope; an account's key is its immutable ``user_id`` —
    never the username, which can be changed.
    """
    account = current()
    return account.user_id if account is not None else 'system'


def bind(account: Account | None):
    """Set the context and return the reset token. Callers reset it in ``finally``."""
    return _current.set(account)


def unbind(token) -> None:
    """Restore the previous context. Safe to call twice: ``ContextVar.reset`` is not, so the
    caller owns exactly one token per bind and this helper exists to say so."""
    with contextlib.suppress(ValueError, RuntimeError):
        _current.reset(token)


def clear() -> None:
    """Forget the identity on this thread/task (the test harness, and a worker's final step)."""
    _current.set(None)


@contextlib.contextmanager
def use(account: Account | None):
    """Run a block as *account* (``None`` = the local owner), restoring the previous one after."""
    token = _current.set(account)
    try:
        yield account
    finally:
        with contextlib.suppress(ValueError, RuntimeError):
            _current.reset(token)
