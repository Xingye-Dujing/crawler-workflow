"""weibo ``search`` — its loop-fallback end stays UN-ARMED, and its cursor stores no list.

docs/crawler_rules.md §6 keeps weibo search fully un-armed (`end_reason=None`) because its
``'end'`` is "every hourly URL was iterated", a LOOP FALLBACK, not a fact the SITE attested.
The walk was stamping it ``site_end``, which licensed a thin table (a window that never
rendered is skipped and still lands on ``'end'``) and silenced the U1 under-target gate. The
same walk also cached its whole URL list in the cursor, and because ``mark_position`` fires
once per harvested card, every stored row re-serialised ~1 MB of JSON into ``runs.db``.
"""

from crawlers.base import UNDER_TARGET
from crawlers.weibo import WeiboCrawler


def _bare(monkeypatch):
    """A WeiboCrawler with no browser: only the plumbing ``search`` touches."""
    crawler = WeiboCrawler.__new__(WeiboCrawler)
    crawler.driver = None
    crawler.headless = True
    crawler.login_wall = False
    crawler.risk_blocked = False
    crawler.unreachable = False
    crawler.pending_waits = 0
    crawler._abort = None
    crawler._collected = []
    crawler._cursor = {}
    crawler._sink = None
    crawler._cursor_sink = None
    crawler.requests = []
    crawler.end_reason = None
    crawler.walk_counts = {}
    monkeypatch.setattr(crawler, '_polite_pause', lambda *a, **k: None)
    return crawler


class TestTheLoopFallbackIsNotALicense:
    def test_a_short_walk_leaves_end_reason_unset(self, monkeypatch):
        """Windows walked, target never crossed, no refusal said why: ``'end'``, and the gate
        must still be able to convict it — so weibo hands back NO license, not ``site_end``."""
        crawler = _bare(monkeypatch)
        monkeypatch.setattr(crawler, '_scrape_single_search', lambda url, target: [])
        # One day of range (day-granular dates) → hourly windows; target 10 with 0 collected
        # means the walk simply runs out of windows, which is the loop fallback.
        crawler.search('三亚', start_time='2026-01-01', end_time='2026-01-02', target_count=10)
        assert crawler.end_reason is None, f'a loop fallback must not license the short, got {crawler.end_reason!r}'

    def test_an_under_target_license_is_never_handed_to_a_search(self, monkeypatch):
        """Positive control: the ONLY end the search walk may leave is None — it is neither the
        convicting UNDER_TARGET nor a LICENSED_ENDS word, because it reports no site fact at all."""
        crawler = _bare(monkeypatch)
        monkeypatch.setattr(crawler, '_scrape_single_search', lambda url, target: [])
        crawler.search('三亚', start_time='2026-01-01', end_time='2026-01-02', target_count=10)
        assert crawler.end_reason != UNDER_TARGET
        assert crawler.end_reason not in ('site_end', 'capped', 'empty')


class TestTheCursorRecordsPositionNotContent:
    def test_the_url_list_is_rebuilt_and_never_stored(self, monkeypatch):
        """The resume re-derives the same URLs from (keyword, start, end), so the list is
        content, not position — and storing it rewrote ~1 MB per harvested row."""
        crawler = _bare(monkeypatch)

        def _harvest_two(url, target):
            crawler._collected.extend([{'微博ID': f'{len(crawler._collected)}'} for _ in range(2)])
            return ['a', 'b']

        monkeypatch.setattr(crawler, '_scrape_single_search', _harvest_two)
        # A target above what the day's windows can hold, so every window is walked.
        crawler.search('三亚', start_time='2026-01-01', end_time='2026-01-02', target_count=10_000)
        position = crawler.position
        assert 'urls' not in position, position
        total = position.get('url_total')
        assert total and total > 1, f'the walk records how many windows there are, got {total}'
        assert position.get('url_index') == total, 'and that it walked them all'


class TestARefusedWindowIsNotProof:
    """M1: the cursor must rest BEHIND a window the session refused, not cross it.

    The loop used to write ``url_index=idx`` and THEN check ``_refused()``, so the refused
    window was already marked done — 继续 started after it and SKIPPED the exact link the user
    is told refreshing the cookie will retry. A refusal is now checked first, so a bounced
    window leaves the cursor at the last clean one."""

    def test_the_cursor_stays_behind_a_window_the_session_refused(self, monkeypatch):
        crawler = _bare(monkeypatch)
        calls = {'n': 0}

        def scrape(url, target):
            calls['n'] += 1
            if calls['n'] == 1:
                crawler._collected.append({'微博ID': 'x1'})
                return ['x1']  # first window proves
            crawler.login_wall = True  # the second window bounces the session
            return []

        monkeypatch.setattr(crawler, '_scrape_single_search', scrape)
        crawler.search('三亚', start_time='2026-01-01', end_time='2026-01-02', target_count=10_000)
        position = crawler.position
        assert position.get('url_index') == 1, f'the refused window was marked done → 继续 skips it: {position}'
        assert calls['n'] == 2, 'the walk stopped AT the refusal, not walked every window'
