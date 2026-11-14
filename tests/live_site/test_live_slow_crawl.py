"""The 慢速采集 preset against a real site: does the switch reach the crawl, and does a
real 小红书 comment walk actually open the note?

User-reported shape (2026-11-13/14): with 慢速采集 on, a comment crawl opened a browser
window that sat there — no note opened, nothing in the console. The fast tier proves the
plumbing (``pacing`` reads the right setting, the walk names a feed redirect); only a real
browser with the user's own profile can say whether the note is really reached and the
panel really read. This file is that measurement.

Why the user's profile: a copied login is a second device to the site (docs/crawler_notes.md,
2026-09-26), so the only honest logged-in crawl is from the jar the site already knows. That
needs ``CIXI_LIVE_USE_USER_PROFILE=1`` — the same flag ``tests/isolation_guard`` reads — and
it is deliberately ``live_site`` (never ``live_quick`` for the browser cases): the daily gate
has no business opening a window on the desktop.

Pacing is applied, not simulated: :func:`_slow_preset` writes the preset and every case below
runs with it, so the crawl pays the human-like intervals the user asked for (小红书 is strict
about scroll/expand frequency, and about how fast pages are opened). The sleeps are asserted
once with a stubbed clock so a regression in the knob is caught without spending a minute of
real time; the walk itself is never shortened.
"""

import re
import time

import pytest
from core.config import Config
from real_paths import COOKIE_DIR, has_cookie

from crawlers.commenting.protocol import BLOCKED, OK
from crawlers.commenting.session import CommentSession

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

PLATFORM = 'xiaohongshu'

#: The preset's own numbers, restated here so a change to the bundle is a failure in this
#: file rather than a silently different crawl. ``test_the_preset_values_are_the_measured_slow_shape``
#: in the fast tier owns the schema; this is the user-facing promise the live run depends on.
SLOW = {
    'crawl_pace_scale': 4.0,
    'crawl_scroll_scale': 3.0,
    'crawl_expand_scale': 3.0,
    'crawl_click_scale': 3.0,
    'crawl_wait_scale': 2.0,
    'crawl_arrival_scale': 1.6,
    'crawl_page_scale': 3.0,
    'crawl_jitter': 30.0,
    'crawl_patience_scale': 2.0,
}


@pytest.fixture
def real_jar(monkeypatch):
    """The user's saved session, read through the same directory the app reads.

    ``tests/conftest`` sends ``Config.COOKIE_DIR`` into a throwaway root, which keeps the
    fast tiers isolated and would mean "nobody has a login" here.
    """
    if not has_cookie(PLATFORM):
        pytest.skip(f'no saved cookies for {PLATFORM}')
    monkeypatch.setattr(Config, 'COOKIE_DIR', str(COOKIE_DIR))
    return str(COOKIE_DIR)


@pytest.fixture
def _slow_preset():
    """Apply 慢速采集 for one case and put the previous values back afterwards.

    Written as concrete values (the preset's own contract), so the case runs the exact
    configuration the toolbar button produces.
    """
    from runtime import settings

    before = settings.all_settings()
    _values, warnings = settings.apply_preset('slow')
    assert not warnings, f'the preset was refused: {warnings}'
    try:
        yield
    finally:
        settings.restore_preset()
        after = settings.all_settings()
        for key in SLOW:
            assert after[key] == before[key], f'{key} was not restored ({after[key]!r} != {before[key]!r})'


class TestThePresetReachesTheCrawl:
    """No browser: the switch, the numbers it writes and the sleeps each knob buys."""

    @pytest.mark.live_quick
    def test_the_preset_writes_every_dimension(self, _slow_preset):
        from runtime import settings

        values = settings.all_settings()
        actual = {key: values[key] for key in SLOW}
        assert actual == SLOW, f'the slow preset is not the shape this live run depends on: {actual}'

    @pytest.mark.live_quick
    def test_every_sleep_reads_its_own_dimension(self, _slow_preset, monkeypatch):
        """A scroll pays the scroll multiplier, an expand its own — not one shared factor.

        The slept number is captured rather than waited out; the live walk below pays the
        real interval, and doing both here would spend a minute proving arithmetic.
        """
        from crawlers.engine import pacing

        slept: list[float] = []
        monkeypatch.setattr(pacing.time, 'sleep', slept.append)
        # No jitter for the arithmetic: the preset sets 30%, and the walk below pays the real
        # (jittered) beats. Patching ``uniform`` to zero would zero the beat itself, so the
        # jitter amount is what gets pinned.
        monkeypatch.setattr(pacing, 'jitter', lambda: 0.0)
        pacing.nap(1.0)  # politeness
        pacing.scroll_nap(1.0)
        pacing.expand_nap(1.0)
        pacing.click_nap(1.0)
        pacing.arrival_nap(1.0)
        pacing.page_nap(1.0)
        assert slept == [4.0, 3.0, 3.0, 3.0, 1.6, 3.0], slept
        assert pacing.scroll_wait(1.0) == 3.0
        assert pacing.expand_wait(1.0) == 3.0
        assert pacing.wait(1.0) == 2.0
        assert pacing.rounds(2) == 4


