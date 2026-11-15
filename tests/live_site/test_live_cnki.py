"""Live CNKI crawl — real Chrome, a saved CNKI session, two pages, one export.

The export endpoint answers a session, and a fresh device is sent to the slider
(`/verify/home`), so this case skips without a saved CNKI cookie exactly as the
other session platforms do. It pins what a unit test cannot: 全选 selects only the
current page, the site accumulates the selection across pages, and the final
“导出题录文件” download parses into the importer's normalized table.

Target 25 is deliberately just past one page (20 rows): it forces a second page
and therefore proves the accumulation and the single export.
"""

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

KEYWORD = '大学生恋爱观'


@pytest.mark.live_quick
def test_two_pages_are_selected_and_exported_once(live_crawler):
    # HEADED on purpose. kns.cnki.net refuses the export window from a headless session
    # ("您的请求被拒绝 / 您无权查看该页面 / HTTP ERROR 403：无头模式被拒绝"), and the export page then
    # has no 下载题录文件 link — the same measurement as docs/crawler_notes.md → 中国知网. A
    # headless run is therefore not a statement about this crawler, and asking for one turned a
    # documented site rule into a red live case.
    crawler = live_crawler('cnki', headless=False)
    rows = crawler.search(KEYWORD, target_count=25)

    assert len(rows) == 25, f'expected the target, got {len(rows)}'
    assert crawler.position.get('page') == 2, f'the batch should cover two pages: {crawler.position}'
    for row in rows:
        assert str(row.get('题名') or '').strip(), f'a record without a title cannot be a graph node: {row}'
        assert str(row.get('记录ID') or '').strip(), f'no identity for the ledger: {row}'
        assert row.get('格式') == 'CNKI', row
    assert len({row['记录ID'] for row in rows}) == len(rows), 'two live records collapsed onto one identity'
