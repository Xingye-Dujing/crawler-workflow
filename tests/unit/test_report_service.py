"""Tests for services/report_service.py — the one-click HTML report.

A report is a document someone else reads, and its content is text crawled off
the internet, so the properties that matter are not layout details:

* nothing crawled is ever markup — every value is escaped, and a test that puts
  ``<script>`` in a cell proves the rule rather than trusting it;
* nothing is invented and nothing disappears quietly — an empty node says it is
  empty, a truncated table says how many rows are missing;
* one bad chart must not cost the whole report;
* the file is self-contained (no external request when it is opened), because
  it is meant to be emailed and printed.
"""

import re

import pytest

from services.export_browser import REPORT_PREFIX, resolve_report_path
from services.report_service import (
    MAX_CHARTS,
    MAX_TABLE_ROWS,
    ReportService,
    build_conclusion_prompt,
    safe_stem,
    summarize,
)

pytestmark = pytest.mark.unit


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as handle:
        return handle.read()


NODES = [
    {
        'id': 'node-1',
        'title': '数据源',
        'rows': [
            {'标题': '三亚', '正文': '张先生在深圳', 'emotion': 'Joy', 'score': 5},
            {'标题': '海口', '正文': '李女士在北京', 'emotion': 'Anger', 'score': 2},
        ],
    },
    {'id': 'node-2', 'title': '输出', 'rows': []},
]


@pytest.fixture
def service(tmp_path):
    return ReportService(str(tmp_path / 'exports'))


class TestSafeStem:
    @pytest.mark.parametrize(
        'name, expected',
        [
            ('季度报告', '季度报告'),
            ('a b', 'a_b'),
            ('../../etc/passwd', 'etc_passwd'),
            ('...', 'run'),
            ('', 'run'),
            (None, 'run'),
            ('正常-名字.xlsx', '正常-名字.xlsx'),
        ],
    )
    def test_a_title_becomes_one_safe_stem(self, name, expected):
        assert safe_stem(name, fallback='run') == expected

    def test_a_long_title_is_capped(self):
        assert len(safe_stem('x' * 300)) == 60


class TestDocument:
    def test_crawled_text_is_never_markup(self, service):
        poisoned = [
            {
                'id': 'n',
                'title': '<img src=x onerror=alert(1)>',
                'rows': [{'正文': '<script>alert("crawled")</script>', '标题': 'a\'b"c'}],
            }
        ]
        markup = service.build('报告', poisoned, {})
        assert '<script>alert' not in markup
        assert '&lt;script&gt;' in markup
        assert '<img src=x' not in markup
        # The escaped forms are present, so nothing was dropped on the way.
        assert 'alert(&quot;crawled&quot;)' in markup
        assert 'a&#x27;b&quot;c' in markup

    def test_an_empty_node_says_so_instead_of_disappearing(self, service):
        markup = service.build('报告', NODES, {})
        assert 'node-2' in markup or '输出' in markup
        assert '没有产出任何行' in markup

    def test_a_truncated_table_says_how_many_rows_are_missing(self, service):
        rows = [{'正文': f'row {i}'} for i in range(MAX_TABLE_ROWS + 7)]
        markup = service.build('报告', [{'id': 'n', 'title': 'T', 'rows': rows}], {})
        assert f'共 {len(rows)} 行' in markup
        assert 'row 19' in markup
        assert 'row 20' not in markup

    def test_the_run_facts_only_list_what_is_known(self, service):
        markup = service.build('报告', NODES, {'workflow_name': 'wf-a', 'run_id': 'abc123'})
        assert 'wf-a' in markup and 'abc123' in markup
        # No start time was supplied, so no row claims one — and no blank label
        # is printed for it either.
        assert '开始' not in markup

    def test_the_conclusion_travels_as_paragraphs(self, service):
        markup = service.build('报告', NODES, {}, conclusion='第一段。\n\n第二段 <b>粗</b>。')
        assert '第一段。' in markup
        assert '&lt;b&gt;' in markup

    def test_the_document_is_self_contained(self, service):
        markup = service.build('报告', NODES, {})
        assert markup.startswith('<!DOCTYPE html>')
        assert '<link' not in markup
        assert 'src="http' not in markup and "src='http" not in markup
        assert 'javascript:' not in markup

    def test_the_page_does_not_change_colour_underneath_its_charts(self, service):
        """The pictures are rendered for light paper.

        Following the OS dark-mode setting flipped the page to black while the
        charts kept their black axis text, which made every figure unreadable on
        a dark-theme machine — the one environment the author happened to use.
        """
        markup = service.build('报告', NODES, {})
        assert 'prefers-color-scheme' not in markup
        # A grid, so the last chart of an unfinished row cannot stretch to the
        # whole width and dwarf its siblings.
        assert 'display: grid' in markup

    def test_a_chart_is_inlined_as_a_picture(self, service):
        markup = service.build('报告', NODES, {})
        assert 'data:image/png;base64,' in markup
        assert 'figcaption' in markup

    def test_rows_the_run_never_finished_are_not_a_category(self, service):
        """``未处理`` is a gap in the run, not a kind of answer.

        Drawing it would put a bar on the chart that reads as "some rows were
        neutral", which is a claim the data never made.
        """
        rows = [{'emotion': '未处理'} for _ in range(3)]
        markup = service.build('报告', [{'id': 'n', 'title': 'T', 'rows': rows}], {})
        assert 'data:image/png' not in markup
        assert '不足以出图' in markup

    def test_a_column_of_only_integers_is_still_chartable(self, service):
        # value_counts() hands back integer counts; the filter that removes the
        # unfinished marker works on the category names and must not touch them.
        rows = [{'label': 1}, {'label': 2}, {'label': 3}]
        markup = service.build('报告', [{'id': 'n', 'title': 'T', 'rows': rows}], {})
        assert 'data:image/png;base64,' in markup

    def test_an_entity_table_charts_its_categories_and_not_its_offsets(self, service):
        """``row``/``start``/``end`` are positions in the source text.

        A histogram of them is a picture of where the crawler happened to find
        something, and it pushes the chart budget past the one figure that
        actually describes the data.
        """
        rows = [
            {'row': 0, 'text': '张先生', 'label': 'PERSON', 'start': 0, 'end': 3},
            {'row': 0, 'text': '深圳市', 'label': 'LOC', 'start': 4, 'end': 7},
            {'row': 1, 'text': '2024年5月', 'label': 'DATE', 'start': 2, 'end': 10},
        ]
        markup = service.build('报告', [{'id': 'n', 'title': '实体', 'rows': rows}], {})
        captions = re.findall(r'<figcaption>(.*?)</figcaption>', markup)
        assert captions == ['实体 · label'], captions

    def test_the_chart_budget_stops_the_report_becoming_a_picture_book(self, service):
        # Twelve numeric columns, each with several distinct values: far more
        # than the report is willing to draw.
        rows = [{f'c{i}': (row + i) % 3 for i in range(12)} for row in range(4)]
        rows.append({'emotion': 'Joy', 'label': 'PERSON'})
        markup = service.build('报告', [{'id': 'n', 'title': 'T', 'rows': rows}], {})
        assert markup.count('<figure>') == MAX_CHARTS

    def test_a_category_nothing_else_shares_is_stated_once_not_drawn(self, service):
        # One slice of 100% is a sentence, not a chart.
        rows = [{'emotion': 'Joy'} for _ in range(5)]
        markup = service.build('报告', [{'id': 'n', 'title': 'T', 'rows': rows}], {})
        assert '<figure>' not in markup
        assert '不足以出图' in markup

    def test_a_failing_chart_costs_a_line_and_not_the_report(self, service, monkeypatch):
        from services import visualizer

        def boom(*_args, **_kwargs):
            raise RuntimeError('matplotlib said no')

        monkeypatch.setattr(visualizer.VisualizationService, 'render_image', staticmethod(boom))
        markup = service.build('报告', NODES, {})
        assert '图表生成失败' in markup
        # The tables are still there: the failure is contained in its section.
        assert '三亚' in markup

    def test_a_run_with_no_chartable_signal_says_so(self, service):
        nodes = [{'id': 'n', 'title': 'T', 'rows': [{'正文': '只有一行文字'}]}]
        markup = service.build('报告', nodes, {})
        assert '不足以出图' in markup


