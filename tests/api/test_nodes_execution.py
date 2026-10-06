"""Every node type through the real executor, and the Stop/kill plumbing.

The audit asked: does each node actually do its job, and do the process-control
endpoints behave under misuse? Each test below drives one node type through
``/api/workflow/execute`` (the same code path the canvas uses), asserting on
the STORED outcome — rows in the run store, files in the export dir, log lines
in the console — not on a private helper's return value.

Everything runs offline: uploads replace crawlers, the resume node reads the
tmp-isolated store, and the slow crawler is a fake that respects the stop
flag, so /api/workflow/stop is exercised without ever touching a browser.
"""

import re
import time

import pandas as pd
import pytest
from run_wait import run_finished

pytestmark = [pytest.mark.api, pytest.mark.serial, pytest.mark.usefixtures('seeded_logins')]

RECORDS = [
    {'标题': '三亚湾日落', '城市': 'Sanya', '分数': 3, '正文': '三亚的海滩很美 三亚湾日落真棒'},
    {'标题': '海口骑楼', '城市': 'Haikou', '分数': 5, '正文': '海口的老街骑楼很有味道'},
    {'标题': '博鳌论坛', '城市': 'Boao', '分数': 2, '正文': '博鳌小镇安静整洁'},
    {'标题': '兴隆咖啡', '城市': 'Sanya', '分数': 7, '正文': '兴隆的咖啡香浓醇厚'},
]


def _node(nid, ntype, params=None, operation=''):
    node = {'id': nid, 'type': ntype, 'title': ntype, 'params': params or {}}
    if operation:
        node['operation'] = operation
    return node


def _wf(nodes, conns, settings=None):
    return {'nodes': nodes, 'connections': conns, 'settings': settings or {'mode': 'serial'}}


def _wait(app_module, timeout=30.0):
    """The run this test started has settled (see tests/run_wait.py)."""
    return run_finished(app_module, timeout)


def _upload(client, paste):
    return paste(RECORDS, name='nodes.csv')


class TestTokenizeNode:
    def test_tokenize_streams_word_frequencies_downstream(self, client, app_module, paste, data_root):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'tokenize', {'text_column': '正文', 'output_mode': 'word_freq', 'top_n': 10}),
                _node('node-3', 'output', {'operation': 'save', 'format': 'json', 'filename': 'tok'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'tok'})
        assert started.get_json()['ok'] is True
        assert _wait(app_module)
        run_id = started.get_json()['run_id']
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
        assert rows, 'jieba must emit frequency rows for Chinese text'
        assert {'word', 'frequency'} <= set(rows[0].keys())
        assert (data_root / 'data' / 'exports' / 'tok.json').exists(), 'the chain must end in a file'

    def test_a_wrong_column_name_fails_loudly_not_silently(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'tokenize', {'text_column': '根本不存在的列'}),
                _node('node-3', 'output', {'operation': 'save', 'format': 'json', 'filename': 'tok-bad'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'tok-bad'})
        assert _wait(app_module)
        run_id = started.get_json()['run_id']
        assert app_module._RUN_STORE.row_count(run_id, 'node-2') == 0
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert '根本不存在的列' in blob, 'the message must name the column that is missing'

    def test_an_unconfigured_tokenize_node_is_a_validation_error(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'tokenize', {'text_column': ''}),
                _node('node-3', 'output', {'operation': 'save', 'format': 'json', 'filename': 'tok-x'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'tok-x'})
        assert _wait(app_module)
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'text column' in blob or '未配置' in blob


class TestRefusalsFailTheNode:
    """A node that could not do its job is a failed node, never a completed one.

    Three of these used to answer ``[]`` after logging the reason. The node settled
    DONE, the run went green, the export wrote a header and nothing else, and every
    downstream node then complained 「上游没有数据」 *about itself* — while the one
    sentence that explained the situation named no node at all. The user is sent to
    diagnose the healthy boxes.
    """

    def _flow(self, ds, tail_node, tail_conn=True):
        nodes = [_node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}), tail_node]
        conns = [{'from': 'node-1', 'to': tail_node['id']}] if tail_conn else []
        return _wf(nodes, conns)

    def test_an_unknown_process_operation_fails_the_node_it_ran_on(self, client, app_module, paste):
        ds = _upload(client, paste)
        broken = _node('node-2', 'process', {'operation': 'transliterate'}, 'transliterate')
        started = client.post(
            '/api/workflow/execute', json={'workflow': self._flow(ds, broken), 'workflow_name': 'proc-x'}
        )
        assert _wait(app_module)
        nodes = app_module._RUN_STORE.node_statuses(started.get_json()['run_id'])
        assert nodes['node-2']['status'] == 'failed', nodes['node-2']
        assert 'transliterate' in (nodes['node-2']['error'] or '')
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        named = [line for line in blob.splitlines() if 'transliterate' in line]
        assert len(named) == 1, f'the refusal was printed {len(named)} times: {named}'
        assert 'node-2' in named[0], 'the reason must travel with the node it belongs to'

    def test_a_tokenize_node_on_a_missing_column_does_not_look_finished(self, client, app_module, paste):
        ds = _upload(client, paste)
        broken = _node('node-2', 'tokenize', {'text_column': '根本没这列', 'output_mode': 'words_only'})
        started = client.post(
            '/api/workflow/execute', json={'workflow': self._flow(ds, broken), 'workflow_name': 'tok-y'}
        )
        assert _wait(app_module)
        nodes = app_module._RUN_STORE.node_statuses(started.get_json()['run_id'])
        assert nodes['node-2']['status'] == 'failed', nodes['node-2']
        assert '根本没这列' in (nodes['node-2']['error'] or '')


