"""CNKI's export walk: 全选 every page, one Refworks export at the end.

No browser and no network. The page seams are scripted, so the walk's own rules
are what runs: 全选 applies to the current page while the site accumulates the
selection across pages; the export happens once per accumulated batch; the user's
target decides where emitting stops; and a refused record never licenses a short
table as "the site ran out".
"""

import pytest

from crawlers.core.crawler import UNDER_TARGET
from crawlers.platforms.cnki.crawler import CnkiCrawler

pytestmark = pytest.mark.unit

REFWORKS = """RT Journal Article
A1 常世亮;常世恺
AD 林州建筑职业技术学院;
T1 大学生恋爱观的影响因素及特点研究
JF 才智
YR 2026
IS 26
OP 64-67
K1 大学生;恋爱观;影响因素
AB 为探究当代大学生恋爱观现状及影响因素。
DO 10.0000/example

"""


def _refworks(title: str) -> str:
    return REFWORKS.replace('T1 大学生恋爱观的影响因素及特点研究', f'T1 {title}')


def _bare(monkeypatch):
    crawler = CnkiCrawler.__new__(CnkiCrawler)
    crawler.driver = None
    crawler.headless = True
    crawler.login_wall = False
    crawler.risk_blocked = False
    crawler.unreachable = False
    crawler.end_reason = None
    crawler.walk_counts = {}
    crawler._collected = []
    crawler._cursor = {}
    crawler._sink = None
    crawler._cursor_sink = None
    crawler._abort = None
    monkeypatch.setattr(crawler, '_polite_pause', lambda *a, **k: None)
    monkeypatch.setattr(crawler, '_clear_selection', lambda: None)
    monkeypatch.setattr(crawler, '_is_logged_in', lambda: True)
    return crawler


def _row(export_id: str) -> dict:
    return {'id': export_id, 'title': f'题名-{export_id}'}


def _harness(crawler, monkeypatch, pages: dict, export=None):
    """Script paging, 全选 accumulation and the one export per batch.

    ``state['selected']`` is the site's cumulative count; guessing it wrongly is
    the bug this file exists to catch. ``export`` may return fewer texts or raise.
    """
    state = {'page': 1, 'selected': 0, 'batches': []}
    monkeypatch.setattr(crawler, '_page_rows', lambda: list(pages.get(state['page'], [])))

    def next_page():
        state['page'] += 1
        return 'ok' if state['page'] in pages else 'end'

    def select_page(ids):
        state['selected'] += len(ids)
        return state['selected']

    def export_batch():
        count = state['selected']
        state['batches'].append(count)
        state['selected'] = 0
        if export is not None:
            return export(count)
        return [_refworks(f'题名-{i}') for i in range(count)]

    monkeypatch.setattr(crawler, '_next_page', next_page)
    monkeypatch.setattr(crawler, '_select_page', select_page)
    monkeypatch.setattr(crawler, '_export_page_records', export_batch)
    return state


class TestTheRecordShape:
    def test_the_refworks_text_goes_through_the_upload_importer(self):
        rows = CnkiCrawler._rows_from_refworks(CnkiCrawler.__new__(CnkiCrawler), REFWORKS)
        assert len(rows) == 1
        row = rows[0]
        assert row['题名'] == '大学生恋爱观的影响因素及特点研究'
        assert row['作者'] == '常世亮;常世恺'
        assert row['年份'] == 2026
        assert row['关键词'] == '大学生;恋爱观;影响因素'
        assert row['记录ID'] and row['格式'] == 'CNKI'

    def test_the_downloads_blank_lines_between_fields_are_removed(self):
        """The real CNKI-…txt writes a blank line after every field (measured)."""
        text = (
            'RT Journal Article\n\nA1 作者\n\nT1 题名一\n\nYR 2026\n\n'
            'RT Journal Article\n\nA1 作者\n\nT1 题名二\n\nYR 2025\n\n'
        )
        parts = CnkiCrawler._split_refworks(text)
        assert len(parts) == 2, parts
        rows = [CnkiCrawler._rows_from_refworks(CnkiCrawler.__new__(CnkiCrawler), part)[0] for part in parts]
        assert [row['题名'] for row in rows] == ['题名一', '题名二']
        assert [row['年份'] for row in rows] == [2026, 2025]


