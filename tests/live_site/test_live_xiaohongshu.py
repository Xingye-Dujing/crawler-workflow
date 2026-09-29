"""Live Xiaohongshu search crawl — real Chrome with the user's saved cookies,
in both browser modes (headless + visible window)."""

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]


@pytest.mark.parametrize(
    'headless',
    [pytest.param(True, marks=pytest.mark.live_quick, id='headless'), pytest.param(False, id='visible')],
)
def test_search_returns_note_cards(live_search, headless):
    """Delivered rows are asserted in full; an empty needs the crawler's own reason.

    xiaohongshu walls a replayed session within minutes (docs/crawler_notes.md), and
    measured 2026-09-25 a visible burst was refused after the headless one delivered —
    so a refusal the crawler *names* (登录墙, already retried by ``live_search``) is the
    site's honest answer and passes. What may never pass is an empty that names nothing:
    it reads to the user as "this keyword has no notes".
    """
    rows = live_search('xiaohongshu', headless=headless, keyword='三亚', count=3)
    if not rows:
        assert rows.login_wall or rows.risk_blocked, (
            'xiaohongshu returned nothing WITHOUT naming a refusal (login wall or risk '
            'control) — that is the silent empty the tier must never pass; a named wall '
            'is risk control and already retried'
        )
        return
    assert len(rows) <= 6, f'target_count=3 must cap the crawl (got {len(rows)})'
    titled = [r for r in rows if (r.get('标题') or '').strip()]
    assert titled, 'at least some cards must carry a title'


def test_collect_walks_past_one_mounted_screen(live_search):
    """A target above the first batch must be met by following 笔记ID, not the card count (U59).

    The grid is virtualised: the initial mount is large (~22 measured 2026-09-29) and scrolling
    keeps a FLAT count while swapping note identities, so the old walk — which capped at the first
    batch and then called the flat count "the bottom" — collected at most one screen. A target past
    that batch (26) is only reached if the harvest keeps pulling new 笔记ID. The assertion is
    two-sided so it cannot pass by accident and cannot weaken the empty rule: reaching the target
    proves the fix; a shortfall is accepted ONLY when the crawler names 风控/登录墙 (the account
    walls within minutes), and a silent shortfall is exactly the under-collect this cell guards.
    """
    target = 26
    rows = live_search('xiaohongshu', headless=True, keyword='三亚', count=target)
    if not rows:
        assert rows.login_wall or rows.risk_blocked, 'an empty must name its refusal, never read as a thin keyword'
        return
    assert len(rows) <= target, f'target_count={target} must cap the crawl (got {len(rows)})'
    if len(rows) < target:
        assert rows.login_wall or rows.risk_blocked, (
            f'stopped at {len(rows)} of {target} with no refusal — a broad keyword has ample supply, '
            'so this is the recycling walk under-collecting again (it must follow 笔记ID, not the flat card count)'
        )
    ids = [r.get('笔记ID') for r in rows if r.get('笔记ID')]
    assert ids, 'delivered rows must carry a session-independent 笔记ID'
    assert len(ids) == len(set(ids)), (
        'a recycling grid re-promotes notes with new tokens; each 笔记ID must be emitted once'
    )