class TestVisualizeNode:
    def test_echarts_spec_is_produced_and_exposed(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'visualize', {'chart_type': 'bar', 'x_field': '城市', 'y_field': '分数', 'agg': 'sum'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'viz'})
        assert _wait(app_module)
        status = client.get('/api/workflow/status').get_json()
        spec = status['chart_results'].get('node-2')
        assert spec and spec['engine'] == 'echarts', 'the finished chart spec must reach the browser'
        assert 'series' in spec['option'] and 'xAxis' in spec['option']

    def test_the_share_node_reads_its_stacked_columns(self, client, app_module, paste):
        """`stack_fields` is read from the node params on the EXECUTOR path too, not only on
        the live render endpoint — a plumb dropped here is a run whose stacked node fails with
        no share chart, while the preview button (which uses the endpoint) still works."""
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'visualize', {'chart_type': 'stack_pct', 'x_field': '城市', 'stack_fields': '分数'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'viz-share'})
        assert _wait(app_module)
        spec = client.get('/api/workflow/status').get_json()['chart_results'].get('node-2')
        assert spec and spec['engine'] == 'echarts', spec
        # One column listed → one full-height segment; the yAxis is the capped share scale.
        assert len(spec['option']['series']) == 1
        assert spec['option']['yAxis']['max'] == 100

    def test_a_share_node_that_lists_no_columns_refuses_by_name(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'visualize', {'chart_type': 'stack_pct', 'x_field': '城市'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'viz-nostack'})
        assert _wait(app_module)
        spec = app_module.execution_state['results'].get('node-2')
        assert isinstance(spec, dict) and 'error' in spec and 'stacked fields' in str(spec['error'])
        assert 'node-2' not in client.get('/api/workflow/status').get_json()['chart_results']

    def test_a_bad_field_is_reported_not_as_a_crash(self, client, app_module, paste):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'visualize', {'chart_type': 'bar', 'x_field': 'nope', 'y_field': 'nope2'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'viz-bad'})
        assert _wait(app_module)
        # A refused chart carries its reason (never a half spec / traceback), it
        # reaches the console, and only RENDERABLE charts surface in chart_results.
        spec = app_module.execution_state['results'].get('node-2')
        assert isinstance(spec, dict) and 'error' in spec and 'nope' in str(spec['error'])
        status = client.get('/api/workflow/status').get_json()
        assert 'node-2' not in status['chart_results']
        # One refusal, one line — and the line names the node. It used to be two:
        # an unattributed "Visualize failed: …" from inside the node, then the
        # executor's own failure line repeating the same reason.
        carried = [line for line in status['logs'] if 'nope' in line]
        assert len(carried) == 1, f'one refusal was announced {len(carried)} times: {carried}'
        assert 'node-2' in carried[0], carried[0]

    def test_a_refused_node_never_settles_as_done(self, client, app_module, paste):
        """The node's own answer is a dict with 'error' — and that must not read
        as a completed node, let alone a completed run.

        The output and visualize nodes report a refusal instead of raising so
        their downstream keeps the table; the durable runner used to settle any
        non-list result DONE, which turned "the file you asked for was never
        written" into a green run.
        """
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'visualize', {'chart_type': 'bar', 'x_field': 'nope', 'y_field': 'nope2'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'viz-failed'})
        assert _wait(app_module)
        run = app_module._RUN_STORE.get_run(started.get_json()['run_id'])
        node = next(entry for entry in run['nodes'] if entry['node_id'] == 'node-2')
        assert node['status'] == 'failed', f"a refused chart settled as '{node['status']}'"
        assert 'nope' in (node['error'] or '')
        assert run['status'] == 'failed', 'a run with a failed node is not completed'


class TestAnomalyNode:
    """An anomaly node that cannot score must fail, not publish a clean bill of
    health: 0.0 scores on every row are indistinguishable, in an export, from a
    table that was checked and found free of outliers."""

    def test_a_text_only_table_fails_the_node_with_the_reason(self, client, app_module, paste):
        ds = paste([{'标题': '甲', '正文': '乙'}] * 6, name='text-only.csv')
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 6}),
                _node('node-2', 'process', {'operation': 'anomaly'}, 'anomaly'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'anom'})
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        statuses = app_module._RUN_STORE.node_statuses(run_id)
        assert statuses['node-2']['status'] == 'failed', statuses['node-2'].get('error')
        assert '数值列' in statuses['node-2']['error'] or 'numeric' in statuses['node-2']['error'].lower()
        assert app_module._RUN_STORE.load_rows(run_id, 'node-2') == [], 'no fabricated scores may be stored'
        logs = ' '.join(app_module.execution_state['logs'])
        assert 'anomaly' in logs.lower() or '异常' in logs, 'the console must carry the refusal'

    def test_a_numeric_table_still_scores_end_to_end(self, client, app_module, paste):
        ds = paste(
            [{'点赞': v, '标题': f'文{i}'} for i, v in enumerate([10, 12, 11, 13, 12, 11, 10, 12, 13, 900])],
            name='numbers.csv',
        )
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 10}),
                _node('node-2', 'process', {'operation': 'anomaly'}, 'anomaly'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'anom-ok'})
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
        assert len(rows) == 10
        assert 'anomaly_score' in rows[0] and 'is_anomaly' in rows[0]
        assert app_module._RUN_STORE.node_statuses(run_id)['node-2']['status'] == 'done'


