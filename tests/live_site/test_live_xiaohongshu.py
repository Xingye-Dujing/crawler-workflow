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
