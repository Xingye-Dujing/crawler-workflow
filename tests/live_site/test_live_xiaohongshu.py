"""Live Xiaohongshu search crawl — real Chrome with the user's saved cookies,
in both browser modes (headless + visible window)."""

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]


@pytest.mark.parametrize('headless', [True, False], ids=['headless', 'visible'])
def test_search_returns_note_cards(live_search, headless):
    rows = live_search('xiaohongshu', headless=headless, keyword='三亚', count=3)
    assert rows, (
        'xiaohongshu returned nothing with saved cookies — likely a risk-control '
        'page or expired login: check the crawl log for the login-wall message'
    )
    assert len(rows) <= 6, f'target_count=3 must cap the crawl (got {len(rows)})'
    titled = [r for r in rows if (r.get('标题') or '').strip()]
    assert titled, 'at least some cards must carry a title'