class TestRowCapWarning:
    def test_the_console_names_the_node_by_its_title(self, client, app_module, paste, monkeypatch, caplog):
        """The cap lives in the storage layer, which only knows ids; the label
        has to ride along or the console blames a box nobody called that."""
        from config import Config

        monkeypatch.setattr(Config, 'RUN_MAX_ROWS_PER_NODE', 2)
        ds = paste(RECORDS, name='cap.csv')
        upload = _node('node-1', 'upload', {'dataset_id': ds, 'row_count': len(RECORDS)})
        upload['title'] = '导入的样本'
        workflow = _wf(
            [upload, _node('node-2', 'tokenize', {'text_column': '正文', 'output_mode': 'word_freq'})],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'cap'})
        run_id = started.get_json()['run_id']
        with caplog.at_level('WARNING'):
            assert _wait(app_module)
        assert app_module._RUN_STORE.row_count(run_id, 'node-1') == 2, 'the cap still caps'
        warnings = [rec.getMessage() for rec in caplog.records if rec.levelname == 'WARNING']
        assert any('导入的样本' in msg for msg in warnings), f'no warning named the node: {warnings}'
        assert not any('#node-1' in msg and '导入的样本' not in msg for msg in warnings), 'never a bare id'


class TestOutputFormats:
    @pytest.mark.parametrize(
        'fmt,ext',
        [('csv', '.csv'), ('json', '.json'), ('markdown', '.md'), ('excel', '.xlsx')],
    )
    def test_every_advertised_format_lands_a_file(self, client, app_module, paste, data_root, fmt, ext):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'output', {'operation': 'save', 'format': fmt, 'filename': f'out-{fmt}'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': f'out-{fmt}'})
        assert _wait(app_module)
        path = data_root / 'data' / 'exports' / f'out-{fmt}{ext}'
        assert path.exists(), f'{fmt} export missing (and the extension must be normalised)'
        if fmt == 'json':
            import json as _json

            assert len(_json.loads(path.read_text(encoding='utf-8'))) == 4
        if fmt == 'csv':
            assert len(pd.read_csv(path, encoding='utf-8-sig')) == 4

    def test_a_filename_with_path_holes_cannot_escape_the_export_dir(self, client, app_module, paste, data_root):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'output', {'operation': 'save', 'format': 'csv', 'filename': '../../evil'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'escape'})
        assert _wait(app_module)
        exports = data_root / 'data' / 'exports'
        assert not list(exports.parent.parent.glob('evil*')), 'a traversal filename must stay inside exports/'

    def test_unnamed_output_keeps_a_default_and_still_saves(self, client, app_module, paste, data_root):
        ds = _upload(client, paste)
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'output', {'operation': 'save', 'format': 'csv'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'defname'})
        assert _wait(app_module)
        assert any(p.suffix == '.csv' for p in (data_root / 'data' / 'exports').iterdir())


def _export_names(data_root) -> set:
    """What is in the export directory right now. The directory is shared for the
    whole session, so a test may only speak about the names it added."""
    exports = data_root / 'data' / 'exports'
    return {p.name for p in exports.iterdir()} if exports.is_dir() else set()


def _is_stamped(name: str, stem: str) -> bool:
    return bool(re.fullmatch(rf'{stem}-\d{{8}}-\d{{6}}(?:-\d+)?\.csv', name))


class TestStampedOutputFilenames:
    """「文件名追加本次运行时间」 — a workflow that runs daily keeps every result.

    The value is decided where the file is written, never stored on the node, so
    these tests check the export directory and the STORED fingerprint: the two
    places a run-time value could do damage.
    """

    def _workflow(self, stem, ds, **extra):
        params = {'operation': 'save', 'format': 'csv', 'filename': f'{stem}.csv', **extra}
        return _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'output', params, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )

    def _run(self, client, app_module, workflow, name):
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name})
        assert _wait(app_module)
        return started.get_json()['run_id']

    def test_the_option_writes_a_stamped_name_and_never_the_plain_one(self, client, app_module, paste, data_root):
        ds = _upload(client, paste)
        before = _export_names(data_root)
        self._run(client, app_module, self._workflow('once', ds, filename_timestamp=True), 'stamp-once')
        fresh = _export_names(data_root) - before
        assert len(fresh) == 1 and _is_stamped(next(iter(fresh)), 'once'), fresh
        assert 'once.csv' not in _export_names(data_root), 'the option exists so the plain name is never written'

    def test_two_runs_of_the_same_workflow_keep_both_files(self, client, app_module, paste, data_root):
        ds = _upload(client, paste)
        workflow = self._workflow('keep', ds, filename_timestamp=True)
        before = _export_names(data_root)
        self._run(client, app_module, workflow, 'stamp-twice')
        first = _export_names(data_root) - before
        self._run(client, app_module, workflow, 'stamp-twice')
        second = _export_names(data_root) - before - first
        assert len(first) == len(second) == 1, f'{first} / {second}'
        assert first != second, 'the second run landed on the first run’s file'
        exports = data_root / 'data' / 'exports'
        for name in first | second:
            assert len(pd.read_csv(exports / name, encoding='utf-8-sig')) == 4

    def test_the_stamp_never_reaches_the_node_fingerprint(self, client, app_module, paste):
        """A time inside a node's parameters would change its fingerprint every run,
        and 继续 could no longer recognise the node it is resuming: every LLM cache
        key would miss and the chain above it would re-pay for its rows.
        """
        from services.run_store import fingerprints_for_workflow

        ds = _upload(client, paste)
        workflow = self._workflow('fp', ds, filename_timestamp=True)
        run_id = self._run(client, app_module, workflow, 'stamp-fp')
        nodes = {n['node_id']: n for n in client.get(f'/api/runs/{run_id}').get_json()['run']['nodes']}
        assert nodes['node-2']['fingerprint'] == fingerprints_for_workflow(workflow)['node-2']
        assert nodes['node-2']['status'] == 'done'

    def test_without_the_option_a_second_run_still_overwrites_the_one_file(self, client, app_module, paste, data_root):
        """The default is the old behaviour, unchanged: this is a switch, not a policy."""
        ds = _upload(client, paste)
        workflow = self._workflow('plain', ds)
        before = _export_names(data_root)
        self._run(client, app_module, workflow, 'plain-once')
        self._run(client, app_module, workflow, 'plain-twice')
        assert _export_names(data_root) - before == {'plain.csv'}


