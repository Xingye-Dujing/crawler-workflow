"""``/api/report/latex`` — one compilable paper document from a run's OWN filed sources.

The route is given a run id and a title, nothing else. That is the whole design: the figures are
read out of the run's file ledger, so the paper's figure and the preview's figure cannot disagree,
and a browser cannot post a LaTeX source for xelatex to read (which would turn the compiler into a
reader of files it was never asked to open).
"""

import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.api


def _fake_xelatex(writes=True):
    def run(command, *args, **kwargs):
        outdir = None
        for index, arg in enumerate(command):
            if arg == '-output-directory':
                outdir = command[index + 1]
        if writes and outdir:
            with open(os.path.join(outdir, 'main.pdf'), 'wb') as handle:
                handle.write(b'%PDF-1.4 fake')
        return SimpleNamespace(returncode=0, stderr=b'')

    return run


def _rows() -> list:
    """Two linked rows wide enough for every view the tests ask for: a node, its coordinates, its
    adjacency and the centrality columns the knowledge-graph table reads. Two, because a graph with
    one endpoint has no link, and the views under test refuse an empty network."""
    import json

    links = {'甲': '乙', '乙': '甲'}
    return [
        {
            '节点': name,
            '连接': json.dumps([{'target': links[name], 'value': 0.5, 'count': 1}], ensure_ascii=False),
            '频次': 3 if name == '甲' else 2,
            '度': 1,
            '中介中心性': 0.2,
            '特征向量中心性': 0.5,
            'PageRank': 0.3,
            'Sigma': 1.4,
            '聚类': 0,
            '聚类标签': '甲组',
            '突现强度': 2.0 if name == '甲' else 0.0,
            '突现起始': 2020,
            '突现结束': 2021,
            '首年': 2020,
            '末年': 2021,
            'x': 0.0 if name == '甲' else 10.0,
            'y': 0.0 if name == '甲' else 10.0,
            '年份序列': json.dumps({'2020': 1, '2021': 2}),
        }
        for name in ('甲', '乙')
    ]


def _figure(chart_type: str, title: str) -> str:
    import pandas as pd

    from services.charts.tikz import LatexChartService as L

    return L.to_latex_document(pd.DataFrame(_rows()), chart_type, title=title)


def _table(chart_type: str, title: str) -> str:
    import pandas as pd

    from services.charts.tikz import LatexChartService as L

    return L.to_latex_table(pd.DataFrame(_rows()), chart_type, title=title)


def _run_with_charts(app_module, data_root, monkeypatch, *, workflow_name='成稿演示'):
    """A finished run that filed a figure and a table for each of two chart nodes, and nothing for
    a third."""
    from services.runs.store import NODE_DONE, RUN_COMPLETED
    from services.workflows.manager import WorkflowManager

    store = app_module.get_run_store()
    export = data_root / 'data' / 'exports'
    export.mkdir(parents=True, exist_ok=True)
    store.start_run('run-tex-1', workflow_name, 'fp-tex', node_total=3)
    for node_id, title, chart_type in (
        ('node-1', '关键词知识图谱', 'knowledge_graph'),
        ('node-2', '突现词图', 'burst'),
    ):
        store.begin_node('run-tex-1', node_id, 'visualize', title=title)
        for kind, text in (
            ('latex', _figure(chart_type, title)),
            ('latex_table', _table(chart_type, title)),
        ):
            name = f'{title}-{node_id}-{kind}.txt'
            (export / name).write_text(text, encoding='utf-8')
            store.record_file('run-tex-1', node_id, str(export / name), kind)
        store.finish_node('run-tex-1', node_id, NODE_DONE)
    store.begin_node('run-tex-1', 'node-3', 'visualize', title='没出 LaTeX 的图')
    store.finish_node('run-tex-1', 'node-3', NODE_DONE)
    store.finish_run('run-tex-1', RUN_COMPLETED)
    WorkflowManager().save(
        workflow_name,
        {
            'nodes': [
                {'id': 'node-1', 'type': 'visualize', 'title': '关键词知识图谱', 'params': {'chart_type': 'bar'}},
            ],
            'connections': [],
        },
    )
    monkeypatch.setattr('services.charts.pdf.find_xelatex', lambda: 'xelatex')
    monkeypatch.setattr('services.charts.pdf.subprocess.run', _fake_xelatex())
    return store, export


