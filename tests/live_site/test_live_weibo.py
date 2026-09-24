"""Live Weibo keyword crawl — real Chrome with the user's saved cookies.

Two things are pinned here, and they are pinned apart on purpose:

* the **windowed** crawl (``timescope``, one hourly URL per window over a week) is read from
  the session's single shared crawl in :func:`weibo_windowed`, because that endpoint is what
  this account gets refused by: ``target_count`` must actually stop the walk (weibo used to
  walk hour-windows unbounded), rows must be well-formed, and the passport *facade* on entry
  must not be mistaken for a login wall;
* a **visible window** crawls too, which needs its own browser and so its own request.

A genuine wall is *reported*, never answered with an empty success — that part is asserted by
the crawler's own flag on the shared crawl rather than by a second request.
"""

from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]


@pytest.mark.live_quick
def test_time_window_search_returns_capped_rows(weibo_windowed):
    rows = weibo_windowed['rows']
    assert rows, (
        f'weibo returned nothing WITH saved cookies (login_wall={weibo_windowed["login_wall"]}) — '
        'the redirect facade was likely mis-read as a login wall, or the cookie is stale (Cookie→generate)'
    )
    assert len(rows) <= weibo_windowed['target'], (
        f'target_count={weibo_windowed["target"]} must not wildly overshoot (got {len(rows)})'
    )
    for row in rows:
        assert (row.get('正文') or '').strip(), f'post with empty body: {row}'
    assert all(isinstance(r.get('转发数', 0), int) and isinstance(r.get('评论数', 0), int) for r in rows)


def test_visible_window_search_works_too(live_search):
    """headless=False — the mode the user's own 窗口 runs use: the same crawl must deliver."""
    end = date.today()
    start = end - timedelta(days=7)
    rows = live_search(
        'weibo',
        headless=False,
        keyword='海口',
        count=3,
        start_time=start.strftime('%Y-%m-%d'),
        end_time=end.strftime('%Y-%m-%d'),
    )
    assert rows, 'a visible-window crawl returned nothing where the headless one produced rows'
    assert len(rows) <= 5, f'target_count=3 must not wildly overshoot (got {len(rows)})'
    for row in rows:
        assert (row.get('正文') or '').strip(), f'post with empty body: {row}'
