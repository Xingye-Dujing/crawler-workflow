"""Live Weibo keyword crawl — real Chrome with the user's saved cookies.

Runs in BOTH browser modes (headless + visible window). Covers the bugs this
tier exists to keep dead: target_count must actually cap the crawl (weibo used
to walk hour-windows unbounded); the passport-QR *facade* on entry must not be
mistaken for a login wall (the session is already logged in); and a genuine
wall must be *reported*, never silently answered with an empty success.
"""

from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]


@pytest.mark.parametrize('headless', [True, False], ids=['headless', 'visible'])
def test_time_window_search_returns_capped_rows(live_crawler, headless):
    crawler = live_crawler('weibo', headless=headless)
    end = date.today()
    start = end - timedelta(days=7)
    try:
        rows = crawler.search(
            '三亚',
            start_time=start.strftime('%Y-%m-%d'),
            end_time=end.strftime('%Y-%m-%d'),
            target_count=3,
        )
    finally:
        crawler.close()
    assert rows, (
        'weibo returned nothing WITH saved cookies — the redirect facade was '
        'likely mis-read as a login wall, or the cookie is stale (Cookie→generate)'
    )
    assert len(rows) <= 5, f'target_count=3 must not wildly overshoot (got {len(rows)})'
    for row in rows:
        assert (row.get('正文') or '').strip(), f'post with empty body: {row}'
    assert all(isinstance(r.get('转发数', 0), int) and isinstance(r.get('评论数', 0), int) for r in rows)