@pytest.mark.live_site
class TestTheRealSlowCrawl:
    """Real Chrome, the user's own profile, the preset's human-like pacing."""

    def test_the_pre_run_probe_returns_and_releases_the_profile(self, real_jar, _slow_preset):
        """慢速采集 also turns on 运行前验证 Cookie — the visible window a run opens first.

        The reported “window opens and nothing happens” is exactly this browser: if the
        probe parks on the feed and keeps the profile, the crawl behind it waits out
        ``profile_lock_timeout`` with a window that never opens a note. Asserted, not
        skipped: the probe must come back with a decided verdict and close its browser.
        """
        from sessions import preflight, profiles

        preflight.reset()
        profile = profiles.profile_dir_for(PLATFORM)
        assert profiles.is_busy(profile) is False, 'a probe may not queue behind a live crawl'
        started = time.monotonic()
        try:
            verdict = preflight.probe(PLATFORM)
        finally:
            preflight.reset()
        elapsed = time.monotonic() - started
        assert verdict['state'] in {
            preflight.VALID,
            preflight.EXPIRED,
            preflight.UNKNOWN,
            preflight.NO_COOKIE,
        }, verdict
        assert verdict['probed'] is True, f'a saved session was never looked at: {verdict}'
        # The endpoint's budget is ``cookie_preflight_timeout`` (45 s default); a probe that
        # outlives it is the one that parks the run behind the profile lock.
        assert elapsed < 180, f'the pre-run probe took {elapsed:.1f}s — the run behind it waits'
        assert profiles.is_busy(profile) is False, 'the probe left its browser holding the profile'

    def test_a_slow_comment_walk_opens_the_note_and_reads_the_panel(self, live_crawler, _slow_preset):
        """The reported failure, measured: does the browser reach the note at all?

        A note is found by this case's own search immediately before the walk (no stale
        fixture URL), the walk runs with the slow preset's scroll/expand intervals, and the
        result is one of the two honest outcomes: rows read off the panel, or a refusal the
        session NAMES. A silent ``ok`` with zero rows — the “stuck on the homepage” reading —
        is the failure this cell refuses; the cursor is pinned in that case, so the test
        also proves the engine would offer 继续 instead of filing an empty table.
        """
        crawler = live_crawler(PLATFORM, headless=False)
        try:
            cards = crawler.search('三亚', target_count=3)
            note = next((c.get('笔记链接') or c.get('链接') or '') for c in cards if c.get('笔记链接') or c.get('链接'))
            assert note, 'the live search produced no clickable note to walk'
            session = CommentSession(crawler.driver, log=print, owner=crawler)
            started = time.monotonic()
            rows, status = session.walk(PLATFORM, note, limit=3)
            elapsed = time.monotonic() - started
        finally:
            crawler.close()
        # One line a person can act on when the run is red: what the site answered and how
        # long the browser spent on it (the “窗口打开没反应” report is exactly this number).
        print(
            f'[slow] note={note} status={status} rows={len(rows)} elapsed={elapsed:.1f}s '
            f'unproven={len(crawler.skipped_targets)} wall={crawler.login_wall} risk={crawler.risk_blocked}'
        )
        assert status in (OK, BLOCKED), f'unexpected adapter failure: {status}'
        if status == BLOCKED:
            # A wall the session names is the site's answer, and a skipped case would also
            # hide a blocked crawl that filed rows anyway.
            assert not rows, f'a blocked crawl still returned {len(rows)} rows as if it succeeded'
            return
        if not rows:
            # Never a silent empty: the walk must have named the link it could not prove
            # (the homepage redirect, a missing panel, a shortfall) so 继续 re-walks it.
            assert crawler.skipped_targets, (
                f'the slow walk came back ok with zero rows and named nothing after {elapsed:.1f}s — '
                'the browser was left on a page that is not the note'
            )
            return
        assert all(re.sub(r'\s', '', row['评论内容']) for row in rows), 'a row must carry its own body'
        assert all(row['平台'] == PLATFORM and row['文章URL'] == note for row in rows)
        assert len(rows) <= 3, f'limit=3 capped the walk (got {len(rows)})'
        # Human-like pacing is the point of the run: a note page under the slow preset
        # cannot be walked in a couple of seconds (scroll 3.6 s + expand 5.4 s per round).
        assert elapsed >= 3.0, f'the walk finished in {elapsed:.1f}s — the slow intervals were not paid'
