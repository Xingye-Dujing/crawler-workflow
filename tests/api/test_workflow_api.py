"""Tests for the workflow endpoints, ending in a real execute round-trip.

``/api/workflow/*`` is the whole product in miniature: a canvas definition is
saved as JSON, reloaded with its Upload nodes re-attached to the stored files,
and then executed by a background thread that checkpoints every node into the
run store. The execute test in the middle is the plan's end-to-end invariant —
file in, cleaned rows out, and a durable record that says exactly what each
node produced — so it deliberately uses only non-crawling, non-LLM nodes:
``upload`` → ``analysis`` → ``output``. A ``source`` node would start Selenium
and a ``process`` node with an LLM operation would need a daemon, and neither
belongs in a test that has to run offline.

The polling tests carry ``@pytest.mark.serial`` because the worker installs a
``_LogTee`` over ``sys.stdout`` for the duration of the run.
"""

import os
import time

import pandas as pd
import pytest

pytestmark = pytest.mark.api


# Six rows, two of which exist only to be removed: one has no score (a null step
# must drop it) and one repeats a title (de-duplication must drop it).
E2E_RECORDS = [
    {'title': 'sanya', 'score': 3, 'city': 'Sanya'},
    {'title': 'haikou', 'score': 5, 'city': 'Haikou'},
    {'title': 'sanya', 'score': 2, 'city': 'Sanya'},
    {'title': 'boao', 'score': '', 'city': 'Boao'},
    {'title': 'xinglong', 'score': 7, 'city': 'Sanya'},
    {'title': 'wanning', 'score': 9, 'city': 'Haikou'},
]
E2E_SURVIVORS = ['sanya', 'haikou', 'xinglong', 'wanning']
E2E_STEPS = [
    {'op': 'drop_null', 'params': {'columns': ['score']}},
    {'op': 'drop_duplicates', 'params': {'columns': ['title']}},
]


def _node(node_id: str, node_type: str, operation: str = '', params: dict = None) -> dict:
    node = {'id': node_id, 'type': node_type, 'title': node_type, 'params': params or {}}
    if operation:
        node['operation'] = operation
    return node


def _workflow(nodes, connections, settings=None):
    return {'nodes': nodes, 'connections': connections, 'settings': settings or {'mode': 'serial'}}


def _e2e_workflow(dataset_id: str, filename: str = 'e2e') -> dict:
    """upload → analysis → output, wired the way the canvas wires it."""
    return _workflow(
        [
            _node('node-1', 'upload', params={'dataset_id': dataset_id, 'dataset_name': 'e2e.csv', 'row_count': 6}),
            _node('node-2', 'analysis', params={'steps': E2E_STEPS}),
            _node('node-3', 'output', operation='save', params={'format': 'csv', 'filename': filename}),
        ],
        [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}],
    )


def _wait_for_worker(app_module, timeout: float = 30.0) -> bool:
    """Poll until the execute thread has really finished, not just stopped.

    ``running`` is cleared at the top of the worker's ``finally``, while the run
    record is still being closed out below it — so the death of the thread is
    the only observation that guarantees the store is complete.
    """
    thread = app_module.execution_state.get('thread')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = thread is not None and thread.is_alive()
        if not app_module.execution_state['running'] and not alive:
            return True
        time.sleep(0.1)
    return False