class TestSave:
    def test_the_file_lands_in_the_export_directory_named_as_a_report(self, service):
        saved = service.save('<html></html>', '季度 报告')
        assert saved['name'] == f'{REPORT_PREFIX}季度_报告.html'
        assert service.export_dir in saved['path']
        assert _read(saved['path']) == '<html></html>'
        assert saved['bytes'] == len(b'<html></html>')

    def test_a_second_report_with_one_name_keeps_both(self, service):
        first = service.save('a', '同名')
        second = service.save('b', '同名')
        assert first['name'] != second['name']
        assert _read(first['path']) == 'a'
        assert _read(second['path']) == 'b'

    def test_a_generated_report_is_viewable_and_nothing_else_is(self, service, tmp_path):
        saved = service.save('x', '报告')
        assert resolve_report_path(service.export_dir, saved['name']) == saved['path']
        # A stray page in the same folder is not a report, whatever it is called.
        exports = tmp_path / 'exports'
        (exports / 'report-impostor').mkdir(exist_ok=True)
        (exports / 'notes.html').write_text('x', encoding='utf-8')
        assert resolve_report_path(service.export_dir, 'notes.html') == ''
        assert resolve_report_path(service.export_dir, 'report-..') == ''
        assert resolve_report_path(service.export_dir, '') == ''


class TestSummary:
    def test_the_digest_carries_counts_not_documents(self):
        text = summarize(NODES)
        assert '数据源: 2 rows' in text
        assert 'Anger' in text and 'Joy' in text
        # The bodies are not dumped at the model: a report summary is about the
        # shape of the data, and thousands of crawled sentences would say less.
        assert '张先生在深圳' not in text

    def test_an_empty_node_is_still_counted(self):
        assert '输出: 0 rows' in summarize(NODES)

    def test_a_numeric_column_reports_its_range(self):
        text = summarize(NODES)
        assert 'score:' in text and 'mean' in text

    def test_the_prompt_names_the_language_it_wants_and_the_numbers_it_has(self):
        zh = build_conclusion_prompt('rows: 3', 'zh')
        en = build_conclusion_prompt('rows: 3', 'en')
        assert '中文' in zh and 'rows: 3' in zh
        assert 'English' in en
        assert 'Do not explain why' in en
