"""Live Xiaohongshu search crawl — real Chrome with the user's saved cookies."""

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]


def test_search_returns_note_cards(live_crawler):
    crawler = live_crawler('xiaohongshu')
    try:
        rows = crawler.search('三亚', target_count=3)
    finally:
        crawler.close()
    assert rows, (
        'xiaohongshu returned nothing with saved cookies — likely a risk-control '
        'page or expired login: check the crawl log for the login-wall message'
    )
    assert len(rows) <= 6, f'target_count=3 must cap the crawl (got {len(rows)})'
    titled = [r for r in rows if (r.get('标题') or '').strip()]
    assert titled, 'at least some cards must carry a title'
