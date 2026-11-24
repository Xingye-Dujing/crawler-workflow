"""What a session answer MEANS, and the one cache slot it lives in.

``sessions.preflight`` is the machinery — a probe opens a browser, a deadline bounds it, a
cache spares the next press. This module is the **judgement** that machinery carries: which
word a page's bare facts turn into, which of those words blocks a run, and which
(scope, platform, account, profile-mode) slot the answer is filed under. Kept apart because
these are the rules a reader has to be able to check without a browser: “a failure to observe
outranks a wall”, “a 300-second-old answer is no longer quotable”, “``default`` and blank are
one slot”.

**Pure by contract**: no browser, no file, no setting, no clock. The caller resolves the
account scope, the profile mode and ``now`` and hands them in — which is what lets the TTL
boundary and the slot fold be tested without a cookie directory or a five-minute wait.
"""

from sessions import naming

VALID = 'valid'
EXPIRED = 'expired'
UNKNOWN = 'unknown'
NO_COOKIE = 'nocookie'
NO_LOGIN = 'nologin'
NOT_CRAWLABLE = 'notcrawlable'
#: The pool benched this login/exit; a run would spend an attempt the whole feature exists to
#: avoid. It reads as its own verdict because the user's next action ("wait", or "unfreeze in
#: the pool panel") is neither "log in again" nor "try anyway".
COOLING = 'cooling'

#: The verdicts a run may not start on. Kept as one tuple because the endpoint and the browser
#: both have to agree, and “过期就不得执行” is the user's decision, not a detail to be
#: rediscovered in two places.
BLOCKING = (EXPIRED, NO_COOKIE, COOLING)

#: One sentence per state, from the backend catalogue. An unmapped state falls back to the
#: “无法核对” wording rather than raising: a verdict the browser cannot name must not be the
#: reason a run fails to start.
REASONS = {
    VALID: 'cookie.pre.valid',
    EXPIRED: 'cookie.pre.expired',
    UNKNOWN: 'cookie.pre.unknown',
    NO_COOKIE: 'cookie.verify.noCookie',
    NO_LOGIN: 'cookie.pre.noLogin',
    NOT_CRAWLABLE: 'cookie.pre.notCrawlable',
    COOLING: 'cookie.pre.cooling',
}


def reason_key(state: str) -> str:
    """The catalogue key for one state, falling back to the “could not check” sentence."""
    return REASONS.get(state, REASONS[UNKNOWN])


def is_blocking(state: str) -> bool:
    """Whether a run may not start on this state."""
    return state in BLOCKING


def classify_probe(facts: dict) -> str:
    """``valid`` / ``expired`` / ``unknown``, from the bare facts a browser came back with.

    The order is the whole point: a failure to observe outranks a wall, because an
    unverifiable page is not evidence of a dead cookie. Whether the page was a wall or risk
    control is :meth:`crawlers.core.crawler.Crawler.check_intercept`'s judgement, and this
    function inherits it rather than re-reading the page.

    ``unreachable`` is checked before even ``login_wall``, and this is the one place its cost
    is visible: verdicts are *cached*. A browser that wrote its own error page never showed
    the site this session, so answering “Cookie 可用” here would park a claim about a cookie
    in the path of every run that starts — with no probe behind it and no way for the user to
    see that nothing was tested.
    """
    if facts.get('error') or facts.get('unreachable'):
        return UNKNOWN
    if facts.get('login_wall'):
        return EXPIRED
    if facts.get('risk_blocked'):
        return UNKNOWN
    return VALID


def cache_key(scope, platform: str, account: str = '', use_profile: bool = False) -> tuple:
    """The ONE key a verdict is stored under: ``(scope, platform, file segment, profile mode)``.

    The scope comes first: two accounts can hold *different* sessions for the same platform
    and the same account label, and a verdict is about one of those files. Keying by platform
    alone let one account's “已失效” refuse the other's healthy run.

    The account is folded to its FILE segment (``default`` and blank are one login), because
    two spellings of one login landing in two cache slots is how a probe runs a browser twice
    and answers “没有登录” from the slot nobody filled.

    ``use_profile`` is the third dimension, and it was missing: which session the probe READS
    depends on it — with browser profiles on it is ``chrome_profile/<platform>/<account>``,
    with them off it is the cookie file. A run with profiles enabled therefore cached its
    verdict under a key a later run with profiles disabled also looked in, and the second run
    was gated on a session it does not use (or cleared by a wall the other one hit).
    """
    return str(scope), str(platform), naming.account_segment(account), bool(use_profile)


def cacheable(state: str) -> bool:
    """Cache only the two verdicts that are facts about the session.

    An ``unknown`` is not one: it says the check did not happen, and reusing it for five
    minutes would keep a run going on an answer the site never gave. Re-asking costs one
    bounded page load, which is what the first press already paid.
    """
    return state in (VALID, EXPIRED)


def is_fresh(stored_at, now, ttl) -> bool:
    """Whether a verdict stamped *stored_at* may still be quoted at *now*.

    The boundary is inclusive at the TTL (`age == ttl` is still fresh) because a settings
    value is a floor, not a race: a caller that read 300 s and waited exactly 300 s must not
    lose the answer to monotonic-clock drift.
    """
    return (now - stored_at) <= float(ttl)
