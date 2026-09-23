"""Tests for the workflow endpoints, ending in a real execute round-trip.

``/api/workflow/*`` is the whole product in miniature: a canvas definition is
saved as JSON, reloaded with its Upload nodes re-attached to the stored files,
and then executed by a background thread that checkpoints every node into the
run store. The execute test in the middle is the plan's end-to-end invariant —
file in, cleaned rows out, and a durable record that says exactly what each
node produced — so it deliberately uses only non-crawling, non-LLM nodes:
``upload`` → ``analysis`` → ``output``. A ``source`` node would start Selenium
and does not belong in a test that has to run offline. Where a test here does
run an LLM node (``TestEntityNode``), the transport itself is patched, so no
daemon and no API are ever asked.

The polling tests carry ``@pytest.mark.serial`` because the worker installs a
``_LogTee`` over ``sys.stdout`` for the duration of the run.
"""

import os

import pandas as pd
import pytest
from run_wait import run_finished

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
    return run_finished(app_module, timeout)


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
        # cleared so the UI asks for the file instead of pretending. Forced:
        # this workflow still references it, and an ordinary delete now refuses
        # to strand the node (see TestDatasetDeletionGuards).
        assert client.delete(f'/api/data/datasets/{dataset_id}?force=1').get_json()['ok'] is True
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
        # The saved file is announced ONCE. Both the exporter and the save node
        # used to name the same path, in two different sentences, every run.
        saved = [line for line in status['logs'] if 'workflow-e2e.csv' in line and 'Exported' in line]
        assert len(saved) == 1, status['logs']
        assert not any('Data saved to' in line for line in status['logs']), 'the duplicate line is back'

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
    def test_a_second_run_waits_its_turn_instead_of_being_refused(self, client, app_module):
        """Busy used to mean 'already running' and a dead end; now it means queued.

        ``queue: false`` keeps the old refusal available, because the resume
        banner's 继续 wants to fail fast rather than silently reorder runs.
        """
        app_module.execution_state['running'] = True
        workflow = _e2e_workflow('anything')
        queued = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'anything'})
        assert queued.status_code == 200
        body = queued.get_json()
        assert body['queued'] is True and body['position'] == 1
        assert [entry['workflow_name'] for entry in app_module.queue_snapshot()] == ['anything']

        refused = client.post('/api/workflow/execute', json={'workflow': workflow, 'queue': False})
        assert refused.status_code == 400
        assert 'already running' in refused.get_json()['error']
        assert len(app_module.queue_snapshot()) == 1, 'a refusal must not park a second copy'

        cancelled = client.post('/api/workflow/queue/cancel', json={'id': body['queue_id']}).get_json()
        assert cancelled['ok'] is True and cancelled['removed'] is True
        assert app_module.queue_snapshot() == []
        assert app_module.execution_state['running'] is True, 'cancelling a wait must not stop the run'

    @pytest.mark.serial
    def test_the_queue_hands_over_when_the_running_run_finishes(self, client, app_module, paste):
        """The whole point: press Run twice, both run, in order, one at a time."""
        dataset_id = paste(E2E_RECORDS, name='queued.csv')

        def _flow(name):
            return _workflow(
                [
                    _node(
                        'node-1',
                        'upload',
                        params={'dataset_id': dataset_id, 'dataset_name': 'queued.csv', 'row_count': 6},
                    ),
                    _node('node-2', 'analysis', params={'steps': E2E_STEPS, 'workflow_name': name}),
                ],
                [{'from': 'node-1', 'to': 'node-2'}],
            )

        first = client.post('/api/workflow/execute', json={'workflow': _flow('first'), 'workflow_name': 'first'})
        assert first.status_code == 200
        second = client.post('/api/workflow/execute', json={'workflow': _flow('second'), 'workflow_name': 'second'})
        assert second.get_json().get('queued') is True

        assert _wait_for_worker(app_module), 'the queued run never finished either'
        store = app_module.get_run_store()
        first_run = store.get_run(first.get_json()['run_id'])
        seconds = [
            run for run in store.list_resumable(limit=20, include_finished=True) if run['workflow_name'] == 'second'
        ]
        assert len(seconds) == 1, 'the queued run started twice, or not at all'
        second_run = seconds[0]
        assert first_run['status'] == 'completed' and second_run['status'] == 'completed'
        # One writer at a time is the property the whole checkpoint design rests
        # on: the queued run may not begin before the running one is over.
        assert second_run['started_at'] >= first_run['finished_at'], 'the two runs overlapped'

    def test_the_queue_is_reported_where_the_ui_already_looks(self, client, app_module):
        app_module.execution_state['running'] = True
        client.post('/api/workflow/execute', json={'workflow': _e2e_workflow('listed'), 'workflow_name': 'listed'})
        app_module.execution_state['running'] = False

        def names(url):
            return [entry['workflow_name'] for entry in client.get(url).get_json()['queue']]

        # Three doors, one list: the panel that polls status, the panel that
        # fetches runs, and the queue endpoint itself must never disagree.
        for url in ('/api/workflow/queue', '/api/workflow/status', '/api/runs/list'):
            assert names(url) == ['listed'], url
        assert client.post('/api/workflow/queue/clear', json={}).get_json()['cleared'] == 1
        assert client.get('/api/workflow/queue').get_json()['queue'] == []

    def test_a_full_queue_refuses_rather_than_parking_forever(self, client, app_module):
        app_module.execution_state['running'] = True
        for index in range(app_module.QUEUE_MAX):
            payload = {'workflow': _e2e_workflow(f'wf-{index}'), 'workflow_name': f'wf-{index}'}
            assert client.post('/api/workflow/execute', json=payload).status_code == 200
        over = client.post('/api/workflow/execute', json={'workflow': _e2e_workflow('one-too-many')})
        assert over.status_code == 409
        assert str(app_module.QUEUE_MAX) in over.get_json()['error']
        assert len(client.get('/api/workflow/queue').get_json()['queue']) == app_module.QUEUE_MAX
        client.post('/api/workflow/queue/clear', json={})

    def test_cancelling_an_unknown_queue_id_removes_nothing(self, client):
        body = client.post('/api/workflow/queue/cancel', json={'id': 'nope'}).get_json()
        assert body['ok'] is True and body['removed'] is False
        assert client.post('/api/workflow/queue/cancel', json={'id': 5}).status_code == 400

    @pytest.mark.serial
    def test_a_workflow_whose_nodes_are_named_freely_still_runs(self, client, app_module, paste):
        """Node ids are data, not a format the executor may assume.

        The canvas mints ``node-N``, but a workflow saved as JSON and edited by
        hand can call its nodes anything. ``sort_workflows`` used to read the
        suffix with ``int()`` and raise, so such a file could never run at all —
        and the failure looked like a server bug, not like a name.
        """
        dataset_id = paste(E2E_RECORDS, name='freely-named.csv')
        workflow = _workflow(
            [
                _node(
                    'alpha',
                    'upload',
                    params={'dataset_id': dataset_id, 'dataset_name': 'freely-named.csv', 'row_count': 6},
                ),
                _node('beta', 'analysis', params={'steps': E2E_STEPS}),
            ],
            [{'from': 'alpha', 'to': 'beta'}],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'free-names'})
        assert started.status_code == 200
        assert _wait_for_worker(app_module), 'the execute thread did not finish in time'
        rows = app_module.execution_state['results']['beta']
        assert [row['title'] for row in rows] == E2E_SURVIVORS
        # The run is recorded under the ids the file used, so 继续 finds them.
        statuses = app_module.get_run_store().node_statuses(started.get_json()['run_id'])
        assert sorted(statuses) == ['alpha', 'beta']

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


