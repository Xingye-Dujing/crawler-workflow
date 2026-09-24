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

import pytest

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

    made = []

    def _make(platform, headless=True):
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
            crawler = get_crawler(platform, headless=headless, cookie_dir=cookie_dir_str)
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

    Each crawl is created inside :func:`crawl_gate.hold`, the same turn the app takes for a
    crawl's whole life, so the tier orders one platform's crawls the way the program does
    rather than running its own policy beside it.
    """
    from config import Config

    def _search(platform, *, headless, keyword=None, count=3, urls=None, attempts=2, **kwargs):
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

    from config import Config
    from crawlers import get_crawler

    target = 8
    end = date.today()
    start = end - timedelta(days=7)
    rows: list = []
    refused = False
    for _round in range(2):
        with crawl_gate.hold('weibo'):
            crawler = get_crawler('weibo', headless=True, cookie_dir=cookie_dir_str)
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
        if rows or not refused:
            break
        time.sleep(Config.WALL_RETRY_BACKOFF)
    return {'rows': rows, 'target': target, 'login_wall': refused}
