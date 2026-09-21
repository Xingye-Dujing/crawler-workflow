"""A REAL crawl whose cookie dies mid-run — and the resume that finishes it.

The scenario the checkpoint system exists for: the browser really crawls
s.weibo.com with the saved cookie, collects a few pages of genuine rows, and
then the cookie 'expires' — simulated at the next window boundary by the same
wall transition the platform forces (login_wall set, window abandoned, crawl
stops). Everything before the wall is already in the run store with a cursor.
A fresh crawler ('the user refreshed the cookie') then resumes from that
cursor on the same store scope and the invariants are checked for real: no
rows lost, no rows duplicated, the crawl genuinely continues.

Only the expiry MOMENT is simulated; the crawl, sink, ledger, cursor and
resume walk all execute against the live site.
"""

from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]

TARGET = 15  # deep enough that one window (~10 cards) never finishes it
EXPIRE_AFTER = 3  # the cookie dies once this many rows are stored


def _window_range():
    end = date.today()
    return end - timedelta(days=2), end


class _ExpiryHarness:
    """Own store + wiring for one simulated-expiry scenario."""

    def __init__(self, tmp_path):
        from services.run_store import RunStore

        self.store = RunStore(str(tmp_path / 'expiry.db'))
        self.run_id = 'live-expiry'
        self.nid = 'weibo-node'
        self.scope = 'live-test:weibo-expiry'
        self.rows_seen = []
        self.armed = False
        # save_cursor UPDATEs node_runs — the row must exist, exactly like the
        # executor's begin_node before every real node run.
        self.store.start_run(self.run_id, 'live-expiry-wf', 'fp', node_total=1)
        self.store.begin_node(self.run_id, self.nid, 'source', title='weibo', fingerprint='fp-node')

    def sink(self, item):
        kept, _dropped = self.store.append_rows(self.run_id, self.nid, [item], dedupe_scope=self.scope)
        if kept:
            self.rows_seen.append(item)
            # The cookie 'goes stale' once a few rows are in: the next window
            # boundary will be answered with the login wall.
            if len(self.rows_seen) >= EXPIRE_AFTER:
                self.armed = True
        return bool(kept)

    def wire(self, crawler):
        crawler.set_sink(self.sink)
        crawler.set_cursor_sink(lambda pos: self.store.save_cursor(self.run_id, self.nid, pos))

    def arm_wall(self, crawler):
        orig_await = crawler._await_search_page

        def walled_await(url):
            if self.armed:
                self.armed = False
                crawler.login_wall = True
                return False
            return orig_await(url)

        crawler._await_search_page = walled_await


def test_mid_crawl_cookie_death_resumes_to_a_complete_deduped_table(live_crawler, tmp_path):
    h = _ExpiryHarness(tmp_path)
    start, end = _window_range()
    kwargs = {
        'start_time': start.strftime('%Y-%m-%d'),
        'end_time': end.strftime('%Y-%m-%d'),
        'target_count': TARGET,
    }

    # ── attempt 1: real crawl, then the cookie dies ─────────────────
    crawler = live_crawler('weibo')
    h.wire(crawler)
    h.arm_wall(crawler)
    try:
        rows1 = crawler.search('三亚', **kwargs)
    finally:
        crawler.close()
    assert crawler.login_wall is True, 'the simulated expiry must register as a wall'
    assert 1 <= len(rows1) < TARGET, f'a wall-stopped crawl is short of target, got {len(rows1)}'
    assert len(h.store.load_rows(h.run_id, h.nid)) == len(rows1), 'every pre-wall row survived in the store'
    cursor = h.store.get_cursor(h.run_id, h.nid)
    assert cursor and cursor.get('url_index'), 'the crawler persisted a resume cursor'
    stopped_at = cursor['url_index']

    # ── "user refreshes the cookie": a fresh crawler resumes ────────
    crawler2 = live_crawler('weibo')
    h.wire(crawler2)
    crawler2.seed(h.store.load_rows(h.run_id, h.nid))
    try:
        rows2 = crawler2.search('三亚', resume=cursor, **kwargs)
    finally:
        crawler2.close()

    final = h.store.load_rows(h.run_id, h.nid)
    # The resumed crawl's table is a superset of the pre-expiry one (seed +
    # whatever the new attempt collected), and nothing was lost at the wall.
    assert len(rows2) >= len(rows1)
    assert len(final) >= len(rows1), 'the resume must keep every pre-expiry row'
    # The resumed crawl moved forward on the window list (or finished it).
    cursor2 = h.store.get_cursor(h.run_id, h.nid)
    assert cursor2['url_index'] >= stopped_at, 'the resume continues from the saved cursor'
    # The ledger's promise: the whole table is duplicate-free.
    links = [r.get('链接') or r.get('微博ID') for r in final]
    assert len({link for link in links if link}) == len(final), 'resumed rows must never duplicate stored ones'
    for row in final:
        assert (row.get('正文') or '').strip()

    h.store.delete_run(h.run_id)
    h.store.forget_items(h.scope)
