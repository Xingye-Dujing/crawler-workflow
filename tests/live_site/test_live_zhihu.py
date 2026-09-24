"""Live Zhihu search crawl — real Chrome, real cookies, real zhihu.com.

Small volume on purpose (target 3): this pins that the 2026-layout parser
still extracts full rows against the live DOM, that 链接 identity feeds the
dedupe ledger, that a row's 正文 reaches the length its own answer page holds
(the list is an excerpt list, so only the page can say what "full" is), and —
in the non-headless variant — that a *visible* browser
window (the Cookie-login mode) crawls just as correctly, background occlusion
flags included.
"""

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]


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


def test_an_expanded_row_carries_its_own_pages_text(live_crawler):
    """The length floor is the answer page's own figure, not a guessed constant.

    The search list is an excerpt list (measured 2026-09-24: 35–109 characters per card,
    with no CSS clamp involved), so a row can only be judged against the text the answer
    itself carries. Re-read in the same browser session, because the pair is the point:
    a crawl that stopped clicking 阅读全文 stores ~70 characters where this page holds
    hundreds, and nothing else in the suite would notice.
    """
    crawler = live_crawler('zhihu', headless=False)
    rows = crawler.search('海口', target_count=2)
    answer = next((r for r in rows if '/answer/' in str(r.get('链接') or '')), None)
    assert answer, f'no answer-type row to compare against a page: {[r.get("链接") for r in rows]}'
    stored = len(str(answer.get('正文') or ''))

    crawler.open(str(answer['链接']))
    node = crawler._element_or_none('.RichContent-inner .RichText')
    assert node is not None, 'the answer page gave no body to compare with'
    page = len(crawler._node_text(node))
    assert page, 'the answer page read as empty, so this comparison measured nothing'
    # 0.7 rather than 1.0: the row was read from the list and the page is read afterwards,
    # and an author may have edited between the two. Everything under that is truncation.
    assert stored >= page * 0.7, f'the row kept {stored} of the {page} characters its own page holds'
