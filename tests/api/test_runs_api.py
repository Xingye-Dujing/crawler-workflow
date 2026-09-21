"""Tests for the run-record endpoints behind 断点续跑.

``/api/runs/*`` is what the resume banner, the run-records panel and the
resume node all read. The endpoints are thin wrappers over ``RunStore``, so the
value here is in the *decisions* they encode:

* a resumable lookup matches on workflow *structure*, so editing a keyword
  still finds the interrupted attempt of the same workflow,
* ``list`` shows finished and orphaned runs that ``resumable`` hides —
  otherwise a run nobody can continue could never be cleaned up,
* ``discard`` and ``delete`` differ by exactly one thing: whether the
  "already crawled" claims go with the run,
* node state is reported as it was recorded (partial / failed / done), because
  that is what tells the UI which rows are already paid for.

Runs are seeded straight into the store the ``client`` fixture provisioned, so
no crawler has to die to produce a half-finished run.
"""
import pytest

from services.run_store import (
    NODE_DONE,
    NODE_FAILED,
    NODE_PARTIAL,
    RUN_COMPLETED,
    RUN_INTERRUPTED,
    RUN_RUNNING,
    workflow_fingerprint,
)

pytestmark = pytest.mark.api


def _rows(count=3):
    return [{'标题': f'帖子 {i}', '正文': f'正文 {i}', '链接': f'https://example.com/{i}'} for i in range(count)]


def _workflow(node_id='node-1', keyword='三亚'):
    return {
        'nodes': [{'id': node_id, 'type': 'source', 'operation': '', 'params': {'keyword': keyword}}],
        'connections': [],
    }


def _seed(store, run_id='r1', name='wf', fingerprint='fp-a', status=RUN_RUNNING, nodes=(), total=0):
    store.start_run(run_id, name, fingerprint, node_total=total)
    for node_id, node_type, node_status, row_count in nodes:
        store.begin_node(run_id, node_id, node_type, fingerprint=f'fp-{node_id}')
        if row_count:
            store.append_rows(run_id, node_id, _rows(row_count))
        store.finish_node(run_id, node_id, node_status)
    if status != RUN_RUNNING:
        store.finish_run(run_id, status)
    return run_id