@pytest.mark.usefixtures('clean_globals')
class TestWindowedFilenames:
    """「文件名带时间范围」 and 「分片文件名加创建时间」 — the two components a crawl appends.

    The window is a fact about the CRAWL and a save node is handed only rows, so the range
    travels through the run: ``_note_window`` records it where the crawl states it,
    ``_window_for_save`` reads it back where the file is named. A range that cannot resolve
    to exactly one window is IGNORED — the file is still written under its plain name. A time
    range in the filename is decoration and must never be the reason a result is withheld; the
    wrong-month table is avoided simply by not tagging, not by refusing the whole export.
    """

    ROWS = [{'正文': 'a'}, {'正文': 'b'}]

    def _save(self, app_module, tmp_path, monkeypatch, **params):
        monkeypatch.setattr(app_module.Config, 'EXPORT_DIR', str(tmp_path))
        node = _node('node-9', 'output', {'operation': 'save', 'format': 'csv', **params}, 'save')
        return app_module._execute_output_node(node, list(self.ROWS))

    def test_a_recorded_window_lands_before_the_extension(self, app_module, tmp_path, monkeypatch):
        app_module._note_window(None, '2026-01-01', '2026-03-15')
        result = self._save(app_module, tmp_path, monkeypatch, filename='weibo.csv', filename_time_range=True)
        assert isinstance(result, list) and len(result) == 2, 'the table must still travel downstream'
        assert [p.name for p in tmp_path.iterdir()] == ['weibo_20260101_to_20260315.csv']

    def test_a_window_the_user_padded_still_names_the_file(self, app_module, tmp_path, monkeypatch):
        app_module._note_window(None, ' 2026-01-01 ', '2026-03-15 00:00:00')
        self._save(app_module, tmp_path, monkeypatch, filename='w.csv', filename_time_range=True)
        assert [p.name for p in tmp_path.iterdir()] == ['w_20260101_to_20260315.csv']

    def test_a_chain_with_no_crawl_ignores_the_range_and_still_writes_the_file(self, app_module, tmp_path, monkeypatch):
        """An upload feeding a save node has no window at all. The ticked switch cannot be
        honoured, so it is ignored and the file is written under its plain name — the user keeps
        their data. Refusing (the old behaviour) threw away the whole result over a filename
        label, which is exactly the bug reported."""
        result = self._save(app_module, tmp_path, monkeypatch, filename='nowhere.csv', filename_time_range=True)
        assert isinstance(result, list) and len(result) == 2, 'a name we cannot honour must not block the table'
        assert [p.name for p in tmp_path.iterdir()] == ['nowhere.csv'], 'written plain, with no time-range tag'

    def test_two_windows_are_ignored_and_the_file_is_still_written(self, app_module, tmp_path, monkeypatch):
        """Two different windows on one path cannot be named honestly, so the tag is dropped
        rather than guessed — but the file is still produced: an ambiguous NAME is no reason to
        lose the data."""
        app_module._note_window(None, '2026-01-01', '2026-01-31')
        app_module._note_window(None, '2026-03-01', '2026-03-31')
        result = self._save(app_module, tmp_path, monkeypatch, filename='two.csv', filename_time_range=True)
        assert isinstance(result, list) and len(result) == 2, 'an ambiguous range is ignored, not fatal'
        assert [p.name for p in tmp_path.iterdir()] == ['two.csv'], 'written plain rather than mis-tagged'

    def test_the_same_window_recorded_twice_is_still_one_window(self, app_module, tmp_path, monkeypatch):
        # Two crawl nodes over ONE range is the common shape of a keyword sweep. Calling
        # that an ambiguity would refuse a file with nothing ambiguous about it.
        app_module._note_window(None, '2026-01-01', '2026-01-31')
        app_module._note_window(None, '2026-01-01', '2026-01-31')
        self._save(app_module, tmp_path, monkeypatch, filename='twice.csv', filename_time_range=True)
        assert [p.name for p in tmp_path.iterdir()] == ['twice_20260101_to_20260131.csv']

    def test_ranges_are_kept_apart_per_workflow(self, app_module):
        """A parallel canvas runs several workflows at once, and naming A's file after B's
        window is precisely the wrong-month table this switch must never produce."""
        app_module._note_window(0, '2026-01-01', '2026-01-31')
        app_module._note_window(1, '2026-03-01', '2026-03-31')
        assert app_module._window_for_save(0)[0] == '_20260101_to_20260131'
        assert app_module._window_for_save(1)[0] == '_20260301_to_20260331'
        assert app_module._window_for_save(7) == ('', app_module.t('export.window_none'))

    def test_a_window_that_was_never_stated_is_never_recorded(self, app_module):
        for blank in ((None, None), ('2026-01-01', ''), ('nonsense', '2026-03-15')):
            app_module._note_window(3, *blank)
        assert app_module.execution_state['_time_windows'].get(3, []) == [], (
            'a one-sided or unreadable range is the crawler’s own refusal, not half a name'
        )

    def test_a_new_run_starts_with_no_window_of_its_own(self, app_module):
        app_module._note_window(0, '2026-01-01', '2026-01-31')
        app_module.reset_console_state()
        assert app_module.execution_state['_time_windows'] == {}, (
            'a run must not name its files after the stretch the last one walked'
        )

    def test_the_two_components_join_in_order_and_only_when_asked(self, app_module):
        """What the crawl node appends to its own stem: the window it was told to walk,
        then the record writing the file — and neither without its switch."""
        stated = {'start_time': '2026-01-01', 'end_time': '2026-03-15', 'part_timestamp': True}
        assert app_module._name_parts(stated, '_20261002-1435-a1b2c3') == ('_20260101_to_20260315_20261002-1435-a1b2c3')
        assert app_module._name_parts(stated) == '_20260101_to_20260315', 'no stamp was asked for'
        assert app_module._name_parts({'part_timestamp': True}, '_20261002-1435-a1b2c3') == '_20261002-1435-a1b2c3'
        assert app_module._name_parts({}) == '', 'an ordinary crawl keeps the name it always had'
        # The panel stores a checkbox as a real boolean, a workflow FILE as the text
        # 'true'/'false', and an exported draft as either: all three must read as asked.
        for spelling in (True, 'true', 'True', '1', 1):
            assert app_module._name_parts({'part_timestamp': spelling}, '_S') == '_S', spelling
        for spelling in (False, 'false', '', None):
            assert app_module._name_parts({'part_timestamp': spelling}, '_S') == '', spelling

    def test_the_stamp_a_resume_reuses_is_the_record_and_not_the_clock(self, app_module, tmp_path):
        """``PartWriter`` adopts the shards an interrupted attempt flushed by matching its
        stem as a prefix. A stamp that moved between attempts would leave them orphaned
        beside a numbering restarting at 001 — which is why it is read off the record."""
        from services.run_store import RunStore

        store = RunStore(str(tmp_path / 'runs.db'))
        store.start_run('r1', 'wf', 'fp')
        first = app_module._record_export_stamp(store, 'r1')
        store.start_run('r1', 'wf', 'fp')  # what 继续 does to the same row
        assert app_module._record_export_stamp(store, 'r1') == first, 'a resume must write the same names'
        store.start_run('r2', 'wf', 'fp')
        second = app_module._record_export_stamp(store, 'r2')
        assert second != first, f'two records collided onto one file name: {first} / {second}'
        assert second.endswith('-r2'), f'the record is what makes this name unique: {second}'