class TestWorkflowCrud:
    def test_save_list_load_delete_round_trip(self, client, data_root):
        workflow = _workflow([_node('node-1', 'upload', params={'dataset_id': 'x'})], [])
        response = client.post('/api/workflow/save', json={'name': 'crud-basic', 'workflow': workflow})
        body = response.get_json()
        assert response.status_code == 200
        assert body['ok'] is True
        # The path is the file the manager wrote, inside the isolated dir.
        assert os.path.basename(body['path']) == 'crud-basic.json'
        assert (data_root / 'data' / 'workflows' / 'crud-basic.json').exists()
        assert body['datasets'] == 1

        assert 'crud-basic' in client.get('/api/workflow/list').get_json()['workflows']

        loaded = client.get('/api/workflow/load', query_string={'name': 'crud-basic'}).get_json()
        assert loaded['ok'] is True
        # The name travels inside the file, so a reopened canvas knows itself.
        assert loaded['workflow']['name'] == 'crud-basic'
        assert [node['id'] for node in loaded['workflow']['nodes']] == ['node-1']

        assert client.post('/api/workflow/delete', json={'name': 'crud-basic'}).get_json() == {'ok': True}
        assert 'crud-basic' not in client.get('/api/workflow/list').get_json()['workflows']
        assert not (data_root / 'data' / 'workflows' / 'crud-basic.json').exists()

    def test_saving_twice_under_one_name_replaces_it(self, client):
        first = _workflow([_node('node-1', 'upload', params={'dataset_id': 'a'})], [])
        second = _workflow([_node('node-1', 'upload', params={'dataset_id': 'b'}), _node('node-2', 'output')], [])
        client.post('/api/workflow/save', json={'name': 'overwrite-me', 'workflow': first})
        client.post('/api/workflow/save', json={'name': 'overwrite-me', 'workflow': second})

        listed = client.get('/api/workflow/list').get_json()['workflows']
        assert listed.count('overwrite-me') == 1
        workflow = client.get('/api/workflow/load', query_string={'name': 'overwrite-me'}).get_json()['workflow']
        assert [node['id'] for node in workflow['nodes']] == ['node-1', 'node-2']

    def test_a_typed_name_becomes_one_safe_file_stem(self, client, data_root):
        workflow = _workflow([_node('node-1', 'upload', params={'dataset_id': 'a'})], [])
        messy = '../../etc/passwd'
        body = client.post('/api/workflow/save', json={'name': messy, 'workflow': workflow}).get_json()
        stem = os.path.splitext(os.path.basename(body['path']))[0]
        # Separators are replaced, so the file stays inside the workflow dir.
        assert stem and os.sep not in stem and '/' not in stem
        assert list((data_root / 'data').glob('*passwd*')) == []
        loaded = client.get('/api/workflow/load', query_string={'name': messy}).get_json()
        assert loaded['ok'] is True
        assert loaded['workflow']['name'] == stem

    def test_long_names_are_capped_before_hitting_the_filesystem(self, client):
        workflow = _workflow([_node('node-1', 'upload', params={'dataset_id': 'a'})], [])
        body = client.post('/api/workflow/save', json={'name': 'w' * 200, 'workflow': workflow}).get_json()
        assert os.path.splitext(os.path.basename(body['path']))[0] == 'w' * 60

    def test_load_of_an_unknown_workflow_is_404(self, client):
        response = client.get('/api/workflow/load', query_string={'name': 'never-saved'})
        assert response.status_code == 404
        assert response.get_json() == {'ok': False, 'error': 'Not found'}

    def test_delete_of_an_unknown_workflow_is_not_an_error(self, client):
        assert client.post('/api/workflow/delete', json={'name': 'ghost-workflow'}).get_json() == {'ok': True}

    def test_list_of_an_empty_dir_is_empty_not_missing(self, client):
        body = client.get('/api/workflow/list').get_json()
        assert body['ok'] is True
        assert isinstance(body['workflows'], list)

    def test_load_reconnects_upload_nodes_to_their_files(self, client, paste):
        dataset_id = paste(E2E_RECORDS, name='orders.csv')
        upload_params = {'dataset_id': dataset_id, 'dataset_name': 'orders.csv', 'row_count': 6}
        workflow = _workflow([_node('node-1', 'upload', params=upload_params)], [])
        client.post('/api/workflow/save', json={'name': 'rebind', 'workflow': workflow})

        def _report():
            body = client.get('/api/workflow/load', query_string={'name': 'rebind'}).get_json()
            return body['datasets'][0], body['workflow']['nodes'][0]['params']

        entry, params = _report()
        assert entry['restored'] is True and entry['missing'] is False
        assert params['dataset_name'] == 'orders.csv' and params['row_count'] == 6

        # Lose the file and the same node reports it as missing, with the id
        # cleared so the UI asks for the file instead of pretending.
        assert client.delete(f'/api/data/datasets/{dataset_id}').get_json()['ok'] is True
        entry, params = _report()
        assert entry['missing'] is True and entry['restored'] is False
        assert params['dataset_id'] == ''

        # Re-uploading the same rows gives the same content-addressed id back.
        assert paste(E2E_RECORDS, name='orders.csv') == dataset_id
        entry, _params = _report()
        assert entry['restored'] is True