class TestThePaperDocument:
    def test_a_run_that_filed_latex_composes_one_numbered_document(self, client, app_module, data_root, monkeypatch):
        from i18n import t

        store, export = _run_with_charts(app_module, data_root, monkeypatch)
        body = client.post('/api/report/latex', json={'run_id': 'run-tex-1', 'title': '数字治理知识图谱'}).get_json()
        assert body['ok'] is True, body
        assert body['figures'] == 2 and body['tables'] == 2
        pdf = export / body['name']
        document = (export / body['tex']).read_text(encoding='utf-8')
        assert pdf.exists() and pdf.read_bytes().startswith(b'%PDF'), 'the compiled PDF is the deliverable'
        assert '\\documentclass[12pt]{article}' in document and '\\usepackage{ctex}' in document
        # Every item is an ``[H]`` float: a plain figure/table lets TeX move the item past the section
        # the reader is in, and that is how the first compile produced a page of nothing but the heading.
        assert '\\usepackage{float}' in document
        assert document.count('\\begin{figure}[H]') == 2 and document.count('\\begin{table}[H]') == 2
        assert '\\begin{center}' not in document, 'an in-flow center cannot break the page, it overflows it'
        assert document.count('\\cixifit{') == 4, 'every pasted body is shrunk to the text block'
        # Every word compared here is resolved through i18n: the test client's language is not this
        # machine's, and a pasted Chinese string would pass here and fail on CI.
        assert f'\\caption{{突现词图{t("report.table_suffix")}}}' in document, 'a table caption carries the title'
        assert t('report.method_section') in document
        kinds = {entry['kind'] for entry in store.files_for_run('run-tex-1')}
        assert {'latex_doc', 'report_pdf'} <= kinds, f'the export browser and 智能清除 must find both: {kinds}'

    def test_a_chart_that_filed_no_latex_is_not_invented_but_is_named(self, client, app_module, data_root, monkeypatch):
        """node-3 has no registered source: the document carries two figures, not three with a
        blank box where the third should be — and the document says out loud which chart is missing.
        A paper that quietly holds two figures where the run drew five reads as if the third never
        existed."""
        from i18n import t

        _store, export = _run_with_charts(app_module, data_root, monkeypatch)
        body = client.post('/api/report/latex', json={'run_id': 'run-tex-1'}).get_json()
        document = (export / body['tex']).read_text(encoding='utf-8')
        assert body['figures'] == 2
        assert document.count('\\begin{figure}[H]') == 2, 'no blank float stands in for the missing one'
        assert '没出 LaTeX 的图' in document, 'named, not silently dropped'
        assert t('report.missing_charts', count=1, names='x').split('x')[0] in document

    def test_parameters_that_cannot_be_checked_are_said_out_loud(self, client, app_module, data_root, monkeypatch):
        """The canvas above holds only node-1, so node-2's parameters cannot be verified against
        the fingerprints its run recorded. A method paragraph describing settings nobody ran is the
        most expensive thing this document can contain."""
        from i18n import t

        _store, export = _run_with_charts(app_module, data_root, monkeypatch)
        body = client.post('/api/report/latex', json={'run_id': 'run-tex-1'}).get_json()
        document = (export / body['tex']).read_text(encoding='utf-8')
        assert t('report.method_unverified', names='x').split('x')[0] in document, document[-900:]

    def test_a_run_with_no_filed_latex_refuses_rather_than_emitting_an_empty_paper(self, client, app_module, data_root):
        from services.runs.store import NODE_DONE, RUN_COMPLETED

        store = app_module.get_run_store()
        store.start_run('run-tex-2', '无 LaTeX', 'fp-tex-2', node_total=1)
        store.begin_node('run-tex-2', 'node-1', 'visualize', title='只出了图')
        store.finish_node('run-tex-2', 'node-1', NODE_DONE)
        store.finish_run('run-tex-2', RUN_COMPLETED)
        response = client.post('/api/report/latex', json={'run_id': 'run-tex-2'})
        assert response.status_code == 400
        error = response.get_json()['error']
        assert 'LaTeX' in error, error

    def test_an_unknown_run_is_refused_by_its_id(self, client):
        response = client.post('/api/report/latex', json={'run_id': 'nope'})
        assert response.status_code == 400
        assert 'nope' in response.get_json()['error']

    def test_a_missing_compiler_is_an_error_not_a_broken_file(self, client, app_module, data_root, monkeypatch):
        _store, export = _run_with_charts(app_module, data_root, monkeypatch)
        monkeypatch.setattr('services.charts.pdf.find_xelatex', lambda: '')
        response = client.post('/api/report/latex', json={'run_id': 'run-tex-1'})
        assert response.status_code == 400
        assert not list(export.glob('report-run-tex-1.pdf')), 'nothing half-written survives a refusal'


