"""Loading one run's results, not a per-node "whatever is newest".

The canvas can pin a run id into every preview/chart payload. Without the pin the
run store answers each node independently with its newest rows, which is right for
"show me the latest table" and wrong the moment a reader is looking at one specific
run: node-1 could come from last night and node-2 from this morning, and the figure
would look complete while describing a run that never happened.

These tests seed two finished runs of the SAME workflow with different rows, then
ask through the real routes. ``done``/``restored`` statuses live in the run ledger
too, so a loaded run's green/red marks have the same provenance as its tables.
"""

import pytest

from services.runs.store import NODE_DONE, RUN_COMPLETED, workflow_fingerprint

pytestmark = pytest.mark.api


def _workflow():
    return {
        'nodes': [
            {'id': 'node-1', 'type': 'upload', 'params': {'dataset_id': 'd1'}},
            {'id': 'node-2', 'type': 'visualize', 'params': {'chart_type': 'bar'}},
        ],
        'connections': [{'from': 'node-1', 'to': 'node-2'}],
    }


def _store_run(store, run_id, name, rows, node_ids=('node-1', 'node-2'), fingerprint=None):
    """One completed run whose node-1 produced ``rows`` and node-2 a chart spec."""
    store.start_run(run_id, name, fingerprint or workflow_fingerprint(_workflow()), node_total=len(node_ids))
    for nid in node_ids:
        store.begin_node(run_id, nid, 'upload', fingerprint=f'fp-{run_id}-{nid}')
        if nid == 'node-1':
            store.append_rows(run_id, nid, rows)
            store.finish_node(run_id, nid, NODE_DONE)
        else:
            # A visualize node really stores no rows; its status is still done.
            store.finish_node(run_id, nid, NODE_DONE)
    store.finish_run(run_id, RUN_COMPLETED)


@pytest.fixture
def two_runs(client, app_module):
    store = app_module._RUN_STORE
    _store_run(store, 'old', 'wf', [{'城市': '旧城', '分数': 1}, {'城市': '旧城', '分数': 3}])
    _store_run(store, 'new', 'wf', [{'城市': '新城', '分数': 2}])
    return app_module


def _preview(client, **payload):
    return client.post('/api/data/preview', json={'node_id': 'node-1', **payload})


class TestRunPinnedPreview:
    def test_a_run_id_reads_that_runs_rows_even_when_a_newer_run_exists(self, client, two_runs):
        body = _preview(client, workflow_name='wf', run_id='old').get_json()
        assert body['ok'] is True
        assert [row['城市'] for row in body['rows']] == ['旧城', '旧城']
        assert body['total_rows'] == 2

    def test_without_a_run_id_the_newest_rows_still_win(self, client, two_runs):
        """The historical default is not broken by the picker: a caller that names no
        run still gets the newest table, exactly as before."""
        body = _preview(client, workflow_name='wf').get_json()
        assert [row['城市'] for row in body['rows']] == ['新城']

    def test_the_pin_beats_even_in_memory_results(self, client, two_runs):
        """Reading the live dict here would mix a newer attempt into a historical
        run. A pinned request must bypass memory and read the ledger."""
        two_runs.execution_state['results']['node-1'] = [{'城市': '内存里的', '分数': 9}]
        pinned = _preview(client, workflow_name='wf', run_id='old').get_json()
        assert [row['城市'] for row in pinned['rows']] == ['旧城', '旧城']
        unpinned = _preview(client, workflow_name='wf').get_json()
        assert [row['城市'] for row in unpinned['rows']] == ['内存里的']

    def test_a_run_that_no_longer_exists_is_refused_by_name(self, client, two_runs):
        response = _preview(client, workflow_name='wf', run_id='ghost')
        assert response.status_code == 400
        assert 'ghost' in response.get_json()['error']

    def test_a_node_absent_from_the_pinned_run_has_no_table(self, client, app_module):
        store = app_module._RUN_STORE
        _store_run(store, 'only-one', 'wf', [{'城市': '独有', '分数': 1}], node_ids=('node-1',))
        response = client.post(
            '/api/data/preview',
            json={'node_id': 'node-2', 'workflow_name': 'wf', 'run_id': 'only-one'},
        )
        assert response.status_code == 400
        assert response.get_json()['code'] == 'no_run_data'


class TestRunPinnedChart:
    def test_the_chart_is_drawn_from_the_loaded_runs_rows(self, client, two_runs):
        response = client.post(
            '/api/visualize/render',
            json={
                'chart_type': 'bar',
                'x_field': '城市',
                'y_field': '分数',
                'agg': 'sum',
                'node_id': 'node-1',
                'workflow_name': 'wf',
                'run_id': 'old',
            },
        )
        body = response.get_json()
        assert body['ok'] is True
        option = body['option']
        # One category (旧城) summing to 4 — the old run's shape, not the new one's.
        assert option['xAxis']['data'] == ['旧城']
        assert option['series'][0]['data'] == [4]

    def test_the_same_chart_unpinned_reads_the_newest_run(self, client, two_runs):
        body = client.post(
            '/api/visualize/render',
            json={
                'chart_type': 'bar',
                'x_field': '城市',
                'y_field': '分数',
                'agg': 'sum',
                'node_id': 'node-1',
                'workflow_name': 'wf',
            },
        ).get_json()
        assert body['ok'] is True
        assert body['option']['xAxis']['data'] == ['新城']

    def test_the_studio_source_probe_also_honours_the_pin(self, client, two_runs):
        """The studio's selectable-source list is a preview of the load: a probe that
        counted the newest run would enable a node whose loaded run has nothing."""
        body = client.post(
            '/api/studio/sources',
            json={
                'candidates': [
                    {'node_id': 'node-1', 'payload': {'node_id': 'node-1', 'workflow_name': 'wf', 'run_id': 'old'}},
                    {'node_id': 'node-2', 'payload': {'node_id': 'node-2', 'workflow_name': 'wf', 'run_id': 'old'}},
                ]
            },
        ).get_json()
        by_id = {row['node_id']: row for row in body['sources']}
        assert by_id['node-1']['available'] is True and by_id['node-1']['rows'] == 2
        assert by_id['node-2']['available'] is False, 'node-2 stored no rows in this run'