class TestWorkflowExecute:
    def test_status_answers_a_quiet_console_before_any_run(self, client):
        body = client.get('/api/workflow/status').get_json()
        assert body['running'] is False
        assert body['logs'] == [] and body['log_total'] == 0
        assert body['results'] == [] and body['workflows'] == []
        assert body['mode'] in ('serial', 'parallel')
        assert body['total_nodes'] == 0 and body['chart_results'] == {}

    def test_processes_only_reports_threads(self, client, app_module):
        """Read-only by inspection: it enumerates ``threading.enumerate()`` and
        reads ``execution_state``; it never signals or kills anything."""
        body = client.get('/api/workflow/processes').get_json()
        assert body['running'] is False
        assert body['active_crawlers'] == 0
        assert body['executor_pool_alive'] is False
        names = {thread['name'] for thread in body['threads']}
        assert 'MainThread' in names
        assert {'name', 'daemon', 'alive', 'ident'} <= set(body['threads'][0])
        assert app_module.execution_state['running'] is False

    @pytest.mark.serial
    def test_execute_end_to_end_from_pasted_file_to_csv(self, client, app_module, paste, data_root):
        dataset_id = paste(E2E_RECORDS, name='e2e.csv')
        workflow = _e2e_workflow(dataset_id, filename='workflow-e2e')
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'workflow-e2e'})
        assert started.status_code == 200
        run_id = started.get_json()['run_id']
        assert _wait_for_worker(app_module), 'the execute thread did not finish in time'

        # ── the file the run was supposed to produce ──────────────────
        export = data_root / 'data' / 'exports' / 'workflow-e2e.csv'
        assert export.exists()
        frame = pd.read_csv(export, encoding='utf-8-sig')
        # The order is alphabetical because Flask's JSON provider sorts object
        # keys when the test client serialises the request body; the set of
        # columns surviving the pipeline is what the run is supposed to decide.
        assert sorted(frame.columns) == ['city', 'score', 'title']
        assert frame['title'].tolist() == E2E_SURVIVORS
        assert frame['score'].tolist() == [3, 5, 7, 9]

        # ── the durable record of the same run ────────────────────────
        store = app_module._RUN_STORE
        assert store is not None, 'the client fixture must hand out a private run store'
        run = store.get_run(run_id)
        assert run['status'] == 'completed'
        assert run['workflow_name'] == 'workflow-e2e'
        assert run['node_total'] == 3 and run['node_done'] == 3
        nodes = {node['node_id']: node for node in run['nodes']}
        assert [node['status'] for node in nodes.values()] == ['done', 'done', 'done']
        # The pipeline really shrank the table: six rows in, four out of both
        # the analysis node and the save node, which passes its input through.
        assert [nodes[nid]['row_count'] for nid in ('node-1', 'node-2', 'node-3')] == [6, 4, 4]
        assert store.row_count(run_id, 'node-1') == 6
        assert [row['title'] for row in store.load_rows(run_id, 'node-2')] == E2E_SURVIVORS

        # ── nothing expensive or offline-hostile ran underneath ───────
        stats = store.stats()
        assert stats['runs'] == 1 and stats['interrupted'] == 0
        assert stats['node_rows'] == 14  # 6 + 4 + 4
        assert stats['cache_entries'] == 0, 'no model may be consulted by this workflow'
        assert stats['seen_keys'] == 0, 'no crawler ran, so no item may be claimed'

        # ── the console tells the same story ──────────────────────────
        status = client.get('/api/workflow/status').get_json()
        assert status['running'] is False
        assert status['total_nodes'] == 3 and status['completed_nodes'] == 3
        assert sorted(status['results']) == ['node-1', 'node-2', 'node-3']
        assert any('drop_duplicates' in line for line in status['logs'])
        assert any('Data saved to' in line for line in status['logs'])

        # ── and the history panel saw it (metrics, not rows) ──────────
        history = client.get('/api/history/runs', query_string={'limit': 50}).get_json()
        mine = [entry for entry in history['runs'] if entry['workflow_name'] == 'workflow-e2e']
        assert len(mine) == 1, 'one execution must land as exactly one history run'
        # One 'rows' metric per node that produced a table; no emotion or
        # tendency series, because nothing labelled anything.
        assert mine[0]['metric_count'] == 3
        assert 'workflow-e2e' in history['workflow_names']
        series = client.get('/api/history/series', query_string={'workflow_name': 'workflow-e2e'}).get_json()['rows']
        assert {row['metric'] for row in series} == {'rows'}
        # All three nodes keep their own point even though analysis and output
        # reported the same row count in the same second — the read-time
        # dedupe keys on node_id too (see test_stats_api.py::TestHistoryEndpoints).
        assert series
        assert {row['node_id'] for row in series} == {'node-1', 'node-2', 'node-3'}
        assert len(series) == 3

    @pytest.mark.serial
    def test_execute_rejects_a_second_run_while_one_is_running(self, client, app_module):
        app_module.execution_state['running'] = True
        response = client.post('/api/workflow/execute', json={'workflow': _e2e_workflow('anything')})
        assert response.status_code == 400
        assert 'already running' in response.get_json()['error']

    def test_execute_refuses_an_llm_workflow_without_a_model(self, client, app_module):
        """A run that would call a model must say so up front. That a run which
        will not call one is allowed through model-less is proven by the
        end-to-end test above."""
        workflow = _workflow([_node('node-1', 'process', operation='clean', params={'text_column': 'title'})], [])
        ollama = client.post('/api/workflow/execute', json={'workflow': workflow}).get_json()
        assert 'No Ollama model selected' in ollama['error']

        openrouter = client.post(
            '/api/workflow/execute',
            json={'workflow': workflow, 'llm': {'provider': 'openrouter'}},
        ).get_json()
        assert 'OpenRouter API key is missing' in openrouter['error']

        named = client.post(
            '/api/workflow/execute',
            json={'workflow': workflow, 'llm': {'provider': 'openrouter', 'api_key': 'k'}},
        ).get_json()
        assert 'No OpenRouter model selected' in named['error']
        # Every refusal happened before a thread was started.
        assert app_module.execution_state['running'] is False

    @pytest.mark.serial
    def test_validation_errors_are_logged_instead_of_running(self, client, app_module):
        workflow = _workflow(
            [_node('node-1', 'upload', params={}), _node('node-2', 'analysis', params={'steps': E2E_STEPS})],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'invalid-wf'})
        assert started.status_code == 200
        assert _wait_for_worker(app_module)

        status = client.get('/api/workflow/status').get_json()
        assert status['running'] is False
        assert status['total_nodes'] == 0 and status['completed_nodes'] == 0
        assert any('Validation error' in line for line in status['logs'])
        assert any('upload node has no file selected' in line for line in status['logs'])
        # A definition mistake is not a resumable state, so nothing was booked.
        assert app_module._RUN_STORE.get_run(started.get_json()['run_id']) is None

    @pytest.mark.serial
    def test_a_stale_upload_fails_its_node_and_skips_downstream(self, client, app_module):
        ghost = {'dataset_id': 'gone', 'dataset_name': 'ghost.csv', 'row_count': 6}
        workflow = _workflow(
            [_node('node-1', 'upload', params=ghost), _node('node-2', 'analysis', params={'steps': E2E_STEPS})],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'stale-upload'})
        run_id = started.get_json()['run_id']
        assert _wait_for_worker(app_module)

        run = app_module._RUN_STORE.get_run(run_id)
        nodes = {node['node_id']: node for node in run['nodes']}
        assert nodes['node-1']['status'] == 'failed'
        assert 'dataset is gone' in nodes['node-1']['error']
        assert nodes['node-1']['row_count'] == 0
        # Empty upstream is reported as skipped, never as a node that ran.
        assert nodes['node-2']['status'] == 'skipped'
        # The dead branch is contained (downstream skipped, rows kept), but
        # the RUN must not claim 'completed' with a failed node inside — a
        # completed run never appears in the resume banner, and the gap would
        # be silent forever.
        assert run['status'] == 'failed'
        assert run['node_done'] == 1, 'a skipped node must not count as done'

    @pytest.mark.serial
    def test_resuming_the_same_workflow_reuses_stored_rows(self, client, app_module, paste):
        """Re-running an identical workflow must not recompute the upload node.

        This is the property 断点续跑 rests on, minus the interruption: the store
        answers a DONE node with ``restored`` rows instead of running it again,
        so a resume pays for nothing it already has.
        """
        dataset_id = paste(E2E_RECORDS, name='reuse.csv')
        workflow = _e2e_workflow(dataset_id, filename='reuse-once')
        first = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'reuse-test'})
        assert first.status_code == 200
        run_id = first.get_json()['run_id']
        assert _wait_for_worker(app_module)

        second = client.post(
            '/api/workflow/execute',
            json={'workflow': workflow, 'workflow_name': 'reuse-test', 'resume_run_id': run_id},
        ).get_json()
        assert second['run_id'] == run_id
        assert _wait_for_worker(app_module)

        run = app_module._RUN_STORE.get_run(run_id)
        assert run['status'] == 'completed'
        nodes = {node['node_id']: node for node in run['nodes']}
        assert nodes['node-1']['status'] == 'restored'
        assert nodes['node-1']['row_count'] == 6
        # Nothing extra was stored: the same six rows, reused in place.
        assert app_module._RUN_STORE.row_count(run_id, 'node-1') == 6
        assert app_module._RUN_STORE.stats()['runs'] == 1


