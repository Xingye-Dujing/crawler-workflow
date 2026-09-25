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

**Run this file with ``CIXI_LIVE_USE_USER_PROFILE=1`` when the question is "does the logged-in
crawl work".** Weibo will not be crawled in parallel, and it will not be crawled from a *copy* of
a login either: the site keeps one rolling session per browser directory and answers a second one
with a passport page, so a red here without the flag is usually an answer about the session shape
(``docs/crawler_notes.md`` measured it both ways at 06:13 and 06:14 of 2026-09-26) rather than
about the code. The flag is the user's consent to let the tier use his own profile.
"""

from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]


@pytest.mark.live_quick
def test_time_window_search_returns_capped_rows(weibo_windowed):
    rows = weibo_windowed['rows']
    assert rows, (
        f'weibo returned nothing WITH saved cookies (login_wall={weibo_windowed["login_wall"]}) — '
        'the redirect facade was likely mis-read as a login wall, the cookie is stale (Cookie→生成), '
        'or this ACCOUNT is flagged by recent volume: measured 2026-09-26, a cookie re-saved 30 minutes '
        'earlier was still answered a passport page, and a retry changes neither'
    )
    assert len(rows) <= weibo_windowed['target'], (
        f'target_count={weibo_windowed["target"]} must not wildly overshoot (got {len(rows)})'
    )
    for row in rows:
        assert (row.get('正文') or '').strip(), f'post with empty body: {row}'
    assert all(isinstance(r.get('转发数', 0), int) and isinstance(r.get('评论数', 0), int) for r in rows)


def test_visible_window_search_works_too(live_search, weibo_windowed):
    """headless=False — the mode the user's own 窗口 runs use: the same crawl must deliver.

    Delivered rows are asserted in full. An empty that the crawler itself reported as a
    wall is the site refusing this account's next burst (measured 2026-09-25: the same
    day's SECOND s.weibo.com search is answered a passport page, and ``live_search`` has
    already asked again after the run's own back-off before handing back) — and it is
    accepted only while the shared headless crawl proves the session itself is alive.
    An empty with no wall stays red: that is the silent "found nothing" a user would
    trust, and a visible browser that always lands on the login page is exactly the
    regression it names.
    """
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
    if not rows:
        assert rows.login_wall or rows.risk_blocked, (
            'a visible-window crawl returned nothing WITHOUT naming a refusal: that reads '
            'as "this keyword has no posts", which is the false answer this tier exists to catch'
        )
        assert weibo_windowed['rows'], (
            'the visible crawl was walled and the headless one found nothing either: either the session is '
            'dead (re-save it, Cookie→生成) or the account is flagged by recent volume — measured '
            '2026-09-26, where a session re-saved 30 minutes earlier was still answered a passport page'
        )
        return
    assert len(rows) <= 5, f'target_count=3 must not wildly overshoot (got {len(rows)})'
    for row in rows:
        assert (row.get('正文') or '').strip(), f'post with empty body: {row}'