STATUS_FIELDS = {
    'running',
    'logs',
    'log_total',
    'workflows',
    'mode',
    'results',
    'total_nodes',
    'completed_nodes',
    # Added by the progress fix: the run's own verdict, so the browser stops
    # inferring "unfinished, offer a continue" from completed < total.
    'skipped_nodes',
    'failed_nodes',
    'outcome',
    'chart_results',
    'cookie_expired',
    'queue',
}


def _run_e2e(client, app_module, paste, name: str) -> dict:
    """One offline run, waited for, answered as the status payload."""
    dataset_id = paste(E2E_RECORDS, name=f'{name}.csv')
    started = client.post(
        '/api/workflow/execute', json={'workflow': _e2e_workflow(dataset_id, name), 'workflow_name': name}
    )
    assert started.status_code == 200
    assert _wait_for_worker(app_module), 'the execute thread did not finish in time'
    return client.get('/api/workflow/status').get_json()


class TestConsoleSaysEachThingOnce:
    """The console is read line by line, so a fact printed twice is a fact the
    reader has to reconcile — and the pairs below did not even agree with each
    other. These assertions hold the transcript down: one line per event, no
    decoration, and a name per component when one canvas holds two workflows."""

    @pytest.mark.serial
    def test_a_finished_run_prints_one_verdict(self, client, app_module, paste):
        body = _run_e2e(client, app_module, paste, 'once-verdict')
        finished = [line for line in body['logs'] if 'Run finished' in line]
        assert len(finished) == 1
        assert not any('completed' in line.lower() and 'node' not in line.lower() for line in body['logs']), (
            'a second completion sentence is a second chance to disagree'
        )

    @pytest.mark.serial
    def test_a_step_that_removed_rows_shows_the_count(self, client, app_module, paste):
        body = _run_e2e(client, app_module, paste, 'once-step')
        steps = [line for line in body['logs'] if 'drop_duplicates' in line]
        assert len(steps) == 1, steps
        assert '(-1)' in steps[0], 'a real removal must be visible, not implied by two numbers'

    @pytest.mark.serial
    def test_a_step_that_removed_nothing_prints_no_fake_zero(self, client, app_module, paste):
        """'(-0)' read as a truncated number rather than as "nothing happened"."""
        dataset_id = paste(E2E_RECORDS, name='noop-step.csv')
        workflow = _workflow(
            [
                _node('node-1', 'upload', params={'dataset_id': dataset_id, 'row_count': len(E2E_RECORDS)}),
                _node(
                    'node-2', 'analysis', params={'steps': [{'op': 'select_columns', 'params': {'columns': ['title']}}]}
                ),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'noop-step'})
        assert _wait_for_worker(app_module)
        steps = [line for line in client.get('/api/workflow/status').get_json()['logs'] if 'select_columns' in line]
        assert len(steps) == 1, steps
        assert '-0' not in steps[0] and 'no change' in steps[0].lower(), steps[0]

    @pytest.mark.serial
    def test_no_console_line_is_decorated_with_rule_characters(self, client, app_module, paste):
        body = _run_e2e(client, app_module, paste, 'once-plain')
        assert not [line for line in body['logs'] if '---' in line or line.endswith('===')], body['logs']

    @pytest.mark.serial
    def test_two_components_on_one_canvas_are_told_apart(self, client, app_module, monkeypatch):
        """Both used to announce themselves with the run's name, so the console
        said the same workflow started twice and the two console tabs got
        identical labels."""

        class Rows(_ScriptedCrawler):
            rows = [{'发布者': 'a', '正文': 'hello', '链接': 'https://weibo.com/1'}]

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: Rows())
        workflow = _workflow(
            [
                _node('a-1', 'source', params={'platform': 'weibo', 'keyword': 'k1', 'target_count': 2}),
                _node('a-2', 'output', operation='save', params={'format': 'csv', 'filename': 'ca'}),
                _node('b-1', 'source', params={'platform': 'weibo', 'keyword': 'k2', 'target_count': 2}),
                _node('b-2', 'output', operation='save', params={'format': 'csv', 'filename': 'cb'}),
            ],
            [{'from': 'a-1', 'to': 'a-2'}, {'from': 'b-1', 'to': 'b-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': '两条', 'lang': 'zh'})
        assert _wait_for_worker(app_module)
        body = client.get('/api/workflow/status').get_json()
        starts = [line for line in body['logs'] if '开始执行工作流' in line]
        assert len(starts) == 2 and starts[0] != starts[1], starts
        # The per-workflow console tabs are labelled from the same names.
        names = [wf['name'] for wf in body['workflows']]
        assert len(names) == len(set(names)) == 2, names


class _ScriptedCrawler:
    """A crawler that returns what the test says, or dies saying nothing."""

    rows: list = []
    boom = False

    def __init__(self, *args, **kwargs):
        pass

    def set_sink(self, sink):
        self._sink = sink

    def set_cursor_sink(self, sink):
        pass

    def seed(self, saved):
        pass

    def close(self):
        pass

    def search(self, *args, **kwargs):
        if type(self).boom:
            raise RuntimeError('driver exploded')
        kept = []
        for item in type(self).rows:
            if self._sink is None or self._sink(item):
                kept.append(item)
        return kept


class TestProgressAccounting:
    """What a finished run says about itself, in numbers and in one sentence.

    Progress used to be one ratio, and the browser read whatever it liked into
    it: a node starved by a dead upstream subtracted from the count exactly like
    a node that failed, so a clean run announced 'ended, continue is available'
    with nothing left to continue, and a refused definition announced '0/0'.
    """

    @pytest.mark.serial
    def test_a_clean_run_reports_no_extra_counts(self, client, app_module, paste):
        body = _run_e2e(client, app_module, paste, 'progress-clean')
        assert body['outcome'] == 'completed'
        assert (body['skipped_nodes'], body['failed_nodes']) == (0, 0)
        finished = [line for line in body['logs'] if 'Run finished' in line]
        assert len(finished) == 1, 'one run, one closing sentence'
        # Drop the [HH:MM:SS] prefix the console handler adds.
        assert finished[0].split('] ', 1)[1] == 'Run finished (3/3 nodes)', (
            'a clean run must not carry skip/failure fragments'
        )

    @pytest.mark.serial
    def test_a_starved_node_is_reported_as_skipped_not_as_missing_progress(
        self, client, app_module, paste, monkeypatch
    ):
        """The case the old wording got wrong twice over: nothing failed, the run
        completed, and yet 'completed 1/2 (continue available)' was a promise the
        screen could not keep."""

        class Empty(_ScriptedCrawler):
            rows = []

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: Empty())
        workflow = _workflow(
            [
                _node('node-1', 'source', params={'platform': 'weibo', 'keyword': 'k', 'target_count': 2}),
                _node('node-2', 'process', operation='keyword', params={'operation': 'keyword'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'starved'})
        assert _wait_for_worker(app_module)
        body = client.get('/api/workflow/status').get_json()
        assert body['outcome'] == 'completed', 'a run nothing failed is not a run to continue'
        assert (body['completed_nodes'], body['skipped_nodes'], body['failed_nodes']) == (1, 1, 0)
        sentence = [line for line in body['logs'] if 'Run finished' in line][0]
        assert '1 skipped' in sentence and 'failed' not in sentence, sentence

    @pytest.mark.serial
    def test_a_failed_node_is_counted_and_named(self, client, app_module, monkeypatch):
        class Boom(_ScriptedCrawler):
            boom = True

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: Boom())
        workflow = _workflow(
            [
                _node('node-1', 'source', params={'platform': 'weibo', 'keyword': 'k', 'target_count': 2}),
                _node('node-2', 'process', operation='keyword', params={'operation': 'keyword'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'boom'})
        assert _wait_for_worker(app_module)
        body = client.get('/api/workflow/status').get_json()
        assert body['outcome'] == 'failed'
        assert body['failed_nodes'] == 1
        assert '1 failed' in [line for line in body['logs'] if 'Run finished' in line][0]

    @pytest.mark.serial
    def test_a_refused_definition_never_reports_zero_percent_of_a_run(self, client, app_module):
        """Validation errors stop the run before a node exists. The old answer was
        silence plus '0/0', which the browser read as a finished run."""
        workflow = _workflow([_node('node-1', 'output', params={})], [])
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'refused'})
        assert _wait_for_worker(app_module)
        body = client.get('/api/workflow/status').get_json()
        assert body['outcome'] == 'rejected'
        assert body['total_nodes'] == 0 and body['completed_nodes'] == 0
        rejected = [line for line in body['logs'] if 'Nothing ran' in line]
        assert rejected and '1' in rejected[0], 'the line must say how many problems there are'
        assert not any('Run finished' in line for line in body['logs']), 'nothing ran, so nothing finished'

    @pytest.mark.serial
    def test_a_node_that_never_ran_is_not_announced_as_starting(self, client, app_module, monkeypatch):
        """'Executing node X' used to be printed before the executor decided
        anything, so the line right after it could say X was restored or skipped."""

        class Empty(_ScriptedCrawler):
            rows = []

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: Empty())
        workflow = _workflow(
            [
                _node('node-1', 'source', params={'platform': 'weibo', 'keyword': 'k', 'target_count': 2}),
                _node('node-2', 'process', operation='keyword', params={'operation': 'keyword'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'no-contradiction'})
        assert _wait_for_worker(app_module)
        logs = client.get('/api/workflow/status').get_json()['logs']
        executing = [line for line in logs if 'Executing node' in line]
        assert all('node-1' in line for line in executing), f'a skipped node was announced as starting: {executing}'


class TestStatusPayloadContract:
    """The console, the progress bar and the queue panel are driven by ONE answer.

    Its shape is written down here while today's behaviour is still the reference,
    so the two changes that will touch it (the console-freeze fix and the progress
    counting fix) can be reviewed as a deliberate delta rather than as drift.
    """

    @pytest.mark.serial
    def test_a_finished_run_answers_the_whole_console_contract(self, client, app_module, paste):
        body = _run_e2e(client, app_module, paste, 'status-contract')
        assert set(body) == STATUS_FIELDS, (
            'the browser reads these keys by name; adding or renaming one is a contract change'
        )
        assert body['running'] is False
        # The browser works out "which lines are new" from total minus the tail it
        # was handed, so the two must stay consistent — an inconsistent pair silently
        # stops the console updating while the run keeps producing.
        assert body['log_total'] >= len(body['logs'])
        assert set(body['results']) == {'node-1', 'node-2', 'node-3'}
        assert (body['total_nodes'], body['completed_nodes']) == (3, 3)
        assert body['cookie_expired'] is False
        assert body['queue'] == []
        assert body['mode'] in ('serial', 'parallel')
        assert body['workflows'], 'a run must be addressable per workflow, not only as one global tail'
        for wf in body['workflows']:
            assert set(wf) == {'id', 'name', 'logs', 'total'}
            assert wf['total'] >= len(wf['logs'])
            assert isinstance(wf['id'], int)

    @pytest.mark.serial
    def test_the_tail_is_capped_but_the_total_keeps_counting(self, client, app_module, paste):
        """The answer ships the last 200 lines and the true total; both halves of
        that pair are load-bearing, so pin them together."""
        body = _run_e2e(client, app_module, paste, 'status-cap')
        assert len(body['logs']) <= 200
        assert body['log_total'] == len(body['logs']) or body['log_total'] > len(body['logs'])

    @pytest.mark.serial
    def test_a_second_run_restarts_the_console_instead_of_accumulating(self, client, app_module, paste):
        """Pins the server half of the console freeze.

        `_begin_run` clears the buffers, so the second run's `log_total` starts
        from a number SMALLER than what the browser last saw. A poller that keeps
        its own high-water index then slices past the end of the array and renders
        nothing for the rest of the run. The fix belongs in the browser (make that
        index observable and resettable), and this test records why it has to be.
        """
        first = _run_e2e(client, app_module, paste, 'status-first')
        second = _run_e2e(client, app_module, paste, 'status-second')
        assert first['log_total'] > 0
        assert second['log_total'] <= first['log_total'], 'the total must not accumulate across runs'
        # Per-line prefixes are what proves a reset: both runs share one stored
        # dataset here (identical rows are content-addressed, so the file keeps the
        # name it was first filed under), which makes the file name a useless marker.
        second_console = '\n'.join(second['logs'])
        assert '[status-first]' not in second_console, 'the previous run console is gone, not hidden'
        assert '[status-second]' in second_console
        assert (second['total_nodes'], second['completed_nodes']) == (3, 3), 'while progress still counts correctly'


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
            lambda platform, headless=True, cookie_dir=None, use_profile=None: FakeSinkCrawler(rows),
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


class TestEntityNode:
    """The entity node end to end, through /api/workflow/execute.

    Two fields decide this node — ``mode`` (rules or model) and ``entity_types``
    (which of the four categories) — and both are set only by the panel, so a
    parameter that stops travelling shows up here as a table that disagrees with
    what the user asked for.
    """

    RECORDS = [{'正文': '张伟前往上海参加峰会', 'title': 'summit'}]

    def _flow(self, dataset_id, name, params):
        return _workflow(
            [
                _node('node-1', 'upload', params={'dataset_id': dataset_id, 'dataset_name': name, 'row_count': 1}),
                _node('node-2', 'process', operation='ner', params=params),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
        )

    @pytest.mark.serial
    def test_the_rules_run_without_any_model_settings(self, client, app_module, paste):
        dataset_id = paste(self.RECORDS, name='ner-rules.csv')
        workflow = self._flow(dataset_id, 'ner-rules.csv', {'text_column': '正文'})
        # No llm payload in the request at all: a rules run must not be gated on
        # a model, an API key or a daemon. And these rules find nothing in this
        # text, which is the honest empty table rather than a failure.
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'ner-rules'})
        assert started.status_code == 200, started.get_json()
        assert _wait_for_worker(app_module)
        assert app_module.execution_state['results']['node-2'] == []

    @pytest.mark.serial
    def test_the_category_filter_reaches_the_table(self, client, app_module, paste):
        records = [{'正文': '张先生在北京大学毕业', 'title': 'a'}]
        dataset_id = paste(records, name='ner-filter.csv')
        workflow = self._flow(dataset_id, 'ner-filter.csv', {'text_column': '正文', 'entity_types': 'person'})
        client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'ner-filter'})
        assert _wait_for_worker(app_module)
        rows = app_module.execution_state['results']['node-2']
        assert [(row['text'], row['label']) for row in rows] == [('张先生', 'PERSON')]

    @pytest.mark.serial
    def test_the_model_mode_uses_the_transport_the_request_named(self, client, app_module, paste, monkeypatch):
        asked = {}

        def fake_chat(self, prompt, max_retries=2):
            asked['prompt'] = prompt
            asked['provider'] = self.provider
            return '张伟|PERSON'

        monkeypatch.setattr(app_module.LLMClient, 'chat', fake_chat)
        dataset_id = paste(self.RECORDS, name='ner-llm.csv')
        workflow = self._flow(
            dataset_id, 'ner-llm.csv', {'text_column': '正文', 'mode': 'llm', 'entity_types': 'person'}
        )
        client.post(
            '/api/workflow/execute',
            json={
                'workflow': workflow,
                'workflow_name': 'ner-llm',
                'llm': {'provider': 'openrouter', 'api_key': 'test-key', 'model': 'test/model'},
            },
        )
        assert _wait_for_worker(app_module)
        assert asked['provider'] == 'openrouter', 'the node ignored the transport the request carried'
        # Only the asked-for category is offered, and the answer becomes a row
        # whose offsets point back into the crawled text.
        assert 'only: PERSON.' in asked['prompt'] and 'ORG:' not in asked['prompt']
        rows = app_module.execution_state['results']['node-2']
        assert [(row['text'], row['label']) for row in rows] == [('张伟', 'PERSON')]
        assert self.RECORDS[0]['正文'][rows[0]['start'] : rows[0]['end']] == '张伟'

    def test_the_model_mode_is_gated_like_every_other_llm_op(self, client, app_module):
        workflow = _workflow(
            [_node('node-1', 'process', operation='ner', params={'text_column': '正文', 'mode': 'llm'})],
            [],
        )
        body = client.post('/api/workflow/execute', json={'workflow': workflow}).get_json()
        assert 'No Ollama model selected' in body['error']
        assert app_module.execution_state['running'] is False


