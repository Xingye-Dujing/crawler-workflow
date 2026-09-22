"""Shared plumbing for the live-site tier.

Everything here really drives real Chrome against the real platforms with the
user's saved cookies — the tier is excluded by default (``live_site`` marker)
and selected explicitly:

    .venv/Scripts/python.exe -m pytest -q -m live_site

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
    """
    from crawlers import get_crawler

    made = []

    def _make(platform, headless=True):
        # WeChat is the one platform crawled without a session: its article bodies
        # are public, and it has no cookie row in the panel at all. Requiring one
        # here would skip the only tier that proves that crawl still works.
        if platform != 'wechat' and not has_cookie(platform):
            pytest.skip(f'no saved cookies for {platform}')
        try:
            crawler = get_crawler(platform, headless=headless, cookie_dir=cookie_dir_str)
        except Exception as e:
            pytest.skip(f'Chrome/driver unavailable: {e}')
        made.append(crawler)
        return crawler

    yield _make
    for crawler in made:
        with contextlib.suppress(Exception):
            crawler.close()


@pytest.fixture
def live_search(live_crawler):
    """``live_search('zhihu', headless=False, keyword='三亚', count=3)`` → rows.

    A live platform can answer a *valid* session with a login redirect once and
    then serve the next request normally — measured, not assumed: an observed
    xiaohongshu run returned nothing with the 登录墙 message logged, and the same
    search passed seconds later with nothing changed. That is risk control, not a
    dead cookie and not a removed capability, and the tier's job is to tell those
    three apart rather than to fail on the first one.

    So the attempt is repeated once, through a fresh crawler, and only when the
    crawl itself reported the wall (`crawler.login_wall`). An empty result with no
    wall is a genuine "this keyword found nothing" and is passed straight back for
    the caller to assert on — the assertions in the tests stay exactly as strict as
    they were, because a retry that ends in the same assertion cannot weaken one.
    """

    def _search(platform, *, headless, keyword=None, count=3, urls=None, attempts=2, **kwargs):
        rows = []
        for attempt in range(attempts):
            crawler = live_crawler(platform, headless=headless)
            try:
                if urls is not None:
                    rows = crawler.search(urls=urls, **kwargs)
                else:
                    rows = crawler.search(keyword, target_count=count, **kwargs)
            finally:
                crawler.close()
            if rows or not getattr(crawler, 'login_wall', False) or attempt == attempts - 1:
                return rows
            # Let the platform's throttle window move before paying for a browser.
            time.sleep(5)
        return rows

    return _search
