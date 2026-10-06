"""The MiKTeX compile node + PDF output, driven offline with a FAKE xelatex.

The compiler is the user's own MiKTeX, so nothing here shells out: ``_find_xelatex`` and
``subprocess.run`` are stood in for exactly the way ``test_report_api`` does for Chrome, which lets the
node's real branches be checked without a TeX install — a chart that emits LaTeX, one that emits neither
box (rejected before a run), and a missing ``xelatex`` (the node FAILS with a named reason, the run does
not crash and no half-written PDF is left).
"""

import os

import pytest
from run_wait import run_finished

import services.latex_compile as latex_compile

pytestmark = [pytest.mark.api, pytest.mark.serial]

RECORDS = [
    {'城市': 'Sanya', '分数': 3},
    {'城市': 'Haikou', '分数': 5},
]


def _node(nid, ntype, params=None, operation=''):
    node = {'id': nid, 'type': ntype, 'title': ntype, 'params': params or {}}
    if operation:
        node['operation'] = operation
    return node


def _wf(nodes, conns):
    return {'nodes': nodes, 'connections': conns, 'settings': {'mode': 'serial'}}


def _fake_xelatex_run(writes=True, returncode=0, stderr=b''):
    """Honour ``-output-directory <dir> main.tex`` by creating (or refusing) ``<dir>/main.pdf``."""
    from types import SimpleNamespace

    def run(command, *args, **kwargs):
        outdir = None
        for i, arg in enumerate(command):
            if arg == '-output-directory':
                outdir = command[i + 1]
        if writes and outdir:
            with open(os.path.join(outdir, 'main.pdf'), 'wb') as handle:
                handle.write(b'%PDF-1.4 fake')
        return SimpleNamespace(returncode=returncode, stderr=stderr)

    return run


def _upload(client, paste):
    return paste(RECORDS, name='compile.csv')


class TestCompileService:
    def test_compose_merges_figure_and_table_into_one_document(self):
        df = __import__('pandas').DataFrame(RECORDS)
        fig = latex_compile.LatexChartService.to_latex_document(df, 'bar', x='城市', y='分数', title='柱')
        tab = latex_compile.LatexChartService.to_latex_table(df, 'bar', x='城市', y='分数', title='柱')
        merged = latex_compile.compose_tex([fig, tab])
        # ONE document: a single preamble, a single body, both contents carried through.
        assert merged.count(r'\documentclass') == 1, 'merging two standalones must not double the preamble'
        assert merged.count(r'\begin{document}') == 1 and merged.count(r'\end{document}') == 1
        assert r'\begin{axis}' in merged, 'the figure body survived the merge'
        assert r'\toprule' in merged, 'the three-line table body survived the merge'
        assert 'Sanya' in merged, 'the data labels ride into the composed document'

    def test_no_xelatex_is_a_named_refusal_not_a_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(latex_compile, '_find_xelatex', lambda: '')
        out, name = latex_compile.compile_pdf(
            r'\documentclass{standalone}\begin{document}x\end{document}', 'x.pdf', str(tmp_path)
        )
        assert 'error' in out and name == ''
        assert not (tmp_path / 'x.pdf').exists()

    def test_a_failed_xelatex_leaves_no_half_written_pdf(self, tmp_path, monkeypatch):
        monkeypatch.setattr(latex_compile, '_find_xelatex', lambda: 'xelatex')
        monkeypatch.setattr(latex_compile.subprocess, 'run', _fake_xelatex_run(False, returncode=1, stderr=b'boom'))
        out, name = latex_compile.compile_pdf('x', 'x.pdf', str(tmp_path))
        assert 'error' in out and not (tmp_path / 'x.pdf').exists()


