"""Turn what a browser observed into a timed verdict about the pair that produced it.

The rule this module exists to keep: **only a failure that points at one side cools that
side.** A login wall is the session's problem, a captcha/risk page is first of all the
exit's problem, and a refused navigation or a timeout is evidence about neither — cooling
an account for a dead ethernet cable burns the very resource the pool is short of. That is
the same split :mod:`sessions.preflight` already makes between ``expired`` and ``unknown``,
and this module inherits it rather than inventing a second opinion.

Two scopes, one state machine (:mod:`services.pool.store`): an ACCOUNT can be walled, an
EXIT can be banned, and each is scoped to a platform because the same login and the same
IP are judged separately by each site.
"""

import time

from runtime.settings import get_setting

from services.pool import store

LOGIN_WALL = 'login_wall'
RISK = 'risk'
NETWORK = 'network'

#: The failures a pool may answer by trying another account. Both are the site answering
#: "not this session", which is exactly the situation a second login is for.
ROTATABLE = (LOGIN_WALL, RISK)

#: A risk page is evidence against the EXIT first. The account is benched briefly so the
#: same run does not immediately re-offer it, but a good login is not thrown away for two
#: hours because one IP was flagged — a second strike on this account earns the full term.
ACCOUNT_SUSPECT_SECONDS = 600


def reason_of(facts: dict) -> str:
    """Which pool reason these crawler facts name, or ``''`` for "no attributable failure".

    ``unreachable`` and a bare ``error`` are folded onto the network reason because both say
    the site was never given a chance to answer. A handler that reports neither is a
    success as far as the pool is concerned — a short table is an *under-collection*, which
    the executor already reports by name and which says nothing about the session.
    """
    facts = facts or {}
    if facts.get('login_wall'):
        return LOGIN_WALL
    if facts.get('risk_blocked'):
        return RISK
    if facts.get('unreachable') or facts.get('error'):
        return NETWORK
    return ''


def is_rotatable(reason: str) -> bool:
    return str(reason or '') in ROTATABLE


def cooldown_for(reason: str, strikes: int = 0) -> float:
    """How long one reason benches its subject, from the declared settings.

    Escalation is OFF by default and caps at a week: a login that walks back into the same
    wall after every timeout is the case for it, while the default stays the plain two-hour
    answer the pool was asked for.
    """
    if reason in (LOGIN_WALL, RISK):
        seconds = float(get_setting('pool_cooldown_seconds') or 0)
    elif reason == NETWORK:
        seconds = float(get_setting('pool_network_cooldown_seconds') or 0)
    else:
        return 0.0
    if seconds > 0 and strikes > 0 and bool(get_setting('pool_escalate')):
        seconds = min(seconds * (2 ** min(strikes, 3)), 604800.0)
    return seconds


def effective_state(row: dict, now: float = None) -> str:
    """``ok`` / ``cooling`` / ``disabled``, with a cooldown that ran out reading as ``ok``.

    Computed rather than swept by a background thread: a server that was switched off for a
    night must wake up with every expired cooldown already gone, and a sweeper is a second
    writer with its own chance to be wrong.
    """
    if not row:
        return 'ok'
    state = str(row.get('state') or 'ok')
    if state == 'disabled':
        return 'disabled'
    until = float(row.get('cool_until') or 0)
    if state == 'cooling' and until and until > (now if now is not None else time.time()):
        return 'cooling'
    return 'ok'


def observe(
    platform: str,
    account: str,
    facts: dict,
    *,
    exit_id: str = '',
    rows: int = 0,
    run_id: str = '',
    node_id: str = '',
) -> dict:
    """Record one browser attempt's verdict and return what it decided.

    Returned shape (the caller needs it to decide whether to rotate, and to word the console
    line): ``{reason, rotatable, scope, seconds, until_local}``. ``scope`` is
    ``account``/``exit``/``''``.
    """
    reason = reason_of(facts)
    answer = {'reason': reason, 'rotatable': is_rotatable(reason), 'scope': '', 'seconds': 0.0, 'until_local': ''}
    if not reason:
        # A real page answered. That is a measurement about both halves of the pair.
        if account:
            store.mark_ok('account', platform, account)
        if exit_id:
            store.mark_ok('exit', platform, exit_id)
        store.record_event(
            kind='ok',
            platform=platform,
            account=account,
            exit_id=exit_id,
            run_id=run_id,
            node_id=node_id,
            rows=rows,
        )
        return answer

    account_strikes = int(store.get_health('account', platform, account).get('strikes') or 0) if account else 0
    exit_strikes = int(store.get_health('exit', platform, exit_id).get('strikes') or 0) if exit_id else 0
    seconds = cooldown_for(reason, account_strikes if reason == LOGIN_WALL else exit_strikes)
    if reason == LOGIN_WALL:
        answer['scope'] = 'account'
        answer['seconds'] = seconds
        if account and seconds > 0:
            until = store.mark_cooldown('account', platform, account, seconds, reason, detail=_detail(facts))
            answer['until_local'] = until.get('cool_until_local', '')
    elif reason == RISK:
        answer['scope'] = 'exit' if exit_id else 'account'
        answer['seconds'] = seconds
        if exit_id and seconds > 0:
            until = store.mark_cooldown('exit', platform, exit_id, seconds, reason, detail=_detail(facts))
            answer['until_local'] = until.get('cool_until_local', '')
        if account:
            # The login is not condemned on one flagged IP; it is benched long enough that
            # this run cannot immediately hand it back, and a repeat earns the full term.
            current = store.get_health('account', platform, account)
            strikes = int(current.get('strikes') or 0)
            seconds_account = (
                seconds if strikes >= 1 else min(ACCOUNT_SUSPECT_SECONDS, seconds or ACCOUNT_SUSPECT_SECONDS)
            )
            if seconds_account > 0:
                store.mark_cooldown('account', platform, account, seconds_account, reason, detail=_detail(facts))
    elif reason == NETWORK:
        answer['scope'] = 'exit' if exit_id else ''
        answer['seconds'] = seconds
        if exit_id and seconds > 0:
            until = store.mark_cooldown('exit', platform, exit_id, seconds, reason, detail=_detail(facts))
            answer['until_local'] = until.get('cool_until_local', '')
    store.record_event(
        kind=reason,
        platform=platform,
        account=account,
        exit_id=exit_id,
        run_id=run_id,
        node_id=node_id,
        reason=reason,
        detail=_detail(facts),
        rows=rows,
    )
    return answer


def _detail(facts: dict) -> str:
    """The crawler's own word for what it hit, never a sentence this module invents."""
    text = str((facts or {}).get('error') or '').strip()
    return text[:300]
