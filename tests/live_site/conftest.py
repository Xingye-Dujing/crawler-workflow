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