class TestCompileNodeAndPdf:
    def test_compile_node_stages_a_pdf(self, client, app_module, paste, data_root, monkeypatch):
        monkeypatch.setattr(latex_compile, '_find_xelatex', lambda: 'xelatex')
        monkeypatch.setattr(latex_compile.subprocess, 'run', _fake_xelatex_run(True))
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 2}),
                _node(
                    'node-2',
                    'visualize',
                    {'chart_type': 'bar', 'x_field': '城市', 'y_field': '分数', 'engine': 'echarts'},
                ),
                _node('cmpA', 'compile'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'cmpA'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'cmp'})
        assert started.get_json()['ok'] is True
        assert run_finished(app_module)
        assert (data_root / 'data' / 'exports' / 'compile-cmpA.pdf').exists(), 'the compile node must stage a PDF'

    def test_visualize_to_output_writes_a_pdf(self, client, app_module, paste, data_root, monkeypatch):
        monkeypatch.setattr(latex_compile, '_find_xelatex', lambda: 'xelatex')
        monkeypatch.setattr(latex_compile.subprocess, 'run', _fake_xelatex_run(True))
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 2}),
                _node(
                    'node-2',
                    'visualize',
                    {'chart_type': 'bar', 'x_field': '城市', 'y_field': '分数', 'engine': 'echarts'},
                ),
                _node('node-3', 'output', {'operation': 'save', 'format': 'pdf', 'filename': 'myfig.pdf'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'vizpdf'})
        assert run_finished(app_module)
        assert (data_root / 'data' / 'exports' / 'myfig.pdf').exists(), 'a chart wired to a save must export a PDF'

    def test_compile_to_output_renames_the_staged_pdf(self, client, app_module, paste, data_root, monkeypatch):
        monkeypatch.setattr(latex_compile, '_find_xelatex', lambda: 'xelatex')
        monkeypatch.setattr(latex_compile.subprocess, 'run', _fake_xelatex_run(True))
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 2}),
                _node(
                    'node-2',
                    'visualize',
                    {'chart_type': 'bar', 'x_field': '城市', 'y_field': '分数', 'engine': 'echarts'},
                ),
                _node('cmpB', 'compile'),
                _node('node-4', 'output', {'operation': 'save', 'format': 'pdf', 'filename': 'final.pdf'}, 'save'),
            ],
            [
                {'from': 'node-1', 'to': 'node-2'},
                {'from': 'node-2', 'to': 'cmpB'},
                {'from': 'cmpB', 'to': 'node-4'},
            ],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'cmppdf'})
        assert run_finished(app_module)
        exports = data_root / 'data' / 'exports'
        assert (exports / 'final.pdf').exists(), 'the output finalises the compile node’s PDF under the user name'
        assert not (exports / 'compile-cmpB.pdf').exists(), (
            'the staged file was renamed away, not copied and left behind'
        )

    def test_both_boxes_off_is_rejected_before_the_run(self, client, app_module, paste, data_root, monkeypatch):
        monkeypatch.setattr(latex_compile, '_find_xelatex', lambda: 'xelatex')
        monkeypatch.setattr(latex_compile.subprocess, 'run', _fake_xelatex_run(True))
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 2}),
                _node(
                    'node-2',
                    'visualize',
                    {
                        'chart_type': 'bar',
                        'x_field': '城市',
                        'y_field': '分数',
                        'engine': 'echarts',
                        'emit_latex': False,
                        'emit_latex_table': False,
                    },
                ),
                _node('cmpC', 'compile'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'cmpC'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'bothoff'})
        assert run_finished(app_module)
        assert app_module.execution_state['outcome'] == 'rejected', 'a compile with no LaTeX is refused up front'
        assert not (data_root / 'data' / 'exports' / 'compile-cmpC.pdf').exists()

    def test_missing_xelatex_fails_the_node_not_the_run(self, client, app_module, paste, data_root, monkeypatch):
        monkeypatch.setattr(latex_compile, '_find_xelatex', lambda: '')
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 2}),
                _node(
                    'node-2',
                    'visualize',
                    {'chart_type': 'bar', 'x_field': '城市', 'y_field': '分数', 'engine': 'echarts'},
                ),
                _node('node-3', 'output', {'operation': 'save', 'format': 'pdf', 'filename': 'no.pdf'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'noxel'})
        assert started.get_json()['ok'] is True, 'a missing compiler is a per-node failure, not a rejected canvas'
        assert run_finished(app_module)
        assert not (data_root / 'data' / 'exports' / 'no.pdf').exists(), 'no binary must mean no file, and no traceback'
