"""Which account may use which extension contribution.

A provider/tool/code pack registers into the process-wide tables every route reads
(``PROVIDERS``/``tools.TOOLS``/``skills.BUILTIN``), and installing one is therefore a
machine-level write (``api/ai.py`` refuses a non-administrator when accounts are on). Visible,
however, is a different question from installed: one account's HTTP tool posts that account's
conversation arguments to a host only its installer approved, and one account's provider can
call an endpoint another account never chose. A contribution registered by a SIGNED-IN account
therefore stays inside that account; the product's own contributions (and anything registered
without an account bound, the pre-accounts local owner) are everyone's.

This module is a leaf on purpose: ``plugins``, ``tools``, the provider registry and ``skills``
all import it, and it must never import any of them.
"""

import threading

#: ``(kind, name) -> scope_key``. A missing key means "the product's own" — every account may
#: use it. Values are ``account_context.scope_key()`` (``'system'`` for the local owner).
_SCOPES: dict[tuple[str, str], str] = {}
_LOCK = threading.Lock()


def claim(kind: str, name: str, scope: str) -> None:
    """Record that ``scope`` registered this contribution (a no-op for the system scope)."""
    key = (str(kind), str(name))
    with _LOCK:
        if str(scope) == 'system':
            _SCOPES.pop(key, None)
        else:
            _SCOPES[key] = str(scope)


def release(kind: str, name: str) -> None:
    """Forget one contribution's owner (uninstall/disable)."""
    with _LOCK:
        _SCOPES.pop((str(kind), str(name)), None)


def owner(kind: str, name: str) -> str:
    """The scope that registered this contribution, or ``''`` when it is the product's own."""
    with _LOCK:
        return _SCOPES.get((str(kind), str(name)), '')


def visible(kind: str, name: str, scope: str) -> bool:
    """Whether ``scope`` may see/use this contribution.

    A built-in answers True for everyone; a plugin answers True only in the scope that installed
    it. ``scope`` is passed in rather than resolved here so a caller that already knows the
    account (a run worker, a request) does not depend on this module importing the context.
    """
    registered = owner(kind, name)
    return not registered or registered == str(scope)
