"""The account/exit pool: which session to use next, and what it cost last time.

This package answers three questions for the rest of the program and owns nothing else:

* *may this node run at all?*  (:func:`snapshot`, :func:`candidates`)
* *which login + exit should this attempt use?*  (:func:`claim`)
* *what did that attempt prove?*  (:func:`observe`)

The state lives in ``data/pool.db`` of the signed-in account's tree, resolved per call
(:mod:`services.pool.store`). Rotation is applied by the executors; this package never
imports them, so the dependency direction stays ``nodes → pool → sessions``.
"""

from runtime.settings import get_setting
from sessions.cookies import CookieManager

from i18n import platform_label, t
from services.pool import egress, health, selector, store


def enabled() -> bool:
    """Whether pool mode is offered at all. Off leaves every existing canvas untouched."""
    return bool(get_setting('pool_enabled'))


def max_attempts() -> int:
    """How many different pairs one node may spend in one run."""
    try:
        return max(1, int(get_setting('pool_max_attempts') or 1))
    except (TypeError, ValueError):
        return 3


def claim(platform: str, exclude_accounts=()) -> selector.Candidate | None:
    return selector.claim(platform, exclude_accounts)


def release(candidate) -> None:
    selector.release(candidate)


def candidates(platform: str, exclude_accounts=()) -> list:
    return selector.candidates(platform, exclude_accounts)


def snapshot(platform: str) -> dict:
    return selector.snapshot(platform)


def observe(
    platform: str, account: str, facts: dict, *, exit_id: str = '', rows: int = 0, run_id: str = '', node_id: str = ''
) -> dict:
    return health.observe(platform, account, facts, exit_id=exit_id, rows=rows, run_id=run_id, node_id=node_id)


def account_word(account: str) -> str:
    """How a console line names one login: 默认账号 for ``default``, the typed name otherwise."""
    label_key, label_args = CookieManager.account_label_key(account)
    return t(label_key, **label_args) if label_key else str(account or '').strip()


def reason_word(reason: str) -> str:
    """The user-facing word for one cooling reason (the values are catalogue keys)."""
    key = {
        health.LOGIN_WALL: 'pool.reason.loginWall',
        health.RISK: 'pool.reason.risk',
        health.NETWORK: 'pool.reason.network',
    }.get(str(reason or ''), '')
    return t(key) if key else ''


def exhaustion_message(platform: str, tried: list) -> str:
    """The one sentence a node raises when every candidate has been spent.

    It is deliberately not "Cookie 已失效": that sends the user to re-take a login when what
    actually happened is that the whole pool is benched, and the two want different actions
    (wait for the clock vs. go and log in).
    """
    parts = []
    for item in tried or ():
        word = account_word(item.get('account') or '')
        reason = reason_word(item.get('reason') or '')
        until = str(item.get('until_local') or '')
        detail = ' · '.join(part for part in (reason, until) if part)
        parts.append(f'{word}（{detail}）' if detail else word)
    return t('pool.exhausted', platform=platform_label(platform), detail='；'.join(parts))


__all__ = [
    'Candidate',
    'account_word',
    'candidates',
    'claim',
    'egress',
    'enabled',
    'exhaustion_message',
    'health',
    'max_attempts',
    'observe',
    'reason_word',
    'release',
    'selector',
    'snapshot',
    'store',
]

Candidate = selector.Candidate