class _FakeCommentSession:
    """Stands in for crawlers.comments.CommentSession: returns canned rows.

    The dispatch under test routes a comments-mode Data Source into the shared
    comment engine; this proves the wiring without a browser (the real adapters
    are live-tested in the live_site tier).
    """

    rows = [{'平台': 'zhihu', '文章URL': 'https://x/1', '评论者': 'a', '评论内容': 'good'}]

    def __init__(self, driver, log=None):
        self.log = log

    def crawl_zhihu(self, url, limit):
        return list(self.rows), 'ok'


class TestSourceCommentsMode:
    def test_comments_mode_routes_to_the_comment_engine(self, client, app_module, monkeypatch):
        made = {'crawlers': 0}

        class _FakeCrawler:
            driver = None

            def close(self):
                pass

        def fake_get_crawler(kind, headless=True, cookie_dir=None, use_profile=None):
            # Comments mode must force a VISIBLE browser even though the source
            # param says headless — zhihu content pages reject headless.
            assert headless is False, 'comment crawl opens a visible window'
            made['crawlers'] += 1
            return _FakeCrawler()

        import crawlers.comments as comments_module

        monkeypatch.setattr(app_module, 'get_crawler', fake_get_crawler)
        monkeypatch.setattr(comments_module, 'CommentSession', _FakeCommentSession)

        workflow = _workflow(
            [
                _node(
                    'node-1',
                    'source',
                    params={
                        'platform': 'zhihu',
                        'collect': 'comments',
                        'urls': 'https://www.zhihu.com/question/1/answer/2',
                        'headless': True,
                    },
                )
            ],
            [],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'cmt-mode'})
        assert started.get_json()['ok'] is True
        run_id = started.get_json()['run_id']
        assert _wait_for_worker(app_module)

        rows = app_module._RUN_STORE.load_rows(run_id, 'node-1')
        assert made['crawlers'] == 1, 'the comments route built its own crawler'
        assert len(rows) == 1 and rows[0]['评论内容'] == 'good'

    def test_comments_mode_without_urls_is_a_validation_error(self, client, app_module):
        workflow = _workflow(
            [_node('node-1', 'source', params={'platform': 'zhihu', 'collect': 'comments', 'urls': ''})],
            [],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'cmt-bad'})
        assert started.status_code == 200  # a validation failure is a logged outcome, not an HTTP error
        assert _wait_for_worker(app_module)
        status = client.get('/api/workflow/status').get_json()
        assert any('the required field article URLs is empty' in line for line in status['logs'])

    def test_foreign_platform_links_stop_the_run_before_any_browser(self, client, app_module, monkeypatch):
        # Selected platform zhihu + a weibo link: validate() must refuse the
        # design, and refuse it EARLY — no visible window may open just to
        # say no (the user pays for cookies and time otherwise).
        built = {'n': 0}

        def counting_get_crawler(*args, **kwargs):
            built['n'] += 1
            raise AssertionError('a workflow that fails validation must not open a browser')

        monkeypatch.setattr(app_module, 'get_crawler', counting_get_crawler)
        workflow = _workflow(
            [
                _node(
                    'node-1',
                    'source',
                    params={'platform': 'zhihu', 'collect': 'comments', 'urls': 'https://weibo.com/123/AbC'},
                )
            ],
            [],
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'cmt-mismatch'})
        assert started.status_code == 200
        assert _wait_for_worker(app_module)
        status = client.get('/api/workflow/status').get_json()
        assert any('do not match the selected platform (zhihu)' in line for line in status['logs'])
        assert built['n'] == 0

    def test_runtime_skips_foreign_links_and_refuses_when_none_match(self, app_module, monkeypatch):
        """The crawl-time second line of defence (a hand-made JSON that never
        passed validate() still must not crawl a platform nobody selected)."""
        import crawlers.comments as comments_module

        crawled = []

        class _FakeCrawler:
            driver = None

            def close(self):
                pass

        class _RecordingSession:
            def __init__(self, driver, log=None):
                pass

            def crawl_zhihu(self, url, limit):
                crawled.append(url)
                return [{'评论内容': 'kept'}], 'ok'

            def crawl_weibo(self, url, limit):
                crawled.append(url)
                return [], 'ok'

            def crawl_xiaohongshu(self, url, limit):
                crawled.append(url)
                return [], 'ok'

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _FakeCrawler())
        monkeypatch.setattr(comments_module, 'CommentSession', _RecordingSession)
        # setitem (not a bare assignment) so the flag is handed back at teardown —
        # a leaked running=True blocks the next test's execute (already-running).
        monkeypatch.setitem(app_module.execution_state, 'running', True)

        from i18n import get_lang, set_lang

        previous = get_lang()
        set_lang('en')  # a direct call skips the per-request X-Lang routing
        try:
            mixed = {
                'id': 'node-1',
                'type': 'comment',
                'params': {'platform': 'zhihu', 'urls': 'https://weibo.com/1/a\nhttps://www.zhihu.com/question/2'},
            }
            rows = app_module._execute_comment_node(mixed)
            assert [r['评论内容'] for r in rows] == ['kept']
            assert crawled == ['https://www.zhihu.com/question/2'], 'only the selected platform may be crawled'

            all_foreign = {
                'id': 'node-2',
                'type': 'comment',
                'params': {'platform': 'zhihu', 'urls': 'https://weibo.com/1/a'},
            }
            with pytest.raises(ValueError, match='conflicts with the selected platform'):
                app_module._execute_comment_node(all_foreign)
        finally:
            set_lang(previous)


