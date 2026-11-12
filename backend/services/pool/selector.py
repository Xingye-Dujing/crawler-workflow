"""Pick the next (account, exit) pair a pool-mode node should crawl as.

The order answers one question: "what is most likely to work and least recently spent?" —
healthy first, then least-recently-attempted, then creation order. Creation order is read
from the cookie files (:meth:`CookieManager.accounts_in_order`), so a user who added
work-then-home still gets work first while both are fresh.

Two details that are easy to get wrong and expensive to debug:

* **A candidate is a PAIR.** Two parallel nodes must not both pick account A just because A
  ranks first; a short in-process lease on both halves of the pair makes the second caller
  take the next one. That is the whole reason a parallel canvas can use a pool at all.
* **A dead exit does not make the account dead.** When an account's bound exit is benched,
  another healthy exit is bound and the same login is offered again — "换 IP 不换号". Only
  when no exit can serve it (and direct fallback is refused) does the account leave the
  candidate list.
"""

import threading
import time
import uuid
from dataclasses import dataclass

from runtime import paths
from runtime.settings import get_setting
from sessions import session_state
from sessions.cookies import CookieManager

from services.pool import egress, store
from services.pool import health as pool_health

#: How long a claim holds a pair without a verdict. Long enough for a real crawl, short
#: enough that a process killed at 3 a.m. does not hide the pair for the next day. A run
#: releases its claim in a ``finally``, so this only matters after a crash.
LEASE_SECONDS = 2 * 60 * 60

_LOCK = threading.Lock()
_LEASES: dict[tuple, tuple] = {}

#: The account field's "rotate" value. ``@`` cannot appear in an account label
#: (``ACCOUNT_RE``), so this can never collide with a login somebody typed.
POOL_VALUE = '@pool'


@dataclass(frozen=True)
class Candidate:
    """One usable combination: which login, and which exit it leaves through."""

    platform: str
    account: str
    exit_id: str = ''
    exit_name: str = ''
    proxy: dict = None

    def label(self) -> str:
        """How a console line names this pair, without ever printing a credential."""
        return egress.describe(self.proxy or {})


def is_pool_value(value) -> bool:
    """Whether the node's 账号 parameter means "choose from the pool" rather than a login.

    The sentinel contains ``@``, which no account label may contain (``ACCOUNT_RE``), so it
    can never collide with a user-typed account named "pool". It is a storage value, not a
    name: nothing may hand it to ``CookieManager.path_for``.
    """
    return str(value or '').strip() == POOL_VALUE


def pool_accounts(platform: str) -> list:
    """Every account of this platform that holds a session, in creation order."""
    manager = CookieManager(paths.active().cookie_dir)
    return [name for name in manager.accounts_in_order(platform) if session_state.has_session(platform, name)]


def _accounts_by_health(platform: str) -> list:
    """Session-holding accounts whose own health is OK, least-recently-attempted first."""
    rows = []
    for index, account in enumerate(pool_accounts(platform)):
        health = store.get_health('account', platform, account)
        if pool_health.effective_state(health) != 'ok':
            continue
        rows.append((float(health.get('last_attempt_at') or 0), index, account))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [account for _stamp, _index, account in rows]


def _exit_for(platform: str, account: str, exclude=(), bind: bool = True) -> tuple:
    """``(exit_id, proxy)`` for this account, or ``('', None)`` when direct is allowed.

    A bound exit that no longer serves this platform is treated like a missing binding. A
    read-only caller (the pre-run gate's snapshot) passes ``bind=False``: deciding a verdict
    must not rewrite where an account lives.
    """
    bound = store.binding_exit_id(platform, account)
    if bound:
        spec = store.exit_secret(bound)
        usable = spec and spec.get('enabled') and _serves(spec, platform)
        if usable and pool_health.effective_state(store.get_health('exit', platform, bound)) == 'ok':
            return bound, spec
    if not egress.exits_for(platform):
        # No IP pool configured at all: the feature is only an account pool.
        return '', None
    choice = egress.healthy_exit(platform, exclude=exclude)
    if not choice:
        if bool(get_setting('pool_allow_direct_fallback')):
            return '', None
        return None, None
    if bind and bound != choice['id']:
        # Moving the binding is the deliberate "the IP died, the login did not" action.
        store.bind(platform, account, choice['id'])
    return choice['id'], store.exit_secret(choice['id'])


def _serves(spec: dict, platform: str) -> bool:
    allowed = spec.get('allowed_platforms') or []
    return not allowed or platform in allowed


def candidates(platform: str, exclude_accounts=()) -> list:
    """Every currently usable pair, best first. No side effects, no leases."""
    exclude = {str(a) for a in (exclude_accounts or ())}
    out = []
    for account in _accounts_by_health(platform):
        if account in exclude:
            continue
        exit_id, proxy = _exit_for(platform, account)
        if exit_id is None:
            continue
        out.append(Candidate(platform, account, exit_id or '', (proxy or {}).get('name', ''), proxy))
    return out


def claim(platform: str, exclude_accounts=()) -> Candidate | None:
    """Lease the best free pair, or None when the pool has nothing usable right now."""
    now = time.time()
    with _LOCK:
        started = list(_LEASES.items())
        for key, (_token, expiry) in started:
            if expiry <= now:
                _LEASES.pop(key, None)
        for candidate in candidates(platform, exclude_accounts):
            account_key = ('account', platform, candidate.account)
            if account_key in _LEASES:
                continue
            # Only the ACCOUNT is leased. One exit behind several accounts is a normal
            # setup (one IP, several logins), and locking it would make a pool of five
            # accounts crawl one at a time for no reason a site cares about.
            _LEASES[account_key] = (uuid.uuid4().hex, now + LEASE_SECONDS)
            try:
                store.touch('account', platform, candidate.account)
                if candidate.exit_id:
                    store.touch('exit', platform, candidate.exit_id)
            except Exception:
                # A failed write must not hide the account behind a two-hour lease.
                _LEASES.pop(account_key, None)
                raise
            return candidate
    return None


def release(candidate: Candidate | None) -> None:
    """Give a pair back. Safe with None, and safe twice."""
    if candidate is None:
        return
    with _LOCK:
        _LEASES.pop(('account', candidate.platform, candidate.account), None)


def reset_leases() -> None:
    """Forget every lease. Test isolation; a running worker's release then finds nothing."""
    with _LOCK:
        _LEASES.clear()


def snapshot(platform: str) -> dict:
    """The pool's state for one platform, shaped for the pre-run gate and the panel.

    ``usable`` counts the pairs a run could actually start with right now, which is the only
    number that decides whether a pool-mode node may run. ``cooling``/``disabled`` are
    reported separately because the user's next action differs: wait, or go and log in.
    """
    accounts = pool_accounts(platform)
    rows = []
    usable = 0
    for account in accounts:
        health = store.get_health('account', platform, account)
        state = pool_health.effective_state(health)
        exit_id, proxy = _exit_for(platform, account, bind=False)
        if state == 'ok' and exit_id is not None:
            usable += 1
        rows.append(
            {
                'account': account,
                'state': state,
                'reason': str(health.get('reason') or ''),
                'cool_until_local': str(health.get('cool_until_local') or ''),
                'strikes': int(health.get('strikes') or 0),
                'exit_id': exit_id or '',
                'exit_name': str((proxy or {}).get('name') or ''),
                'exit_state': (
                    pool_health.effective_state(store.get_health('exit', platform, exit_id)) if exit_id else 'ok'
                ),
            }
        )
    return {'platform': platform, 'accounts': rows, 'total': len(accounts), 'usable': usable}
