"""Ask each platform whether the session we hold still works — *before* the run.

The Cookie panel used to answer this question by asking the user: 「COOKIE 是否已长
时间未更新？」 on every run, which is a person guessing from memory about the one
thing a browser can check for them. This module checks instead, so the panel can
refuse a run that would die at a login wall an hour deep, and stay silent about a
run that will not.

**Three answers stay three, because the user's next action differs and a merged one
costs a wasted re-login.** That split is the whole reason the crawler keeps
``login_wall`` apart from ``risk_blocked`` (:func:`crawlers.base.Crawler.check_intercept`),
and this module inherits it rather than inventing a second opinion:

``expired``     the probe page answered with a login wall — the session is dead, and
                with the setting on the run is refused until it is refreshed.
``valid``       the page came back as content.
``unknown``     timeout, risk control, a browser that would not start, a profile held
                by another browser. **Never reported as expired**: a headless probe
                that zhihu answers with 40362 has told us nothing about the cookie,
                and blocking on it would send the user to log in over a session that
                is fine. Unknown never blocks the run — it says "could not check".

The remaining three verdicts are decided without buying a browser: ``nocookie`` (no
saved file *and* no profile session to test), ``nologin`` (WeChat, which is crawled
without any session) and ``notcrawlable`` (Instagram, capture-only).

A probe is a real page load, so it is bounded (``COOKIE_PREFLIGHT_TIMEOUT``), capped
in parallel (``COOKIE_PREFLIGHT_MAX_PARALLEL``) and **cached**
(``COOKIE_PREFLIGHT_TTL``) — and the cache is dropped the moment anything could have
changed it: saving, deleting or capturing a cookie calls :func:`invalidate`.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import browser_profiles

from config import Config
from crawlers import crawler_class, is_crawlable
from i18n import t
from services.cookie_manager import CookieManager

logger = logging.getLogger(__name__)

VALID = 'valid'
EXPIRED = 'expired'
UNKNOWN = 'unknown'
NO_COOKIE = 'nocookie'
NO_LOGIN = 'nologin'
NOT_CRAWLABLE = 'notcrawlable'

#: The verdicts a run may not start on. Kept as one tuple because the endpoint and the
#: browser both have to agree, and 「过期就不得执行」 is the user's decision, not a
#: detail to be rediscovered in two places.
BLOCKING = (EXPIRED, NO_COOKIE)

_cache: dict[str, dict] = {}
_lock = threading.Lock()


def reset() -> None:
    """Forget every cached verdict. Test isolation, never a runtime operation."""
    with _lock:
        _cache.clear()


def invalidate(platform: str = None) -> None:
    """Drop the cached verdict for one platform, or for all of them.

    Called by every path that can change a session — a pasted save, a login capture,
    a deletion — because a five-minute cache that outlives the re-login it was
    refreshed by would refuse a run the user *just* fixed, with no way to see why.
    """
    with _lock:
        if platform is None:
            _cache.clear()
        else:
            _cache.pop(str(platform), None)


def cached(platform: str) -> dict | None:
    """The stored verdict for *platform* while it is still young enough to quote."""
    with _lock:
        entry = _cache.get(str(platform))
        if not entry:
            return None
        if time.monotonic() - entry['at'] > Config.COOKIE_PREFLIGHT_TTL:
            _cache.pop(str(platform), None)
            return None
        return dict(entry)


def _remember(platform: str, verdict: dict) -> None:
    """Cache only the two verdicts that are facts about the session.

    An ``unknown`` is not one: it says the check did not happen, and reusing it for
    five minutes would keep a run going on an answer the site never gave. Re-asking
    costs one bounded page load, which is what the first press already paid.
    """
    if verdict.get('state') not in (VALID, EXPIRED):
        return
    with _lock:
        _cache[str(platform)] = {**verdict, 'at': time.monotonic()}


def classify_probe(facts: dict) -> str:
    """``valid`` / ``expired`` / ``unknown``, from the bare facts a browser came back with.

    The order is the whole point: a failure to observe outranks a wall, because an
    unverifiable page is not evidence of a dead cookie. Whether the page was a wall or
    risk control is :meth:`crawlers.base.Crawler.check_intercept`'s judgement, and this
    function inherits it rather than re-reading the page.
    """
    if facts.get('error'):
        return UNKNOWN
    if facts.get('login_wall'):
        return EXPIRED
    if facts.get('risk_blocked'):
        return UNKNOWN
    return VALID


def record(platform: str, facts: dict) -> dict:
    """Cache a verdict somebody else already measured and reported.

    The panel's 验证 Cookie button asks this same question of the same browser, so a
    user who just watched it answer 「已失效」 should not pay for a second probe to be
    told so again — and a stale 「可用」 must not survive the check that contradicted it.
    """
    verdict = _verdict(str(platform), classify_probe(facts), probed=True)
    _remember(platform, verdict)
    return verdict


#: One sentence per state, from the backend catalogue. An unmapped state falls back to
#: the 「无法核对」 wording rather than raising: a verdict the browser cannot name must
#: not be the reason a run fails to start.
_REASONS = {
    VALID: 'cookie.pre.valid',
    EXPIRED: 'cookie.pre.expired',
    UNKNOWN: 'cookie.pre.unknown',
    NO_COOKIE: 'cookie.verify.noCookie',
    NO_LOGIN: 'cookie.pre.noLogin',
    NOT_CRAWLABLE: 'cookie.pre.notCrawlable',
}


def _reason_key(state: str) -> str:
    return _REASONS.get(state, 'cookie.pre.unknown')


def describe(verdict: dict) -> str:
    """The user-facing sentence for one verdict, rendered from the backend catalogue.

    Server-side on purpose: the wording belongs with the crawler that decided it, and
    a copy of these six sentences in the browser's own dictionary is how the two
    drift apart (the same reason ``/api/cookies/flow`` ships its guidance already
    translated).
    """
    platform = str(verdict.get('platform') or '')
    text = t(str(verdict.get('why_key') or _reason_key(str(verdict.get('state') or ''))), platform=platform)
    detail = str(verdict.get('detail') or '')
    return f'{text}（{detail}）' if detail else text


def _verdict(platform: str, state: str, *, detail: str = '', why_key: str = '', probed: bool = False) -> dict:
    return {
        'platform': platform,
        'state': state,
        'blocking': state in BLOCKING,
        'detail': detail,
        'why_key': why_key or _reason_key(state),
        'probed': probed,
    }


def _needs_session(platform: str) -> bool:
    """Whether this platform's crawl is served to a logged-in browser at all.

    Read off the class: WeChat carries no ``login_url`` precisely because its
    article bodies need no session, so a pre-flight that demanded a cookie there
    would refuse a crawl that has never needed one.
    """
    return bool(getattr(crawler_class(platform), 'login_url', ''))


def _has_session_to_test(platform: str, use_profile: bool = None) -> bool:
    """Whether anything could carry this platform's login.

    The saved file is the obvious source, but a *used profile* is a second one: since
    a profile imports the cookie file once and is never re-planted, a session lives in
    the directory from then on, and :func:`browser_profiles` ignores the file
    completely. Deleting a snapshot (#111) therefore does not log that device out — so
    this must not answer "nothing to test" while the profile is in play.
    """
    if CookieManager(Config.COOKIE_DIR).exists(platform):
        return True
    active = browser_profiles.is_enabled() if use_profile is None else bool(use_profile)
    return bool(active and browser_profiles.is_used(platform))


def knows(platform: str) -> bool:
    """Whether this process has any opinion at all about *platform*.

    Two registries answer that, and they are deliberately different lists:
    ``CookieManager.PLATFORMS`` is who can *hold a saved session* and the crawler
    registry is who can be *crawled*. WeChat is in the second and not the first — it
    needs no login — so a name either side recognises is worth a verdict, and a name
    neither recognises gets no browser. That also makes the second list's word
    final: ``instagram`` can be logged into but not crawled, so it is never blocking.
    """
    platform = str(platform or '')
    return bool(platform) and (CookieManager.is_supported(platform) or crawler_class(platform) is not None)


def _probe_live(platform: str, *, use_profile: bool = None) -> dict:
    """One bounded page load in the browser the run would have used.

    Isolated as a function so the whole of ``check`` below — the cache, the deadline,
    the parallelism — is testable without a browser, while the crawler facts still
    come from the real :meth:`Crawler.diagnose` in the device tier.
    """
    from crawlers import get_crawler

    try:
        # ``headless=False`` and ``for_login=True`` are the same two choices
        # ``_cookie_verify_worker`` makes, and for the same measured reason: this
        # machine's risk control answers a headless content page differently from a
        # real window (Zhihu in particular), and a probe that blamed the cookie for a
        # headless block would refuse runs over a session that is fine. Keeping the
        # mode identical is also what stops the panel's 验证 button and this gate from
        # disagreeing about one platform — the window is the price of the guarantee.
        crawler = get_crawler(
            platform,
            headless=False,
            cookie_dir=Config.COOKIE_DIR,
            for_login=True,
            use_profile=use_profile,
        )
    except Exception as e:
        # A browser that would not start (no chromedriver, a profile Chrome refuses to
        # share) is not a probe that found a dead cookie.
        return {'error': str(e)[:200]}
    try:
        facts = crawler.diagnose('')
        return {
            'login_wall': bool(facts.get('login_wall')),
            'risk_blocked': bool(getattr(crawler, 'risk_blocked', False)),
        }
    except Exception as e:
        return {'error': str(e)[:200]}
    finally:
        # The probe owns its browser even when the page load failed: a Chrome left open
        # by a check nobody asked for is worse for the user than the check itself, and
        # it would keep holding the platform's profile.
        try:
            crawler.close()
        except Exception as e:
            logger.debug('cookie probe browser did not close cleanly: %s', e)


def probe(platform: str, *, use_profile: bool = None, fresh: bool = False) -> dict:
    """The verdict for one platform, from cache when a recent one exists."""
    platform = str(platform or '')
    if not fresh:
        hit = cached(platform)
        if hit:
            # ``cached=True`` is what lets the console say "reusing the check from
            # N minutes ago" instead of printing a verdict that looks freshly earned.
            # ``probed`` goes with it: this answer did not buy a browser just now, and
            # a caller that reported otherwise would claim a check it never ran.
            hit['cached'] = True
            hit['probed'] = False
            return hit

    if not knows(platform):
        return _verdict(platform, UNKNOWN, detail=t('cookie.pre.notListed', platform=platform))
    if not is_crawlable(platform):
        return _verdict(platform, NOT_CRAWLABLE)
    if not _needs_session(platform):
        return _verdict(platform, NO_LOGIN)
    if not _has_session_to_test(platform, use_profile):
        return _verdict(platform, NO_COOKIE)
    profile = browser_profiles.profile_dir_for(platform, enabled=use_profile)
    if profile and browser_profiles.is_busy(profile):
        # Something already holds that browser — an in-flight run, or the panel's own
        # login window. Waiting here would park the press of Execute behind a wait
        # whose own timeout is longer than any crawl, and the run that owns the
        # profile is already the best evidence about the session there is.
        return _verdict(platform, UNKNOWN, detail=t('cookie.pre.busy', platform=platform))
    facts = _probe_live(platform, use_profile=use_profile)
    verdict = _verdict(platform, classify_probe(facts), probed=True)
    if verdict['state'] == UNKNOWN and not facts.get('error'):
        verdict['detail'] = t('cookie.pre.riskControl')
    elif verdict['state'] == UNKNOWN:
        verdict['detail'] = facts['error']
    _remember(platform, verdict)
    return verdict


def check(platforms, *, use_profile: bool = None, fresh: bool = False) -> dict:
    """Probe every platform of *platforms* at once and return ``{platform: verdict}``.

    The parallelism is capped rather than per-platform because the cost is a browser
    each: a canvas with six sources must not open six Chromes at the user's press of
    one button, and four is already more windows than a probe should be allowed to
    take over the desktop.

    A platform whose probe outlived ``COOKIE_PREFLIGHT_TIMEOUT`` is answered
    ``unknown`` here rather than left out of the result: the caller branches on the
    key being present, and a missing key would read as "no opinion". Its browser
    thread is left to finish and close itself — it may still hold that profile for a
    while, and the run that starts behind it then waits on
    :func:`browser_profiles.acquire_profile`, which is bounded and reports the
    directory it is stuck on. That is a slower start, never a corrupted session.
    """
    names = list(dict.fromkeys(str(p or '') for p in (platforms or []) if str(p or '')))
    answers: dict[str, dict] = {}
    if not names:
        return answers
    workers = max(1, min(len(names), int(Config.COOKIE_PREFLIGHT_MAX_PARALLEL)))
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {pool.submit(probe, name, use_profile=use_profile, fresh=fresh): name for name in names}
        deadline = time.monotonic() + Config.COOKIE_PREFLIGHT_TIMEOUT
        for future, name in futures.items():
            remaining = max(0.0, deadline - time.monotonic())
            try:
                answers[name] = future.result(timeout=remaining)
            except Exception:
                answers[name] = _verdict(
                    name,
                    UNKNOWN,
                    detail=t('cookie.pre.timeout', n=int(Config.COOKIE_PREFLIGHT_TIMEOUT)),
                )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return answers