class TestConsoleReadabilityRegression:
    """The bug this repo shipped with: the console printed 'node-1' / '[WF0]'
    because toWorkflowJSON dropped each node's title (so the backend got
    title:None) and the workflow prefix was an index. This test drives the
    user's REAL saved workflow (微博-ChatGPT.json — every node title:None)
    through the fixed pipeline and proves the console now speaks in the
    workflow's name and readable node labels, never a bare id or a WF index.
    """

    def test_saved_titleless_workflow_still_reads_with_names(self, client, app_module, monkeypatch):
        """The shape the user's real workflow had: a name node, a source and an
        output, with every ``title`` dropped by the pre-fix frontend.

        This used to read ``data/workflows/微博-ChatGPT.json`` when that file
        existed and a reconstruction otherwise, so the suite silently tested two
        different things on two machines (and reached into real user data while
        doing it). The reconstruction IS the shape, so it is now the only input.
        """
        workflow = _workflow(
            [
                {'id': 'node-2', 'type': 'name', 'params': {'workflow_name': '获取微博'}},
                {
                    'id': 'node-1',
                    'type': 'source',
                    'params': {'platform': 'weibo', 'keyword': 'ChatGPT', 'target_count': 2},
                },
                {
                    'id': 'node-3',
                    'type': 'output',
                    'operation': 'save',
                    'params': {'format': 'csv', 'filename': 'probe'},
                },
            ],
            [{'from': 'node-2', 'to': 'node-1'}, {'from': 'node-1', 'to': 'node-3'}],
        )
        for n in workflow['nodes']:
            n['title'] = None

        rows = [{'发布者': 'a', '正文': 'hello', '链接': 'https://weibo.com/1'}]

        class _C:
            login_wall = False

            def __init__(self, *a, **k):
                self.driver = None

            def set_sink(self, s):
                self._s = s

            def set_cursor_sink(self, s):
                pass

            def seed(self, saved):
                pass

            def close(self):
                pass

            def search(self, keyword=None, target_count=None, resume=None, **k):
                kept = []
                for item in rows:
                    if self._s is None or self._s(item):
                        kept.append(item)
                return kept

        monkeypatch.setattr(
            app_module, 'get_crawler', lambda platform, headless=True, cookie_dir=None, use_profile=None: _C()
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': '获取微博'})
        assert started.get_json()['ok'] is True
        assert _wait_for_worker(app_module)

        logs = client.get('/api/workflow/status').get_json()['logs']
        blob = '\n'.join(logs)
        # The console addresses the workflow by name (from the name node), never
        # by a '[WF0]' index — 'WF0' must not appear anywhere.
        assert 'WF0' not in blob, 'the console must not fall back to WF indices'
        # A titleless source still reads as a label + id, not a lone 'node-1'.
        assert '#node-1' in blob, 'the source should read "Data Source #node-1", not a bare node-1'
        # And the node it names must be the one that actually ran.
        assert app_module._RUN_STORE.row_count(started.get_json()['run_id'], 'node-1') == 1


class TestConsoleSemantics:
    """The progress console keeps told two lies: a failed node was counted in
    'completed_nodes' (so 'Run finished (3/3)' announced a broken run as a
    clean one), and every decorative logger line — blanks, '=' banners —
    marched into the UI console because the file log and the console shared
    one handler. Both are pinned here."""

    @pytest.mark.serial
    def test_a_failed_node_is_visited_but_not_done(self, client, app_module, monkeypatch):
        class _BoomCrawler:
            def __init__(self, *args, **kwargs):
                pass

            def set_sink(self, sink):
                pass

            def set_cursor_sink(self, sink):
                pass

            def seed(self, rows):
                pass

            def close(self):
                pass

            def search(self, *args, **kwargs):
                raise RuntimeError('driver exploded')

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _BoomCrawler())
        workflow = _workflow(
            [
                _node('node-1', 'source', params={'platform': 'zhihu', 'keyword': 'k', 'target_count': 5}),
                _node('node-2', 'output', operation='save', params={'format': 'csv', 'filename': 'boom-out'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
            settings={'mode': 'serial'},
        )
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'boom'})
        assert started.get_json()['ok'] is True
        assert _wait_for_worker(app_module)

        status = client.get('/api/workflow/status').get_json()
        assert status['total_nodes'] == 2
        # The source failed and the output skipped for lack of upstream data:
        # NOTHING was completed. The old count called that '1/2' or '2/2'.
        assert status['completed_nodes'] == 0
        blob = '\n'.join(status['logs'])
        assert 'driver exploded' in blob
        assert 'completed (' not in blob, 'a failed or skipped node must never print a completed line'
        assert 'Run finished (0/2 nodes)' in blob

    def test_decorative_logger_lines_never_reach_the_console(self, app_module):
        import logging

        logs = app_module.execution_state['logs']
        before = len(logs)
        crawler_log = logging.getLogger('crawlers.wechat')
        crawler_log.info('=' * 70)  # standalone-script banner
        crawler_log.info('')  # blank separator
        crawler_log.info('   ')  # whitespace-only
        crawler_log.info('real progress line')
        assert len(logs) == before + 1, 'only the meaningful line may be kept'
        assert 'real progress line' in logs[-1]
        # The banner lines the console refused...
        blob = '\n'.join(logs[before:])
        assert '====' not in blob

    @pytest.mark.serial
    def test_run_lines_name_the_workflow_not_an_index(self, client, app_module, monkeypatch):
        # No name node on this canvas: the console must fall back to the
        # workflow name the browser sent with the run — never 'WF1'.
        workflow = _workflow(
            [
                _node('node-1', 'source', params={'platform': 'zhihu', 'keyword': 'k', 'target_count': 1}),
                _node('node-2', 'output', operation='save', params={'format': 'csv', 'filename': 'na-out'}),
            ],
            [{'from': 'node-1', 'to': 'node-2'}],
            settings={'mode': 'serial'},
        )

        class _One:
            def __init__(self, *args, **kwargs):
                pass

            def set_sink(self, sink):
                pass

            def set_cursor_sink(self, sink):
                pass

            def seed(self, rows):
                pass

            def close(self):
                pass

            def search(self, *args, **kwargs):
                return [{'标题': 'a'}]

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _One())
        started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': '命名测试'})
        assert _wait_for_worker(app_module)
        assert started.get_json()['ok'] is True
        # Per-workflow tab metadata is only built for multi-component runs, so
        # check the single-run story instead: the console named the workflow,
        # not an index.
        status = client.get('/api/workflow/status').get_json()
        blob = '\n'.join(status['logs'])
        assert '[命名测试]' in blob or '命名测试' in blob
        assert 'WF1' not in blob and 'WF0' not in blob


