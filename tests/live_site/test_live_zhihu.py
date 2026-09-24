"""Live Zhihu search crawl — real Chrome, real cookies, real zhihu.com.

Small volume on purpose (target 3): this pins that the 2026-layout parser
still extracts full rows against the live DOM, that 链接 identity feeds the
dedupe ledger, and — in the non-headless variant — that a *visible* browser
window (the Cookie-login mode) crawls just as correctly, background occlusion
flags included.
"""

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]


def _assert_rows(rows, minimum=2):
    assert len(rows) >= minimum, f'expected at least {minimum} rows, got {len(rows)}'
    links = [r.get('链接') or '' for r in rows]
    unique = {link for link in links if link}
    for row in rows:
        assert (row.get('正文') or '').strip() or (row.get('标题') or '').strip(), f'empty row: {row}'
    assert len(unique) >= minimum - 1, 'rows should carry distinct article links (dedupe identity)'


@pytest.mark.live_quick
def test_headless_search_returns_full_rows(live_search):
    try:
        rows = live_search('zhihu', headless=True, keyword='三亚', count=3)
    except RuntimeError as e:
        # Zhihu's day-by-day headless risk control is a DESIGNED refusal: the
        # crawler raises the catalog's actionable message instead of pretending
        # success. That is an environment state (retry later, or run the
        # visible-window variant), not a code failure.
        pytest.skip(f'zhihu refused the headless session this run: {e}')
    _assert_rows(rows)
    # Time column regression: the 2026 layout moved it to .SearchItem-time.
    assert any((r.get('发布时间') or '').strip() for r in rows), 'publish time should parse on live DOM'


def test_visible_window_search_works_too(live_search):
    """headless=False — the login-browser mode: occluded/background protection
    flags are on, and the same parser must still deliver."""
    rows = live_search('zhihu', headless=False, keyword='海口', count=2)
    _assert_rows(rows, minimum=1)
    assert rows, 'visible-window crawl must yield at least one row'