class TestRunListing:
    def test_list_includes_finished_runs_newest_first(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'old', name='wf-old', status=RUN_COMPLETED)
        _seed(store, 'mid', name='wf-mid', status=RUN_INTERRUPTED)
        _seed(store, 'live', name='wf-live', total=2, nodes=[('node-1', 'source', NODE_PARTIAL, 4)])

        runs = client.get('/api/runs/list').get_json()['runs']
        assert [run['run_id'] for run in runs] == ['live', 'mid', 'old']
        by_id = {run['run_id']: run for run in runs}
        assert by_id['live']['resumable'] is True and by_id['live']['partial_nodes'] == ['node-1']
        assert by_id['live']['rows_kept'] == 4
        assert by_id['mid']['resumable'] is True and by_id['mid']['partial_nodes'] == []
        # A clean run has nothing to continue, yet it stays visible here so it
        # can still be deleted.
        assert by_id['old']['resumable'] is False
        assert {'workflow_name', 'workflow_fingerprint', 'nodes', 'started_at'} <= set(by_id['old'])

    def test_list_limit_is_bounded_by_the_query(self, client, app_module):
        store = app_module._RUN_STORE
        for i in range(3):
            _seed(store, f'r{i}', status=RUN_INTERRUPTED)
        assert len(client.get('/api/runs/list', query_string={'limit': 2}).get_json()['runs']) == 2
        # Out-of-range limits clamp rather than emptying the panel.
        assert len(client.get('/api/runs/list', query_string={'limit': 0}).get_json()['runs']) == 1

    def test_detail_shows_each_node_exactly_as_it_was_left(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(
            store,
            'broken',
            total=3,
            nodes=[
                ('node-1', 'source', NODE_DONE, 3),
                ('node-2', 'analysis', NODE_PARTIAL, 2),
                ('node-3', 'output', NODE_FAILED, 0),
            ],
        )
        store.finish_node('broken', 'node-3', NODE_FAILED, error='selenium died')
        store.finish_run('broken', RUN_INTERRUPTED)

        run = client.get('/api/runs/broken').get_json()['run']
        assert run['status'] == RUN_INTERRUPTED
        assert run['node_total'] == 3 and run['node_done'] == 3
        nodes = {node['node_id']: node for node in run['nodes']}
        assert [nodes[nid]['status'] for nid in ('node-1', 'node-2', 'node-3')] == ['done', 'partial', 'failed']
        assert [nodes[nid]['row_count'] for nid in ('node-1', 'node-2', 'node-3')] == [3, 2, 0]
        assert nodes['node-3']['error'] == 'selenium died'
        assert nodes['node-1']['fingerprint'] == 'fp-node-1'

    def test_detail_of_an_unknown_run_is_404(self, client):
        response = client.get('/api/runs/never-happened')
        assert response.status_code == 404
        body = response.get_json()
        assert body['ok'] is False
        assert 'No such run' in body['error']

    def test_status_describes_the_run_in_flight(self, client, app_module):
        quiet = client.get('/api/runs/status').get_json()
        assert quiet == {'ok': True, 'running': False, 'run_id': '', 'resume': False}

        app_module.execution_state['running'] = True
        app_module.execution_state['run_id'] = 'abc123'
        app_module.execution_state['resume'] = True
        live = client.get('/api/runs/status').get_json()
        assert live == {'ok': True, 'running': True, 'run_id': 'abc123', 'resume': True}

    def test_stats_count_rows_claims_and_cache(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'stats', status=RUN_COMPLETED, nodes=[('node-1', 'source', NODE_DONE, 3)])
        store.cache_put('emotion|qwen|正文', 'k1', ['pos'])
        body = client.get('/api/runs/stats').get_json()
        assert body['ok'] is True
        stats = body['stats']
        assert stats['runs'] == 1 and stats['interrupted'] == 0
        assert stats['node_rows'] == 3
        assert stats['cache_entries'] == 1
        assert stats['seen_keys'] == 0
        assert stats['bytes'] > 0


class TestResumableLookup:
    def test_an_interrupted_run_of_the_same_shape_is_found(self, client, app_module):
        store = app_module._RUN_STORE
        workflow = _workflow()
        _seed(store, 'interrupted', fingerprint=workflow_fingerprint(workflow), status=RUN_INTERRUPTED)

        found = client.post('/api/runs/resumable', json={'workflow': workflow}).get_json()
        assert [run['run_id'] for run in found['runs']] == ['interrupted']
        # Editing the keyword changes settings, not structure, so the offer
        # survives — that is the whole point of matching on the fingerprint.
        tweaked = client.post('/api/runs/resumable', json={'workflow': _workflow(keyword='海口')}).get_json()
        assert [run['run_id'] for run in tweaked['runs']] == ['interrupted']

    def test_a_rewired_canvas_finds_nothing(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'orphan', fingerprint=workflow_fingerprint(_workflow()), status=RUN_INTERRUPTED)
        rewired = _workflow(node_id='node-9')
        assert client.post('/api/runs/resumable', json={'workflow': rewired}).get_json()['runs'] == []

    def test_completed_runs_are_not_offered(self, client, app_module):
        store = app_module._RUN_STORE
        workflow = _workflow()
        _seed(store, 'tidy', fingerprint=workflow_fingerprint(workflow), status=RUN_COMPLETED)
        assert client.post('/api/runs/resumable', json={'workflow': workflow}).get_json() == {'ok': True, 'runs': []}

    @pytest.mark.parametrize('payload', [{}, {'workflow': {}}, {'workflow': {'nodes': []}}, {'workflow': None}])
    def test_a_canvas_with_nothing_on_it_answers_empty(self, client, payload):
        assert client.post('/api/runs/resumable', json=payload).get_json() == {'ok': True, 'runs': []}

    def test_the_number_of_offers_is_capped(self, client, app_module):
        store = app_module._RUN_STORE
        fingerprint = workflow_fingerprint(_workflow())
        for i in range(3):
            _seed(store, f'r{i}', fingerprint=fingerprint, status=RUN_INTERRUPTED)
        body = client.post('/api/runs/resumable', json={'workflow': _workflow(), 'limit': 2}).get_json()
        assert [run['run_id'] for run in body['runs']] == ['r2', 'r1']


class TestRunHousekeeping:
    def test_discard_throws_away_the_run_and_its_crawl_claims(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'keep-going', status=RUN_INTERRUPTED)
        store.begin_node('keep-going', 'node-1', 'source')
        kept, _ = store.append_rows('keep-going', 'node-1', _rows(3), dedupe_scope='item:fp-node-1')
        assert kept == 3
        assert store.claim_item('item:other', 'hand-key', 'keep-going') is True

        body = client.post('/api/runs/discard', json={'run_id': 'keep-going'}).get_json()
        assert body['ok'] is True
        # rows, node state and the run row itself, plus every claim released.
        assert body['removed']['node_rows'] == 3
        assert body['removed']['node_runs'] == 1
        assert body['removed']['runs'] == 1
        assert body['removed']['item_claims'] == 4
        assert store.get_run('keep-going') is None
        assert store.stats()['seen_keys'] == 0
        # Starting over really does collect everything again.
        assert store.claim_item('item:other', 'hand-key', 'new-run') is True

    @pytest.mark.parametrize(('payload', 'status'), [({}, 400), ({'run_id': '   '}, 400), ({'run_id': 'ghost'}, 404)])
    def test_discard_needs_a_run_that_exists(self, client, payload, status):
        response = client.post('/api/runs/discard', json=payload)
        assert response.status_code == status
        assert 'No such run' in response.get_json()['error']

    def test_delete_drops_the_copy_but_keeps_what_was_crawled(self, client, app_module):
        """The difference between the two buttons: an old finished run can go
        without its items becoming unseen again for a crawl still in progress."""
        store = app_module._RUN_STORE
        _seed(store, 'finished', status=RUN_COMPLETED)
        store.begin_node('finished', 'node-1', 'source')
        store.append_rows('finished', 'node-1', _rows(2), dedupe_scope='item:fp-node-1')
        before = store.stats()['seen_keys']
        assert before == 2

        body = client.post('/api/runs/delete', json={'run_id': 'finished'}).get_json()
        assert body['ok'] is True
        assert body['removed']['node_rows'] == 2
        assert store.get_run('finished') is None
        assert store.stats()['seen_keys'] == before

    def test_delete_and_discard_need_a_run_id(self, client):
        for path in ('/api/runs/delete', '/api/runs/discard'):
            assert client.post(path, json={}).status_code == 400

    def test_purge_ages_out_runs_and_stale_cache_entries(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'ancient', name='wf', status=RUN_COMPLETED)
        store._execute("UPDATE runs SET started_at = '2019-01-01T00:00:00' WHERE run_id = 'ancient'")
        _seed(store, 'fresh', name='wf', status=RUN_INTERRUPTED)
        store.cache_put('emotion|qwen', 'old', ['stale answer'])
        store._execute("UPDATE llm_cache SET created_at = '2019-01-01T00:00:00'")

        body = client.post('/api/runs/purge').get_json()
        assert body['ok'] is True
        assert body['removed']['runs'] == 1
        assert body['removed']['cache_entries'] == 1
        assert store.get_run('ancient') is None
        assert store.get_run('fresh') is not None
        # The interrupted run is the one somebody may still continue.
        assert [run['run_id'] for run in client.get('/api/runs/list').get_json()['runs']] == ['fresh']

    def test_purge_of_an_empty_store_reports_zeros(self, client):
        assert client.post('/api/runs/purge').get_json() == {
            'ok': True,
            'removed': {'runs': 0, 'cache_entries': 0, 'seen_keys': 0},
        }