def _capture(cls, seen):
    """A get_crawler stand-in that records the headless flag it was given.

    The argument is what two tests below assert on, and spelling it out per
    test turned into a lambda too long to read.
    """

    def _make(platform, headless=True, **kwargs):
        seen['headless'] = headless
        return cls()

    return _make


class TestCrawlableGuard:
    """A platform can hold a cookie and still have no crawler — and the two
    capabilities must not be confused at run time.

    Douyin was that live case while its crawl was unimplemented; now that every
    listed platform can be crawled, the guard is pinned on a synthetic
    cookie-only registration instead. Naming a real platform here would turn
    this test red every time a crawler lands, which is the wrong reason. The
    refusal has to happen before a browser is bought and must name the node,
    because '0 rows' from a platform that was never going to answer reads to the
    user as a failed search rather than an unimplemented one.
    """

    @staticmethod
    def _node(platform, nid='src-1', title='某平台源'):
        return {'id': nid, 'type': 'source', 'title': title, 'platform': platform, 'params': {'keyword': 'ai'}}

    def test_a_cookie_only_platform_is_refused_before_any_browser_boots(self, monkeypatch):
        import app as app_module

        from crawlers import CRAWLERS

        class _CookieOnly:
            supports_crawl = False

        monkeypatch.setitem(CRAWLERS, 'kuaishou', _CookieOnly)

        from i18n import t

        def _no_browser(*args, **kwargs):
            raise AssertionError('the guard must run before get_crawler')

        monkeypatch.setattr(app_module, 'get_crawler', _no_browser)
        with pytest.raises(ValueError) as err:
            app_module._execute_source_node(self._node('kuaishou'), headless=True)
        message = str(err.value)
        assert t('run.notCrawlable', label='某平台源 #src-1', platform='kuaishou') in message
        assert 'src-1' in message, 'the refusal must speak with the user\u2019s node name'

    def test_a_platform_whose_crawl_landed_passes_the_guard(self, monkeypatch):
        import app as app_module

        seen = {}

        class _One:
            def set_sink(self, sink):
                pass

            def set_cursor_sink(self, sink):
                pass

            def search(self, keyword, **kwargs):
                seen['keyword'] = keyword
                seen['target'] = kwargs.get('target_count')
                return [{'标题': 'x', '链接': 'https://www.bilibili.com/video/BV1a/'}]

            def close(self):
                pass

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _One())
        rows = app_module._execute_source_node(self._node('bilibili'), headless=True)
        assert rows and seen['keyword'] == 'ai' and seen['target'] == 50

    def test_a_platform_that_refuses_headless_is_run_in_a_visible_window(self, monkeypatch):
        """Douyin answers a headless browser with a captcha interstitial on every
        navigation, so the node must be re-planned onto a real window rather than
        quietly returning nothing — and the console has to say it switched."""
        import app as app_module

        from crawlers.video import DouyinCrawler

        seen = {}
        logs = []

        class _One:
            def set_sink(self, sink):
                pass

            def set_cursor_sink(self, sink):
                pass

            def search(self, keyword, **kwargs):
                return [{'标题': 'x', '链接': 'https://www.douyin.com/video/7665683746674183459'}]

            def close(self):
                pass

        assert DouyinCrawler.never_headless is True
        monkeypatch.setattr(app_module, 'get_crawler', _capture(_One, seen))
        monkeypatch.setattr(app_module, 'add_log', lambda msg: logs.append(msg))
        from i18n import t

        rows = app_module._execute_source_node(self._node('douyin'), headless=True)
        assert rows
        assert seen['headless'] is False, 'the crawler must be built with a visible window'
        assert t('run.forcedVisible', label='某平台源 #src-1', platform='douyin') in logs


