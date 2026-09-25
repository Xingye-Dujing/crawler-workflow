"""Shared plumbing for the live-site tier.

Everything here really drives real Chrome against the real platforms with the
user's saved cookies — the tier is excluded by default (``live_site`` marker)
and selected explicitly:

    .venv/Scripts/python.exe -m pytest -q -m live_site     # every case, ~an hour
    .venv/Scripts/python.exe -m pytest -q -m live_quick    # one crawl per platform

The second line is the tier a change is supposed to be checked against: 51 real
crawls is not a gate anyone runs twice an hour, and a gate nobody runs is not a
gate. ``live_quick`` is a subset of ``live_site`` (``tests/unit/test_test_tiers.py``
pins that, and that every platform is still visited), so the full pass remains the
one that says "everything".

A missing or unreadable cookie file SKIPS that platform instead of failing:
the tier must stay runnable on machines without every login, while on this
machine all four platforms run for real. Volumes are deliberately tiny (3-5
rows) — the point is correctness of the pipeline, not scraping data.
"""

import contextlib
import json
import time
from pathlib import Path

import isolation_guard
import pytest

import settings_store

REPO_ROOT = Path(__file__).resolve().parents[2]
COOKIE_DIR = REPO_ROOT / 'data' / 'cookies'


def has_cookie(platform: str) -> bool:
    path = COOKIE_DIR / f'{platform}_cookies.json'
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(data, list) and len(data) > 0


#: Where this tier's browsers keep their own session, and it has to OUTLIVE the run.
#:
#: The root conftest sends every writable path into ``<tmp>/cixi_pytest/isolated-<pid>`` and
#: deletes that directory at import, so a live crawl started there begins in a brand-new profile
#: **every run** and has the saved cookie file replanted into it (``crawlers/__init__.py:97``).
#: That is the shape this account gets refused by: weibo re-issues ``SUB``/``SUBP`` on a logged-in
#: page load, so the saved pair stops being accepted once it has been used, and measuring it on
#: 2026-09-26 is what cost the USER their own session (docs/crawler_notes.md). A real run — the
#: user's — crawls from a profile that keeps its own jar, and that is the only difference between
#: "the tests get bounced to the login page" and "the user never sees that page".
#:
#: ``scratchpad/`` is gitignored, and this is deliberately NOT ``data/chrome_profile``: that
#: directory belongs to the user's own crawls, and a test session must not log into it, be logged
#: out of it, or contend with their browser for its single-writer lock.
LIVE_PROFILE_ROOT = REPO_ROOT / 'scratchpad' / 'live_profiles'


def live_attempts(platform: str) -> int:
    """How many times this tier may ask *platform* one question.

    Two everywhere but weibo, and one is the account's protection rather than a looser assertion:
    the second ask is the same refused endpoint seen again with the same saved credential, and it
    is the ACCOUNT that carries the flag (measured 2026-09-26, the night the retries were found to
    have cost the user their own session). A refusal there is asserted as a refusal — see
    ``test_live_weibo.py::test_visible_window_search_works_too`` — so nothing about strictness is
    traded away, only the repeat request.
    """
    return 1 if platform == 'weibo' else 2


def refresh_for_planting(platform: str) -> bool:
    """Does this platform's test profile need the saved file put into it again?

    This is the panel's own question, asked with the panel's own answer
    (:func:`browser_profiles.needs_refresh`): "it was planted, and the file has been saved since".
    The tier borrows it rather than keeping a rule of its own so that a cookie the user re-took
    reaches the test profile exactly the way the 「把 Cookie 更新进 Profile」 button makes it reach
    theirs — once, from the file that is current now. A profile that has never been used answers
    ``False``: its first crawl imports the file by itself.
    """
    import browser_profiles

    return bool(browser_profiles.needs_refresh(platform, str(COOKIE_DIR / f'{platform}_cookies.json')))


def resolve_profile_root(in_user_directory: bool) -> Path:
    """The profile root this tier crawls from, and the one rule that decides it.

    Default: :data:`LIVE_PROFILE_ROOT` — it survives the run (so the saved cookie is not replayed
    into a fresh browser every round) and it is nowhere near the user's own directories.

    With the operator's flag: ``data/chrome_profile``, the app-managed profile the user's own
    crawls run in. That is not a shortcut — it is the only honest way to test a logged-in crawl:
    measured 2026-09-26, the user's weibo crawl (a session his browser has been rotating since
    09-24) returned results at 06:14 while this tier's browser, planted minutes earlier from a
    COPY of the same cookie file, was answered a passport page at 06:13. To a site, a copied login
    is a second device. The flag is his consent, read from the one place the isolation guard reads
    it too, so the tier and the guard cannot disagree about what was allowed.

    The refusal in the default branch is the point of this function: without it, one edited
    constant would have the tests crawling inside the user's session, quietly, on every run.
    """
    root = isolation_guard.user_profile_dir() if in_user_directory else LIVE_PROFILE_ROOT
    if not in_user_directory:
        forbidden = (REPO_ROOT / 'data').resolve()
        assert not str(root.resolve()).startswith(str(forbidden)), (
            f'the live tier profile root {root} sits inside {forbidden}, which holds the user profiles'
        )
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