class TestSentimentNode:
    """「情感极性」 end to end: a real SnowNLP pass through the executor into a CSV.

    No model download, no GPU and no LLM call, so this is the tier where the whole chain
    is honest — the node runs, the two columns land in the stored rows and in the file,
    and a mode the operation does not know fails by name instead of running something else.
    """

    ROWS = [
        {'正文': '今天玩得非常开心，风景太美了'},
        {'正文': '这服务太差了，等了两个小时没人管'},
        {'正文': '会议定于周三在报告厅举行'},
        {'正文': ''},
    ]

    def _chain(self, ds, **params):
        return _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': len(self.ROWS)}),
                _node('node-2', 'process', {'operation': 'sentiment', 'text_column': '正文', **params}, 'sentiment'),
                _node('node-3', 'output', {'operation': 'save', 'format': 'csv', 'filename': 'senti.csv'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )

    def test_the_default_mode_labels_the_column_and_writes_it_out(self, client, app_module, paste, data_root):
        ds = paste(self.ROWS, name='senti.csv')
        started = client.post('/api/workflow/execute', json={'workflow': self._chain(ds), 'workflow_name': 'senti'})
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        statuses = app_module._RUN_STORE.node_statuses(run_id)
        assert statuses['node-2']['status'] == 'done', statuses['node-2'].get('error')
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
        assert {'sentiment', 'score'} <= set(rows[0]), sorted(rows[0])
        assert [r['sentiment'] for r in rows[:2]] == ['positive', 'negative']
        # An empty text is not a judgement of 中性; the row keeps saying nothing.
        assert rows[3]['sentiment'] == '' and rows[3]['score'] in (None, ''), rows[3]
        written = pd.read_csv(data_root / 'data' / 'exports' / 'senti.csv', encoding='utf-8-sig')
        assert {'sentiment', 'score'} <= set(written.columns), sorted(written.columns)
        assert len(written) == 4

    def test_the_whole_chain_needs_no_api_key_for_any_of_the_three_free_modes(self, client, app_module):
        """The gate is what refuses a run before it starts, and three of these four modes
        cost nothing: a canvas that asked for SnowNLP must not be blocked for a key, which
        is exactly the trap ``mode != 'ml'`` set for every other spelling."""
        for mode in ('snownlp', 'ml', 'bert'):
            node = _node('n', 'process', {'operation': 'sentiment', 'mode': mode}, 'sentiment')
            assert app_module._workflow_needs_llm({'nodes': [node]}) is False, mode
        llm = _node('n', 'process', {'operation': 'sentiment', 'mode': 'llm'}, 'sentiment')
        assert app_module._workflow_needs_llm({'nodes': [llm]}) is True

    def test_a_mode_the_operation_does_not_know_fails_the_node_by_name(self, client, app_module, paste):
        ds = paste(self.ROWS, name='senti-bogus.csv')
        started = client.post(
            '/api/workflow/execute', json={'workflow': self._chain(ds, mode='TextBlob'), 'workflow_name': 'senti-bogus'}
        )
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        statuses = app_module._RUN_STORE.node_statuses(run_id)
        assert statuses['node-2']['status'] == 'failed', statuses['node-2']
        assert 'TextBlob' in statuses['node-2']['error'], statuses['node-2']['error']
        assert 'mode' in statuses['node-2']['error'], 'the refusal must name the field it is refusing'
        assert app_module._RUN_STORE.load_rows(run_id, 'node-2') == [], 'a refused mode stores nothing'

    def test_an_inverted_threshold_band_fails_rather_than_answering_every_row_positive(self, client, app_module, paste):
        ds = paste(self.ROWS, name='senti-band.csv')
        started = client.post(
            '/api/workflow/execute',
            json={'workflow': self._chain(ds, pos_threshold=0.2, neg_threshold=0.8), 'workflow_name': 'senti-band'},
        )
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        statuses = app_module._RUN_STORE.node_statuses(run_id)
        assert statuses['node-2']['status'] == 'failed', statuses['node-2']
        assert '0.2' in statuses['node-2']['error'], statuses['node-2']['error']

    def test_bert_refuses_by_name_instead_of_running_snownlp(self, client, app_module, paste):
        """The bert node must refuse with a NAMED BERT reason and store nothing — never fall
        back to SnowNLP. Which reason fires is environment-dependent: a machine without the
        torch/transformers stack refuses for the missing piece, and this machine (which HAS
        torch) refuses because the chain names no model. Both sentences lead with ``BERT``,
        so the pin is on the refusal being about the requested mode, not on which machine it is.
        """
        ds = paste(self.ROWS, name='senti-bert.csv')
        started = client.post(
            '/api/workflow/execute', json={'workflow': self._chain(ds, mode='bert'), 'workflow_name': 'senti-bert'}
        )
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        statuses = app_module._RUN_STORE.node_statuses(run_id)
        assert statuses['node-2']['status'] == 'failed', statuses['node-2']
        error = statuses['node-2']['error'] or ''
        # A named BERT refusal (missing backend OR unnamed model), never SnowNLP doing the work.
        assert 'BERT' in error, error
        assert app_module._RUN_STORE.load_rows(run_id, 'node-2') == [], 'a refused mode stores nothing'

    def test_a_missing_text_column_is_refused_before_any_row_is_read(self, client, app_module, paste):
        ds = paste([{'标题': '只有标题'}] * 3, name='senti-nocol.csv')
        workflow = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 3}),
                _node('node-2', 'process', {'operation': 'sentiment', 'text_column': '正文'}, 'sentiment'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'senti-nocol'})
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        statuses = app_module._RUN_STORE.node_statuses(run_id)
        assert statuses['node-2']['status'] == 'failed', (
            'a node that read nothing and changed nothing must not settle DONE'
        )