class TestHeadlessIsNeverSilentlyIgnored:
    """Two crawl paths override the run's 无头 choice, and an unexplained browser
    appearing mid-run reads as the setting having been broken.

    Douyin refuses a headless browser on every navigation, and comment crawling
    drives a visible window for all platforms (zhihu content pages reject
    headless). Both now say so in the console; a user who sees no such line is
    looking at a crawl that really did run headless.
    """

    @staticmethod
    def _node(nid='src-1', title='源', platform='douyin'):
        return {'id': nid, 'type': 'source', 'title': title, 'platform': platform, 'params': {'keyword': 'ai'}}

    def test_the_source_node_announces_the_switch(self, monkeypatch):
        import app as app_module

        from i18n import t

        seen = {}

        class _One:
            def set_sink(self, sink):
                pass

            def set_cursor_sink(self, sink):
                pass

            def search(self, keyword, **kwargs):
                return [{'标题': 'x', '链接': 'https://www.douyin.com/video/1'}]

            def close(self):
                pass

        logs = []
        monkeypatch.setattr(app_module, 'get_crawler', _capture(_One, seen))
        monkeypatch.setattr(app_module, 'add_log', lambda m: logs.append(m))
        app_module._execute_source_node(self._node(), headless=True)
        assert seen['headless'] is False
        assert t('run.forcedVisible', label='源 #src-1', platform='douyin') in logs

    def test_the_comment_node_announces_it_only_when_headless_was_asked(self, monkeypatch):
        """The notice is the whole point: the node drives a visible window for
        every platform, and a browser appearing mid-"headless" run with no
        explanation reads as the setting having been ignored."""
        import app as app_module

        from i18n import t

        class _Session:
            def __init__(self, *args, **kwargs):
                pass

            def crawl_zhihu(self, url, limit):
                return [], 'ok'

        logged = []
        monkeypatch.setattr('crawlers.comments.CommentSession', _Session)
        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: None)
        monkeypatch.setattr(app_module, 'add_log', lambda m: logged.append(m))
        node = {'id': 'c-1', 'type': 'comment', 'title': '评论', 'params': {'urls': 'https://www.zhihu.com/question/1'}}

        assert app_module._execute_comment_node(node, headless=True) == []
        assert t('run.forcedVisibleComment', label='评论 #c-1') in logged

        logged.clear()
        assert app_module._execute_comment_node(node, headless=False) == []
        notice = t('run.forcedVisibleComment', label='评论 #c-1')
        assert notice not in logged, 'a run that already wanted a visible window must not claim it was switched'