@pytest.fixture(scope='session', autouse=True)
def live_profile_root():
    """Give the tier a profile directory that survives the run — and name whose it is.

    Written as a *setting* rather than passed as an argument, because that is how the product
    chooses its profile root (:func:`browser_profiles.root_dir`): the tier then goes through the
    same resolution a user's crawl does, including "an absolute path wins, empty means the
    app-managed one". A refusal there is the one way this fixture could quietly end back at the
    user's directory, so the warnings come back as a failure rather than as a log line.
    """
    root = resolve_profile_root(isolation_guard.uses_user_profile())
    _saved, warnings = settings_store.save_settings({'browser_profile_dir': str(root), 'use_browser_profile': True})
    assert not warnings, f'the tier profile root was refused, so crawls would use the user directory: {warnings}'
    return str(root)


@pytest.fixture(scope='session')
def cookie_dir_str() -> str:
    return str(COOKIE_DIR)


@pytest.fixture
def live_crawler(cookie_dir_str):
    """``live_crawler('zhihu', headless=False)`` → crawler or skip.

    Construction failure (Chrome/driver missing) skips too: on machines with
    no browser this tier is not applicable, not broken.

    **Every crawler here is built inside the product's own same-platform gate.** The tier
    used to drive browsers directly, so it ran a second policy beside the one that decides
    when a platform may be crawled: ``app.py`` holds :func:`crawl_gate.hold` for a crawl's
    whole life, and now so does every case in here. That is fidelity, not protection — the
    2026-09-24 weibo refusals that first looked like "crawled too soon after its sibling"
    turned out to be intermittent risk control (see ``docs/crawler_notes.md``), and the gate
    deliberately adds no cooldown of its own.
    """
    import crawl_gate

    from crawlers import get_crawler
    from crawlers.base import ProfileUnavailableError

    made = []

    def _make(platform, headless=True, use_profile=None):
        # WeChat is the one platform crawled without a session: its article bodies
        # are public, and it has no cookie row in the panel at all. Requiring one
        # here would skip the only tier that proves that crawl still works.
        if platform != 'wechat' and not has_cookie(platform):
            pytest.skip(f'no saved cookies for {platform}')
        # A test that asks for a second browser of a platform it is still holding would
        # otherwise sit in the gate until PLATFORM_GATE_TIMEOUT — 900 seconds, with no
        # browser on screen and nothing in the report to explain it, because the wait is
        # indistinguishable from a slow crawl. Three cases do ask (the two-board
        # comparison, the cookie-death resume, the author-discovery walk), and by the
        # product's own rule the earlier crawl of that platform is over by then, so
        # handing the turn back here keeps the promise instead of bypassing the lock.
        for entry in [e for e in made if e[2] == platform]:
            release(entry[0])
        stack = contextlib.ExitStack()
        # Taken before the browser exists: the turn has to cover the *whole* crawl, or
        # two tests would each cool down for a crawl that had not started yet.
        stack.enter_context(crawl_gate.hold(platform))
        try:
            crawler = get_crawler(
                platform,
                headless=headless,
                cookie_dir=cookie_dir_str,
                use_profile=use_profile,
                refresh_cookies=refresh_for_planting(platform),
            )
        except ProfileUnavailableError:
            # Not "no browser on this machine" — the profile is held by something that
            # has not finished. Skipping here would hide a serialization bug in this
            # very tier behind a grey line, so it stays red.
            stack.close()
            raise
        except Exception as e:
            stack.close()
            pytest.skip(f'Chrome/driver unavailable: {e}')
        made.append([crawler, stack, platform])
        return crawler

    def release(crawler) -> None:
        """Close *crawler* and hand its platform's turn back."""
        for entry in made:
            if entry[0] is crawler:
                with contextlib.suppress(Exception):
                    crawler.close()
                entry[1].close()
                made.remove(entry)
                return
        with contextlib.suppress(Exception):
            crawler.close()

    _make.release = release
    yield _make
    for crawler, stack, _platform in reversed(made):
        with contextlib.suppress(Exception):
            crawler.close()
        stack.close()


class _Rows(list):
    """The rows of one live search, carrying the crawler's final answer with them.

    An empty from a real site is three different facts wearing one face: the crawler
    was bounced to a login page (``login_wall`` — the session is dead), risk control
    answered (``risk_blocked`` — the session may be perfect, the fix is to back off;
    measured 2026-09-25 as this account's SECOND search burst of a session), or it
    found nothing and says so silently — the shape a user would trust as "no
    results", and the one thing this tier may never pass. A plain list threw the
    first two answers away, so every caller asserting ``rows`` conflated them.
    """

    login_wall = False
    risk_blocked = False