class TestResumeNode:
    def test_explicit_pick_adopts_a_finished_runs_table(self, client, app_module, paste):
        ds = _upload(client, paste)
        first = _wf(
            [
                _node('node-1', 'upload', {'dataset_id': ds, 'row_count': 4}),
                _node('node-2', 'analysis', {'steps': [{'op': 'drop_null', 'params': {'columns': ['分数']}}]}),
                _node('node-3', 'output', {'operation': 'save', 'format': 'csv', 'filename': 'r1'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': first, 'workflow_name': 'r1'})
        assert _wait(app_module)
        run1 = started.get_json()['run_id']

        second = _wf(
            [
                _node('node-1', 'resume', {'resume_run_id': run1, 'resume_node_id': 'node-2', 'resume_limit': 0}),
                _node('node-2', 'output', {'operation': 'save', 'format': 'csv', 'filename': 'r2'}, 'save'),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started2 = client.post('/api/workflow/execute', json={'workflow': second, 'workflow_name': 'r2'})
        assert _wait(app_module)
        rows = app_module._RUN_STORE.load_rows(started2.get_json()['run_id'], 'node-1')
        assert len(rows) == 4
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert run1 in blob, 'the adoption must name its source run'

    def test_auto_discovery_adopts_the_biggest_table_of_a_broken_same_shape_run(self, client, app_module, data_root):
        from services.run_store import NODE_DONE, RUN_INTERRUPTED, RunStore, workflow_fingerprint

        # A prior run of EXACTLY this shape (what "继续" re-executes) is
        # forged straight into the store: node-1 is the resume node's own id
        # and its stored table is what the newest attempt must adopt.
        lonely = _wf([_node('node-1', 'resume', {})], [])
        fp = workflow_fingerprint(lonely)
        db = str(data_root / 'data' / 'forged-runs.db')
        maker = RunStore(db)
        maker.start_run('forged-1', 'auto-resume', fp, mode='serial', headless=True, llm=None, lang='en', node_total=1)
        maker.begin_node('forged-1', 'node-1', 'resume')
        maker.append_rows('forged-1', 'node-1', [{'x': 1}, {'x': 2}, {'x': 3}])
        maker.finish_node('forged-1', 'node-1', NODE_DONE)
        maker.finish_run('forged-1', RUN_INTERRUPTED)
        maker._conn.close()

        app_module._RUN_STORE = RunStore(db)
        started = client.post('/api/workflow/execute', json={'workflow': lonely, 'workflow_name': 'auto-resume'})
        assert _wait(app_module)
        rows = app_module._RUN_STORE.load_rows(started.get_json()['run_id'], 'node-1')
        assert [r['x'] for r in rows] == [1, 2, 3]

    def test_a_resume_node_with_nothing_to_adopt_produces_no_rows_no_crash(self, client, app_module):
        lonely = _wf([_node('node-1', 'resume', {})], [])
        started = client.post('/api/workflow/execute', json={'workflow': lonely, 'workflow_name': 'no-run'})
        assert _wait(app_module)
        assert app_module._RUN_STORE.row_count(started.get_json()['run_id'], 'node-1') == 0
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'no run selected' in blob or '没有选择运行记录' in blob


class TestBrowserReaper:
    def test_a_browser_ignoring_close_is_killed_by_pid_and_the_call_returns(self, app_module):
        """Stop must not hang on a wedged driver — and the fallback kill is
        PID-targeted (tree included), never a global chromedriver massacre."""
        import subprocess
        import sys
        import types

        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])

        class _Stuck:
            def __init__(self, proc):
                self.driver = types.SimpleNamespace(service=types.SimpleNamespace(process=proc))

            def close(self):
                time.sleep(30)  # the wedged quit this path exists for

        started = time.monotonic()
        app_module._close_login_browser(_Stuck(child), quit_timeout=0.5)
        assert time.monotonic() - started < 20, 'the bounded close must return'
        child.wait(timeout=10)
        assert child.poll() is not None, 'the ignored driver process must be reaped by PID'

    def test_a_null_crawler_is_nothing_to_do(self, app_module):
        app_module._close_login_browser(None)  # must not raise


class TestStopAndKill:
    def test_stop_while_idle_is_safe(self, client, app_module):
        resp = client.post('/api/workflow/stop')
        assert resp.status_code == 200 and resp.get_json()['ok'] is True
        assert app_module.execution_state['running'] is False
        assert client.get('/api/workflow/status').get_json()['logs'] == []

    def test_stop_aborts_a_crawl_keeps_rows_and_marks_the_run_interrupted(self, client, app_module, monkeypatch):
        class _Slow:
            def __init__(self, *a, **k):
                self._s = None

            def set_sink(self, s):
                self._s = s

            def set_cursor_sink(self, s):
                pass

            def seed(self, rows):
                pass

            def close(self):
                pass

            def search(self, *a, **k):
                kept = []
                i = 0
                while app_module.execution_state['running'] and i < 100000:
                    row = {'标题': f'r{i}'}
                    i += 1
                    if self._s is None or self._s(row):
                        kept.append(row)
                    if i % 50 == 0:
                        time.sleep(0.01)
                return kept

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _Slow())
        workflow = _wf([_node('node-1', 'source', {'platform': 'zhihu', 'keyword': 'k', 'target_count': 99999})], [])
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'slow'})
        assert started.get_json()['ok'] is True
        run_id = started.get_json()['run_id']
        for _ in range(200):
            if app_module._RUN_STORE.row_count(run_id, 'node-1') > 0:
                break
            time.sleep(0.05)
        stopped = client.post('/api/workflow/stop')
        assert stopped.get_json()['ok'] is True
        assert _wait(app_module)
        run = app_module._RUN_STORE.get_run(run_id)
        assert run['status'] == 'interrupted', 'a stopped run must be resumable, not completed'
        assert run['nodes'][0]['row_count'] > 0, 'everything the stopped crawl kept must stay stored'

    def test_stopping_keeps_the_console_that_explains_it(self, client, app_module, monkeypatch):
        """Stop used to wipe the console and zero the node counters.

        The consequence was a summary line that read "运行结束（0/0 个节点完成）"
        for a run that had just finished two nodes, printed into a console the
        user had been watching — the record of what the run did, deleted by the
        act of stopping it.
        """

        class _Slow:
            def __init__(self, *a, **k):
                self._s = None

            def set_sink(self, s):
                self._s = s

            def search(self, *a, **k):
                for i in range(500):
                    if self._s:
                        self._s({'标题': f'row {i}', '链接': f'https://www.zhihu.com/question/{i}'})
                    time.sleep(0.01)
                return []

            def close(self):
                pass

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _Slow())
        workflow = _wf([_node('node-1', 'source', {'platform': 'zhihu', 'keyword': 'k', 'target_count': 99999})], [])
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'slow-console'})
        for _ in range(200):
            if app_module.execution_state['logs']:
                break
            time.sleep(0.05)
        before = list(client.get('/api/workflow/status').get_json()['logs'])
        client.post('/api/workflow/stop')
        assert _wait(app_module)
        after = client.get('/api/workflow/status').get_json()['logs']
        assert after, 'stopping must not erase the console the user was reading'
        assert before and after[: len(before)] == before, 'the lines already earned must survive in order'
        assert app_module.execution_state['total_nodes'] > 0, 'the summary must still know the run had nodes'

    def test_kill_protects_the_main_thread_and_answers_honestly(self, client):
        import threading

        main_ident = threading.main_thread().ident
        resp = client.post('/api/workflow/processes/kill', json={'ident': main_ident})
        assert resp.status_code == 403, 'MainThread must never be killable'

        resp = client.post('/api/workflow/processes/kill', json={'ident': 1234567890})
        assert resp.status_code == 404

        resp = client.post('/api/workflow/processes/kill', json={})
        assert resp.status_code == 400

    def test_kill_terminates_a_chosen_worker_thread(self, client):
        import threading

        started_evt = threading.Event()

        def _idle():
            # The kill raises SystemExit asynchronously — it lands at the next
            # bytecode boundary. A thread parked in one long C-level sleep()
            # cannot be interrupted, so the worker ticks instead. Catching the
            # SystemExit is what a well-behaved worker does: the thread exits
            # cleanly (and pytest is not polluted by an "unhandled" warning).
            started_evt.set()
            try:
                for _ in range(3000):
                    time.sleep(0.01)
            except SystemExit:
                return

        t = threading.Thread(target=_idle, name='disposable-worker', daemon=True)
        t.start()
        assert started_evt.wait(5)
        resp = client.post('/api/workflow/processes/kill', json={'ident': t.ident})
        assert resp.status_code == 200 and resp.get_json()['ok'] is True
        t.join(timeout=5)
        assert not t.is_alive(), 'the killed thread must actually die'

    def test_kill_protects_the_run_supervisor_and_live_pool_workers(self, client, app_module):
        import threading

        started = threading.Event()

        def _idle():
            started.set()
            try:
                for _ in range(3000):
                    time.sleep(0.01)
            except SystemExit:
                return

        # The supervisor thread named 'run' is protected by name — the whole point of
        # naming it. Before the fix it reported as "Thread-N" and was freely killable.
        run_thread = threading.Thread(target=_idle, name='run', daemon=True)
        run_thread.start()
        assert started.wait(5)
        resp = client.post('/api/workflow/processes/kill', json={'ident': run_thread.ident})
        assert resp.status_code == 403, 'the live run supervisor must never be killable'

        # A parallel run crawls on executor pool threads; while a run is live those are
        # off-limits too (a SystemExit there can orphan a browser / hold its profile).
        pool = threading.Thread(target=_idle, name='ThreadPoolExecutor-0_1', daemon=True)
        pool.start()
        app_module.execution_state['running'] = True
        try:
            resp = client.post('/api/workflow/processes/kill', json={'ident': pool.ident})
            assert resp.status_code == 403, 'a live crawl worker must not be killable'
        finally:
            app_module.execution_state['running'] = False
        # Once no run is live, a stuck pool thread is disposable again (use Stop otherwise).
        resp = client.post('/api/workflow/processes/kill', json={'ident': pool.ident})
        assert resp.status_code == 200
        run_thread.join(timeout=5)
        pool.join(timeout=5)


