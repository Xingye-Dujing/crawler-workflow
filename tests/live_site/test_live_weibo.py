"""Live Weibo keyword crawl — real Chrome with the user's saved cookies.

Covers the two bugs this tier exists to keep dead: target_count must actually
cap the crawl (weibo used to walk hour-windows unbounded), and a login-wall
redirect must be *reported*, never silently answered with an empty success.
"""

from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]


def test_time_window_search_returns_capped_rows(live_crawler):
    crawler = live_crawler('weibo')
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
        'weibo returned nothing WITH saved cookies — either the cookie is stale '
        '(re-run Cookie→generate) or the login-wall detection is not firing'
    )
    assert len(rows) <= 5, f'target_count=3 must not wildly overshoot (got {len(rows)})'
    for row in rows:
        assert (row.get('正文') or '').strip(), f'post with empty body: {row}'
    assert all(isinstance(r.get('转发数', 0), int) and isinstance(r.get('评论数', 0), int) for r in rows)