@pytest.fixture
def live_search(live_crawler):
    """``live_search('zhihu', headless=False, keyword='三亚', count=3)`` → rows.

    A live platform can answer a *valid* session with a login redirect once and
    then serve the next request normally — measured, not assumed: an observed
    xiaohongshu run returned nothing with the 登录墙 message logged, and the same
    search passed seconds later with nothing changed. That is risk control, not a
    dead cookie and not a removed capability, and the tier's job is to tell those
    three apart rather than to fail on the first one.

    So the attempt is repeated, through a fresh crawler, and only when the crawl itself
    reported the wall (`crawler.login_wall`). An empty result with no wall is a genuine
    "this keyword found nothing" and is passed straight back for the caller to assert on —
    the assertions in the tests stay exactly as strict as they were, because a retry that
    ends in the same assertion cannot weaken one. The list comes back as :class:`_Rows`,
    so a caller that still gets nothing can tell the site's honest refusal from the
    silent empty and assert on the difference.

    Two attempts, not more: measured 2026-09-24, weibo's refusals were intermittent risk
    control on one account (the same 7-day windowed search returned 8 rows alone and was
    answered a passport page minutes later), and **every retry asks the site again** — a
    third and fourth attempt spent the account's budget to prove nothing new. Between them
    the tier waits :data:`Config.WALL_RETRY_BACKOFF`, the back-off a user's run gets, where
    it used to sleep 5 s — a patience no product path has ever offered.

    **Weibo gets one attempt** (measured 2026-09-26, the same night the retries were found to
    have cost the user their own session): a retry there is the same refused endpoint asked
    again by the same saved credential, and the account is what carries the flag — so the
    second request buys a red that names nothing new and spends budget that is not the test's
    to spend. A refusal is asserted as a refusal instead (see
    ``test_live_weibo.py::test_visible_window_search_works_too``).

    Each crawl is created inside :func:`crawl_gate.hold`, the same turn the app takes for a
    crawl's whole life, so the tier orders one platform's crawls the way the program does
    rather than running its own policy beside it.
    """
    from config import Config

    def _search(platform, *, headless, keyword=None, count=3, urls=None, attempts=None, **kwargs):
        if attempts is None:
            attempts = live_attempts(platform)
        rows = _Rows()
        for attempt in range(attempts):
            crawler = live_crawler(platform, headless=headless)
            try:
                if urls is not None:
                    rows = _Rows(crawler.search(urls=urls, **kwargs) or [])
                else:
                    rows = _Rows(crawler.search(keyword, target_count=count, **kwargs) or [])
            finally:
                # Released through the fixture so the platform's turn ends with the crawl:
                # a bare ``close()`` would hold it until the test finished, and the retry
                # below would then queue behind a browser that no longer exists.
                live_crawler.release(crawler)
            rows.login_wall = bool(getattr(crawler, 'login_wall', False))
            rows.risk_blocked = bool(getattr(crawler, 'risk_blocked', False))
            if rows or not rows.login_wall or attempt == attempts - 1:
                return rows
            time.sleep(Config.WALL_RETRY_BACKOFF)
        return rows

    return _search


@pytest.fixture(scope='session')
def weibo_windowed(cookie_dir_str):
    """One real 7-day windowed keyword search per session, shared by the cases that need it.

    Two live cases want the same crawl: the row test wants posts to check their shape and
    the target cutoff, and the comment crawl wants a post that reports ``评论数 > 0`` so the
    comment fetch is honest rather than pointed at a fixture URL that quietly dies. Asked
    separately they cost s.weibo.com **two** search bursts minutes apart, and that is the
    shape this account was refused in on 2026-09-24: the first burst answered, the second
    came back a passport page, and every retry asked the site again, which is how one
    refusal grew into six. Same query either way, so it is crawled once and read twice.

    Returns ``{'rows', 'target', 'login_wall'}``. A refusal is handed to the callers
    rather than hidden: a test that cannot see rows has nothing to assert, and saying so
    with the flag is the honest red.
    """
    from datetime import date, timedelta

    import crawl_gate

    from crawlers import get_crawler

    target = 8
    end = date.today()
    start = end - timedelta(days=7)
    rows: list = []
    refused = False
    # ONE round, one browser: a second ask is the same refused endpoint seen again with the same
    # credential, and the ACCOUNT carries the flag — which is why ``live_search`` ends a weibo
    # attempt instead of repeating it. Refusing to retry is what keeps this tier from spending an
    # allowance that belongs to the user.
    with crawl_gate.hold('weibo'):
        crawler = get_crawler(
            'weibo',
            headless=True,
            cookie_dir=cookie_dir_str,
            refresh_cookies=refresh_for_planting('weibo'),
        )
        try:
            rows = (
                crawler.search(
                    '三亚',
                    start_time=start.strftime('%Y-%m-%d'),
                    end_time=end.strftime('%Y-%m-%d'),
                    target_count=target,
                )
                or []
            )
            refused = bool(crawler.login_wall)
        finally:
            crawler.close()
    return {'rows': rows, 'target': target, 'login_wall': refused}