class FakeSinkCrawler:
    """A crawler stand-in that streams through the REAL sink plumbing: every
    row passes the tee in _execute_source_node (ledger + PartWriter), so the
    part-file behaviour under test is the production one."""

    def __init__(self, rows):
        self.rows = rows
        self.driver = None
        self._sink = None

    def set_sink(self, sink):
        self._sink = sink

    def set_cursor_sink(self, sink):
        pass

    def seed(self, saved):
        pass

    def close(self):
        pass

    def search(self, keyword=None, target_count=None, **kw):
        kept = []
        for row in self.rows:
            if self._sink is None or self._sink(row):
                kept.append(row)
        return kept


class TestProgressiveOutput:
    """分批输出 (source part files) and 实时导出 (LLM live snapshot)."""

    @pytest.mark.serial
    @pytest.mark.parametrize(
        ('keep_parts', 'expect_parts'),
        [(False, 0), (True, 2)],
        ids=['parts-removed', 'parts-kept'],
    )
    def test_source_node_writes_part_files_and_merges(
        self, client, app_module, monkeypatch, data_root, keep_parts, expect_parts
    ):
        rows = [{'作者': f'a{i}', '正文': f'body {i}'} for i in range(5)]
        monkeypatch.setattr(
            app_module,
            'get_crawler',
            lambda platform, headless=True, cookie_dir=None: FakeSinkCrawler(rows),
        )
        workflow = _workflow(
            [
                _node(
                    'node-1',
                    'source',
                    params={
                        'platform': 'zhihu',
                        'keyword': '测试',
                        'target_count': 5,
                        'part_size': 2,
                        'keep_parts': keep_parts,
                    },
                )
            ],
            [],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'parts-test'})
        run_id = started.get_json()['run_id']
        assert _wait_for_worker(app_module)
        assert app_module._RUN_STORE.row_count(run_id, 'node-1') == 5

        exports = data_root / 'data' / 'exports'
        final = exports / 'parts-test-src-node-1.csv'
        assert final.exists(), 'the merged file must exist whatever the keep-parts choice'
        frame = pd.read_csv(final, encoding='utf-8-sig')
        assert frame['正文'].tolist() == [f'body {i}' for i in range(5)]
        parts = sorted(p.name for p in exports.glob('parts-test-src-node-1.part*.csv'))
        assert len(parts) == expect_parts, '5 rows at part_size=2 flush exactly two settled parts'

    def test_llm_live_snapshot_is_rewritten_on_every_publish(self, client, app_module, data_root):
        node = _node('p1', 'process', operation='clean', params={'text_column': '正文', 'live_export': True})
        run_ctx = app_module._llm_run_ctx(node, 'clean', None)
        assert callable(run_ctx['publish'])

        df = pd.DataFrame([{'正文': '甲'}, {'正文': '乙'}])
        run_ctx['publish'](df)
        from services.part_writer import safe_stem

        stem = safe_stem(f'{app_module.execution_state.get("workflow_name") or "llm"}-p1')
        live = data_root / 'data' / 'exports' / f'{stem}.live.csv'
        assert live.exists()
        assert pd.read_csv(live, encoding='utf-8-sig')['正文'].tolist() == ['甲', '乙']

        # A later batch adds a column: the snapshot grows in place, the tmp
        # file never survives the swap, and no stale rows linger.
        df['清洗后'] = ['a', 'b']
        run_ctx['publish'](df)
        frame = pd.read_csv(live, encoding='utf-8-sig')
        assert list(frame.columns) == ['正文', '清洗后']
        assert list(frame['清洗后']) == ['a', 'b']
        assert not list(live.parent.glob('*.tmp'))
        # The state snapshot still travels too (the preview panel reads it).
        assert app_module.execution_state['results']['p1'] == df.to_dict('records')

    def test_llm_live_export_off_by_default(self, client, app_module, data_root):
        node = _node('p2', 'process', operation='clean', params={'text_column': '正文'})
        run_ctx = app_module._llm_run_ctx(node, 'clean', None)
        df = pd.DataFrame([{'正文': '甲'}])
        run_ctx['publish'](df)
        # No {this node}.live file: the export directory is session-scoped, so
        # only a p2-named snapshot would prove the feature fired.
        from services.part_writer import safe_stem

        stem = safe_stem(f'{app_module.execution_state.get("workflow_name") or "llm"}-p2')
        assert not list((data_root / 'data' / 'exports').glob(f'{stem}.live.*'))