class TestQuietNodesInConsole:
    """A 工作流命名 or 上传文件 node has no work to announce.

    Both are pure plumbing: one carries a label, the other re-reads a file the user
    already pointed at. Printing "Executing node …" and "Node … completed (2/4)" for
    each of them made the lines that do carry information — a crawl, a failure, a
    restored node — the minority of the console on an otherwise quiet canvas. What
    those nodes say *about themselves* (which file, how many rows) and anything that
    went wrong still has to be printed.
    """

    def _flow(self, ds, steps=None):
        nodes = [
            _node('node-1', 'name', {'workflow_name': '城市统计'}),
            _node('node-2', 'upload', {'dataset_id': ds, 'dataset_name': 'nodes.csv', 'row_count': 4}),
            _node('node-3', 'analysis', {'steps': steps or [{'op': 'drop_duplicates', 'params': {}}]}),
            _node('node-4', 'output', {'format': 'csv', 'filename': 'quiet'}, 'save'),
        ]
        conns = [
            {'from': 'node-1', 'to': 'node-2'},
            {'from': 'node-2', 'to': 'node-3'},
            {'from': 'node-3', 'to': 'node-4'},
        ]
        return _wf(nodes, conns)

    def _logs(self, client, app_module):
        return '\n'.join(client.get('/api/workflow/status').get_json()['logs'])

    def test_a_clean_run_prints_nothing_for_the_plumbing_nodes(self, client, app_module, paste, data_root):
        ds = paste(RECORDS, name='nodes.csv')
        client.post('/api/workflow/execute', json={'workflow': self._flow(ds), 'workflow_name': 'quiet'})
        assert _wait(app_module)
        blob = self._logs(client, app_module)
        # The two node types are named here and nowhere else in this run's lines.
        for phrase in ('Executing node: name #node-1', 'Executing node: upload #node-2'):
            assert phrase not in blob, f'{phrase!r} is chatter about a node that did nothing:\n{blob}'
        assert 'name #node-1 completed' not in blob and 'upload #node-2 completed' not in blob, blob
        # The nodes that do work still report themselves, and so does the progress.
        assert 'analysis #node-3 completed' in blob, blob
        assert 'output #node-4 completed' in blob, blob

    def test_the_upload_still_says_what_it_loaded(self, client, app_module, paste, data_root):
        """Quieting the generic chatter must not hide the one fact this node owns:
        which file reached the run, and how many rows came out of it."""
        ds = paste(RECORDS, name='nodes.csv')
        client.post('/api/workflow/execute', json={'workflow': self._flow(ds), 'workflow_name': 'quiet'})
        assert _wait(app_module)
        blob = self._logs(client, app_module)
        assert 'Loaded uploaded file nodes.csv: 4 rows' in blob, blob

    def test_a_failing_plumbing_node_is_still_reported(self, client, app_module, paste, data_root):
        """An upload whose file went missing is exactly the case the console exists
        for — silencing a node's routine lines can never mean silencing its failure."""
        ds = paste(RECORDS, name='nodes.csv')
        flow = self._flow(ds)
        assert client.post('/api/workflow/execute', json={'workflow': flow, 'workflow_name': 'q'}).status_code == 200
        assert _wait(app_module)
        client.delete(f'/api/data/datasets/{ds}')
        second = client.post('/api/workflow/execute', json={'workflow': flow, 'workflow_name': 'q'}).get_json()
        assert second['ok'] is True, second
        assert _wait(app_module)
        record = app_module.get_run_store().get_run(second['run_id'])
        assert record['status'] == 'failed', record
        nodes = {node['node_id']: node for node in record['nodes']}
        assert nodes['node-2']['status'] == 'failed', nodes
        assert nodes['node-2'].get('error'), 'the reason must be stored, not just the status'
        blob = self._logs(client, app_module)
        assert 'upload #node-2' in blob, f'the failing node was silenced along with its routine lines:\n{blob}'