class TestTheWalk:
    def test_every_page_is_selected_and_exported_once(self, monkeypatch):
        crawler = _bare(monkeypatch)
        _harness(crawler, monkeypatch, {1: [_row('a'), _row('b')], 2: [_row('c')]})
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 3)

        crawler.search('大学生恋爱观', target_count=5)

        assert crawler.collected() == 3
        assert crawler.end_reason == 'site_end', 'the pager offered no next page'
        assert crawler.position.get('page') == 2, 'the cursor covers the batch pages'

    def test_the_selection_accumulates_across_pages(self, monkeypatch):
        crawler = _bare(monkeypatch)
        state = _harness(crawler, monkeypatch, {1: [_row('a'), _row('b')], 2: [_row('c')]})
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 3)

        crawler.search('k', target_count=5)

        assert state['batches'] == [3], 'one export for the accumulated selection, not one per page'

    def test_the_target_stops_selection_after_enough_pages(self, monkeypatch):
        crawler = _bare(monkeypatch)
        state = _harness(crawler, monkeypatch, {1: [_row('a'), _row('b'), _row('c')], 2: [_row('d')]})
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 4)

        crawler.search('k', target_count=2)

        assert state['batches'] == [3], 'page 1 alone already covers the target'
        assert crawler.collected() == 2
        assert crawler.end_reason is None
        assert crawler.position.get('page') == 1

    def test_a_resumed_run_restarts_at_the_stored_page(self, monkeypatch):
        crawler = _bare(monkeypatch)
        pages = {2: [_row('a'), _row('b'), _row('c')]}
        state = _harness(crawler, monkeypatch, pages)
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 30)

        def advance(page):
            state['page'] = page
            return True

        monkeypatch.setattr(crawler, '_advance_to', advance)

        crawler.search('k', target_count=10, resume={'page': 2})

        assert state['batches'] == [3], 'the resumed page is re-selected as one batch'
        assert crawler.position.get('page') == 2

    def test_the_selection_cap_splits_a_large_search(self, monkeypatch):
        crawler = _bare(monkeypatch)
        page_a = [_row(f'a{i}') for i in range(300)]
        page_b = [_row(f'b{i}') for i in range(300)]
        state = _harness(crawler, monkeypatch, {1: page_a, 2: page_b})
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 600)

        crawler.search('k', target_count=600)

        assert state['batches'] == [300, 300], 'the site refuses a 501st selection, so batches are capped'
        assert crawler.collected() == 600

    def test_a_short_export_is_refused_and_keeps_the_cursor(self, monkeypatch):
        crawler = _bare(monkeypatch)
        _harness(
            crawler,
            monkeypatch,
            {1: [_row('a'), _row('b')]},
            export=lambda _count: [_refworks('题名-a')],
        )
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 2)

        crawler.search('k', target_count=5)

        assert crawler.collected() == 1
        assert crawler.end_reason == UNDER_TARGET, 'a missing record is not the site running out'
        assert crawler.walk_counts.get('refused') == 1
        assert crawler.position == {}, 'a hole keeps 继续 on this page'

    def test_a_failed_export_batch_is_counted_and_not_licensed(self, monkeypatch):
        crawler = _bare(monkeypatch)

        def fail(_count):
            raise CnkiCrawler.ExportError('no window')

        _harness(crawler, monkeypatch, {1: [_row('a'), _row('b')]}, export=fail)
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 2)

        crawler.search('k', target_count=5)

        assert crawler.collected() == 0
        assert crawler.end_reason == UNDER_TARGET
        assert crawler.walk_counts.get('refused') == 2
        assert crawler.position == {}

    def test_rows_without_export_keys_are_a_named_refusal(self, monkeypatch):
        crawler = _bare(monkeypatch)
        _harness(crawler, monkeypatch, {1: [{'id': '', 'title': '题名'}]})
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 1)

        with pytest.raises(ValueError) as caught:
            crawler.search('k', target_count=5)
        assert '导出键' in str(caught.value)

    def test_one_unexportable_row_convicts_the_page(self, monkeypatch):
        crawler = _bare(monkeypatch)
        state = _harness(crawler, monkeypatch, {1: [_row('a'), {'id': '', 'title': '无键的一行'}]})
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 2)

        crawler.search('k', target_count=5)

        assert state['batches'] == [1], 'only rows with an export key can be selected'
        assert crawler.collected() == 1
        assert crawler.walk_counts.get('refused') == 1
        assert crawler.end_reason == UNDER_TARGET
        assert crawler.position == {}

    def test_a_stuck_next_page_does_not_license_the_short_table(self, monkeypatch):
        crawler = _bare(monkeypatch)
        _harness(crawler, monkeypatch, {1: [_row('a')], 2: [_row('b')]})
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 2)
        monkeypatch.setattr(crawler, '_next_page', lambda: 'failed')

        crawler.search('k', target_count=5)

        assert crawler.collected() == 1
        assert crawler.end_reason == UNDER_TARGET, 'a clicked-but-stuck pager is not a site end'

    def test_zero_results_is_the_sites_own_empty(self, monkeypatch):
        crawler = _bare(monkeypatch)
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: True)
        monkeypatch.setattr(crawler, '_total_results', lambda: 0)
        monkeypatch.setattr(crawler, '_page_rows', lambda: [])

        crawler.search('k', target_count=5)

        assert crawler.collected() == 0
        assert crawler.end_reason == 'empty'

    def test_a_slider_of_the_first_page_is_named(self, monkeypatch):
        crawler = _bare(monkeypatch)
        monkeypatch.setattr(crawler, '_open_search', lambda _kw: False)
        crawler.risk_blocked = True

        with pytest.raises(ValueError) as caught:
            crawler.search('k', target_count=5)
        assert '安全验证' in str(caught.value)


class TestTheExportGate:
    def test_an_anonymous_session_refuses_before_selecting(self, monkeypatch):
        crawler = _bare(monkeypatch)
        monkeypatch.setattr(crawler, '_is_logged_in', lambda: False)
        crawler._select_page = lambda _ids: pytest.fail('selection must not run when the site says logged out')

        with pytest.raises(CnkiCrawler.ExportError) as caught:
            crawler._export_page_records()
        assert crawler.login_wall is True, 'a login refusal must reach the executor cookie path'
        assert '登录' in str(caught.value)