class TestTheDocumentItself:
    """The .tex is the deliverable a reader keeps, so its shape is under test too."""

    def test_the_method_lines_come_from_the_biblio_node_that_ran(self, monkeypatch, tmp_path):
        from runtime.stores import get_run_store

        from services.reports import paper
        from services.runs.store import NODE_DONE, RUN_COMPLETED
        from services.workflows.manager import WorkflowManager

        store = get_run_store()
        store.start_run('run-meth-1', '方法核对', 'fp-m', node_total=1)
        store.begin_node('run-meth-1', 'node-1', 'biblio', title='关键词图谱')
        store.finish_node('run-meth-1', 'node-1', NODE_DONE)
        store.finish_run('run-meth-1', RUN_COMPLETED)
        WorkflowManager().save(
            '方法核对',
            {
                'nodes': [
                    {
                        'id': 'node-1',
                        'type': 'biblio',
                        'title': '关键词图谱',
                        'params': {'entity_type': 'keyword', 'slice_years': 2, 'link_measure': 'cosine'},
                    },
                ],
                'connections': [],
            },
        )
        monkeypatch.setattr(
            paper.WorkflowManager,
            'captured_params',
            lambda self, n, i, f: ({'entity_type': 'keyword', 'slice_years': 2, 'link_measure': 'cosine'}, True),
        )
        run = store.get_run('run-meth-1')
        lines = paper._method_lines(run, list(run['nodes']))
        assert len(lines) == 1
        assert '关键词' in lines[0], lines
        assert 'slice_years=2' in lines[0] and 'link_measure=cosine' in lines[0]

    def test_a_run_with_no_method_lines_still_ships_a_document_with_its_provenance(self):
        from services.reports import paper

        document = paper.build_document(
            # A real source from this project's own LaTeX writer: a body that is not one of its
            # standalone documents is refused rather than pasted in raw (a stray
            # \begin{document} mid-paper would break the compile).
            [{'figure': _figure('knowledge_graph', '图一'), 'table': '', 'caption': '图一'}],
            title='标题',
            meta={'workflow': 'wf', 'run_id': 'r-1', 'started': '今天', 'finished': '现在', 'figures': 1, 'tables': 0},
            methods=[],
        )
        assert '\\begin{document}' in document and document.rstrip().endswith('\\end{document}')
        assert 'r-1' in document and '今天' in document

    def test_nothing_filed_produces_no_document(self):
        from services.reports import paper

        assert paper.build_document([], title='t', meta={}, methods=[]) == ''

    def test_the_page_holds_the_widest_body_this_project_writes(self):
        """A figure arrives as a 17.5 cm minipage and a network picture sizes itself to
        ``GRAPH_BOX_CM``. Tighten the margins and every figure silently shrinks its fonts instead of
        its page — so what is under test is the relationship between these numbers, not their values.
        """
        import services.charts.tikz as lc
        from services.reports import paper

        assert paper.TEXTWIDTH_CM >= paper.WIDEST_BODY_CM
        assert lc.GRAPH_BOX_CM[0] <= paper.TEXTWIDTH_CM, 'a figure sized to its box must not need shrinking'
        assert lc.GRAPH_BOX_CM[1] <= paper.TEXTWIDTH_CM, 'the box is stated in both directions'
        document = paper.build_document(
            [{'figure': _figure('knowledge_graph', '图一'), 'table': '', 'caption': '图一'}],
            title='标题',
            meta={'workflow': 'wf', 'run_id': 'r-4', 'started': 'a', 'finished': 'b', 'figures': 1, 'tables': 0},
            methods=[],
        )
        assert f'\\usepackage[a4paper,margin={paper.PAGE_MARGIN_CM}cm]{{geometry}}' in document
        assert '\\usepackage{float}' in document, '[H] comes from float'

    def test_a_table_longer_than_a_page_is_blocked_and_continued_not_cut(self):
        """A `tabular` cannot break, so a 50-row three-line table ran 2.6 cm past the bottom of the
        sheet. It is now cut into page-sized blocks that repeat their header — and every row survives."""

        from i18n import t
        from services.charts.tikz import LatexChartService as L
        from services.reports import paper

        rows = [[f'关键词{i}', i, 1] for i in range(1, 61)]
        table = L._document(L._tabular(['节点', '频次', '度'], rows), 'knowledge_graph', '长表', table=True)
        document = paper.build_document(
            [{'figure': '', 'table': table, 'caption': '长表'}],
            title='标题',
            meta={'workflow': 'wf', 'run_id': 'r-2', 'started': 'a', 'finished': 'b', 'figures': 0, 'tables': 1},
            methods=[],
        )
        blocks = document.count('\\begin{table}[H]')
        assert blocks == 3, f'60 rows at {paper.TABLE_ROWS_PER_BLOCK} a block is three pages, not one'
        assert f'\\caption*{{长表{t("report.table_suffix")}{t("report.table_continued")}}}' in document
        # One number for one table: the continuation is captioned but never re-numbered.
        assert document.count('\\caption{长表') == 1 and document.count('\\label{tab:cixi-1}') == 1
        assert document.count('关键词60') == 1 and document.count('关键词1 &') == 1, 'no row was dropped or doubled'
        assert document.count('\\textbf{节点}') == blocks, 'each block repeats the header'

    def test_a_table_this_service_did_not_write_is_pasted_unchanged(self):
        """The block cutter reads this project's own shape — one row per line, a bold header between
        ``\\toprule`` and ``\\midrule``. A hand-edited .txt in the export folder is not cut up into
        something that no longer compiles."""
        from services.charts.tikz import LatexChartService as L
        from services.reports import paper

        odd = (
            '{\\footnotesize\n\\begin{tabular}{*{3}{l}}\n\\toprule\n甲 & 乙 & 丙 \\\\\n'
            '\\midrule\n1 & 2 & 3 \\\\ 4 & 5 & 6 \\bottomrule\n\\end{tabular}\n}'
        )
        assert paper._split_table(odd) is None, 'its rows are not one-per-line, so it is not ours'
        document = paper.build_document(
            # A real standalone around it: a body this service did not write at all is refused, and
            # that refusal must not be confused with "unparsable table shape".
            [{'figure': '', 'table': L._document(odd, 'knowledge_graph', '手改表', table=True), 'caption': '手改表'}],
            title='标题',
            meta={'workflow': 'wf', 'run_id': 'r-3', 'started': 'a', 'finished': 'b', 'figures': 0, 'tables': 1},
            methods=[],
        )
        assert odd in document, 'an unparsable body is pasted as it arrived'
        assert document.count('\\begin{table}[H]') == 1
