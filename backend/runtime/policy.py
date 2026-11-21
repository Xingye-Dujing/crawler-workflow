"""Who may act on the machine itself, as opposed to on their own data.

The server is a local single-user tool that can also host accounts. Some doors do not touch an
account's own tree at all: they read or change *the box* — host paths and settings, the shared
lexicon and component catalog, the program's own update, the script library, the filesystem picker
and the command runner behind the AI workspace. On a single-user checkout every one of them is the
owner's own business; once accounts exist, one ordinary account must not be able to read another
account's tree or move every other account's browser, driver or proxy.

This module is the ONE answer to that question. ``api/settings``, ``api/lexicon``,
``api/components``, ``api/update``, ``api/ai`` and ``ai/workspace`` all asked it separately before
(three copies of ``accounts_mode() and not is_admin()`` plus the AI workspace's own
``CLOUD_MODE``-only check, which left that door open on a shared host). A caller asks here, and the
answer stays honest for a request and for a run thread alike because
:func:`runtime.account_context.current` is the same identity every lower layer uses.
"""

from __future__ import annotations

from runtime import account_context


def accounts_on() -> bool:
    """Whether this process keeps an account registry (and therefore asks for a login)."""
    from services.accounts.service import accounts_mode

    return bool(accounts_mode())


def may_administer_machine() -> bool:
    """Whether this caller may read or change machine-wide state.

    No registry means the login-free local owner, who may do everything. With a registry, only an
    administrator may: a missing identity is a refusal, never a wildcard.
    """
    if not accounts_on():
        return True
    account = account_context.current()
    return bool(account is not None and account.is_admin)


def machine_refusal_key() -> str:
    """The catalogue key a refused caller is answered with (same sentence on every panel)."""
    return 'accounts.adminRequired'
