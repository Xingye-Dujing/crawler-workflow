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

from i18n import t
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
        # ``node_done`` counts the nodes that really finished, not the ones merely
        # visited — the same answer the console gives for this run.
        assert run['node_total'] == 3 and run['node_done'] == 1
        nodes = {node['node_id']: node for node in run['nodes']}
        assert [nodes[nid]['status'] for nid in ('node-1', 'node-2', 'node-3')] == ['done', 'partial', 'failed']
        assert [nodes[nid]['row_count'] for nid in ('node-1', 'node-2', 'node-3')] == [3, 2, 0]
        # Every node that reached a finish carries its own wall time: an int >= 0 (second-granularity,
        # so the value is 0 unless begin→finish crossed a second). Never None for a closed node.
        assert [nodes[nid]['duration_seconds'] >= 0 for nid in ('node-1', 'node-2', 'node-3')] == [True, True, True]
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

    def test_all_mode_lists_a_finished_run_of_a_different_shape(self, client, app_module):
        """The 断点续跑 node grafts a stored node's rows into a graph that need not
        resemble the run they came from — adding the node itself re-fingerprints the
        canvas. So its list must ignore both the structure match and the
        finished/unfinished split that the banner path enforces, or the node would
        only ever show data when it happened to be disabled."""
        store = app_module._RUN_STORE
        _seed(
            store,
            'old-crawl',
            fingerprint='a-completely-different-graph',
            status=RUN_COMPLETED,
            nodes=[('node-2', 'source', NODE_DONE, 4)],
        )
        # The banner path refuses it: wrong shape, and it finished.
        assert client.post('/api/runs/resumable', json={'workflow': _workflow()}).get_json()['runs'] == []
        # The node path (all=true) lists it, with the per-node rows it reads from.
        body = client.post('/api/runs/resumable', json={'workflow': _workflow(), 'all': True}).get_json()
        ids = [run['run_id'] for run in body['runs']]
        assert ids == ['old-crawl']
        node_ids = [(n['node_id'], n['row_count']) for n in body['runs'][0]['nodes']]
        assert ('node-2', 4) in node_ids

    def test_all_mode_still_hides_a_live_run(self, client, app_module):
        """A run still writing is never a resume source — all=true widens *which*
        past runs are visible, it does not offer to discard the in-flight one."""
        store = app_module._RUN_STORE
        _seed(store, 'live', status=RUN_RUNNING, nodes=[('node-1', 'source', NODE_DONE, 2)], total=1)
        body = client.post('/api/runs/resumable', json={'workflow': _workflow(), 'all': True}).get_json()
        assert body['runs'] == []


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

    def test_clear_empties_every_run_and_hands_back_what_they_claimed(self, client, app_module):
        """The third housekeeping answer: 清空 is neither delete nor discard.

        Deleting one record keeps its crawl claims (the crawl was paid for and another run may
        still be continuing under them); emptying *every* record is a request to start from
        nothing, so a surviving ``item_seen`` row would be a promise about data that no longer
        exists anywhere — the next crawl of the same canvas would under-deliver with no table
        left that could explain the gap. The answer cache is the deliberate survivor: an LLM
        answer is paid for by its prompt, not by the run row.
        """
        store = app_module._RUN_STORE
        _seed(store, 'one', name='wf-a', status=RUN_COMPLETED)
        _seed(store, 'two', name='wf-b', status=RUN_INTERRUPTED)
        for rid in ('one', 'two'):
            store.begin_node(rid, 'node-1', 'source')
            store.append_rows(rid, 'node-1', _rows(2), dedupe_scope=f'item:fp-{rid}')
        store.cache_put('emotion|qwen', 'asked before', ['a stored answer'])
        assert store.stats()['seen_keys'] == 4 and store.stats()['cache_entries'] == 1

        body = client.post('/api/runs/clear', json={'confirm': True}).get_json()
        assert body['ok'] is True
        assert body['removed']['runs'] == 2
        assert body['removed']['node_rows'] == 4
        assert body['removed']['item_claims'] == 4, 'clearing history must release its dedupe ledger'
        assert store.list_resumable(limit=10, include_finished=True) == []
        stats = store.stats()
        assert stats['seen_keys'] == 0
        assert stats['cache_entries'] == 1, 'a cleared history must not make the next run re-pay the LLM'

    @pytest.mark.parametrize('payload', [{}, {'confirm': False}, {'confirm': 'true'}, None])
    def test_clear_refuses_without_an_explicit_confirm(self, client, app_module, payload):
        """A stray POST must not be able to erase a history, so the flag is read as a boolean.

        ``'true'`` is included because that is what a form-encoded or query-string caller sends,
        and a truthy string is exactly the accident this route cannot afford to honour.
        """
        store = app_module._RUN_STORE
        _seed(store, 'precious', status=RUN_COMPLETED)
        kwargs = {'json': payload} if payload is not None else {}
        response = client.post('/api/runs/clear', **kwargs)
        assert response.status_code == 400
        assert t('api.needConfirm') in response.get_json()['error']
        assert store.get_run('precious') is not None, 'a refused clear must not have deleted anything'

    def test_clear_spares_the_run_a_worker_is_still_writing(self, client, app_module):
        """The panel's button is allowed while a run is live, so the live record has to be
        excluded rather than the whole request refused — deleting rows under a worker would
        destroy state mid-flight (the same reason ``purge`` takes ``exclude_run_id``)."""
        store = app_module._RUN_STORE
        _seed(store, 'finished-elsewhere', name='wf-a', status=RUN_COMPLETED)
        _seed(store, 'in-flight', name='wf-b', status=RUN_RUNNING)
        app_module.execution_state.update({'running': True, 'run_id': 'in-flight'})
        try:
            body = client.post('/api/runs/clear', json={'confirm': True}).get_json()
        finally:
            app_module.execution_state.update({'running': False, 'run_id': ''})
        assert body['removed']['runs'] == 1
        assert store.get_run('in-flight') is not None
        assert store.get_run('finished-elsewhere') is None

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

    def test_purge_spares_a_pinned_run(self, client, app_module):
        """The user directive: a 置顶 (locked) record survives even the age/count
        sweep — a pin that only stopped a manual delete but not the auto sweep is
        not a pin. The lock key must also stay (its run still exists)."""
        store = app_module._RUN_STORE
        _seed(store, 'ancient', name='wf', status=RUN_COMPLETED)
        store._execute("UPDATE runs SET started_at = '2019-01-01T00:00:00' WHERE run_id = 'ancient'")
        app_module.lock_store.set_locked('runs', 'ancient', True)
        body = client.post('/api/runs/purge').get_json()
        assert body['removed']['runs'] == 0, 'a pinned run must not be aged out'
        assert store.get_run('ancient') is not None
        assert 'ancient' in app_module.lock_store.all_locks()['runs']

    def test_purge_prunes_the_lock_of_a_run_that_no_longer_exists(self, client, app_module):
        """A lock whose record was deleted out from under it is a dead key; the sweep
        forgets it so locks.json cannot accumulate ids with no run behind them."""
        app_module.lock_store.set_locked('runs', 'ghost', True)
        client.post('/api/runs/purge')
        assert 'ghost' not in app_module.lock_store.all_locks()['runs']

    def test_purge_of_an_empty_store_reports_zeros(self, client):
        assert client.post('/api/runs/purge').get_json() == {
            'ok': True,
            'removed': {'runs': 0, 'cache_entries': 0, 'seen_keys': 0},
        }


# ─── persisted-console viewer endpoints ────────────────────────────────────


def _seed_log(store, run_id, lines):
    """File an ordered console for a run: ``(line, wf_idx, level)`` tuples → durable rows."""
    rows = [(f'2026-10-06T04:00:{i:02d}', wf_idx, '', level, line) for i, (line, wf_idx, level) in enumerate(lines)]
    store.append_log(run_id, rows)


class TestRunLogEndpoints:
    """``/api/runs/<id>/log`` (+ ``.txt``) read ONLY the durable ``run_log`` table.

    The invariant that matters: these reads never touch ``execution_state``. The live
    console and the page-refresh reattach run off that in-memory buffer; a durable viewer
    that disturbed it (or that only worked while a run was in flight) would be worse than
    no feature, because it would break the mechanism the user already relies on.
    """

    def test_page_returns_the_whole_log_ascending_with_a_window(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'r1', name='wf', status=RUN_COMPLETED)
        _seed_log(store, 'r1', [(f'l{i}', 0, 'info') for i in range(5)])
        body = client.get('/api/runs/r1/log').get_json()
        assert [r['line'] for r in body['rows']] == ['l0', 'l1', 'l2', 'l3', 'l4']
        assert (body['min_seq'], body['max_seq']) == (0, 4)
        assert body['has_more'] is False

    def test_limit_pages_and_before_walks_older(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'r1', status=RUN_COMPLETED)
        _seed_log(store, 'r1', [(f'l{i}', 0, 'info') for i in range(7)])
        newest = client.get('/api/runs/r1/log?limit=3').get_json()
        assert [r['line'] for r in newest['rows']] == ['l4', 'l5', 'l6']
        assert newest['has_more'] is True
        older = client.get(f'/api/runs/r1/log?limit=3&before={newest["min_seq"]}').get_json()
        assert [r['line'] for r in older['rows']] == ['l1', 'l2', 'l3']

    def test_filters_on_level_wf_and_search(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'r1', status=RUN_COMPLETED)
        _seed_log(
            store,
            'r1',
            [
                ('抓取 三亚 完成', 0, 'info'),
                ('登录墙', 0, 'error'),
                ('抓取 海口 完成', 1, 'info'),
            ],
        )
        assert [r['line'] for r in client.get('/api/runs/r1/log?level=error').get_json()['rows']] == ['登录墙']
        assert [r['line'] for r in client.get('/api/runs/r1/log?wf=1').get_json()['rows']] == ['抓取 海口 完成']
        assert [r['line'] for r in client.get('/api/runs/r1/log?q=三亚').get_json()['rows']] == ['抓取 三亚 完成']

    def test_a_junk_level_or_wf_is_ignored_not_an_error(self, client, app_module):
        """A hand-typed query parameter is a nicety on a read path, never a 400 — an
        unrecognised level simply filters on nothing (so the whole log still shows)."""
        store = app_module._RUN_STORE
        _seed(store, 'r1', status=RUN_COMPLETED)
        _seed_log(store, 'r1', [('a', 0, 'info'), ('b', 1, 'error')])
        body = client.get('/api/runs/r1/log?level=bogus&wf=notanint').get_json()
        assert [r['line'] for r in body['rows']] == ['a', 'b']

    def test_unknown_run_is_a_404(self, client, app_module):
        assert client.get('/api/runs/nope/log').status_code == 404

    def test_reading_the_log_never_disturbs_the_live_console(self, client, app_module):
        """The reattach safety, asserted at the endpoint the new feature adds."""
        store = app_module._RUN_STORE
        _seed(store, 'r1', status=RUN_COMPLETED)
        _seed_log(store, 'r1', [('x', 0, 'info')])
        before = {key: list(app_module.execution_state[key]) for key in ('logs',)}
        before_total = app_module.execution_state['_log_total']
        client.get('/api/runs/r1/log')
        client.get('/api/runs/r1/log.txt')
        assert app_module.execution_state['logs'] == before['logs']
        assert app_module.execution_state['_log_total'] == before_total

    def test_download_is_a_text_attachment_in_order(self, client, app_module):
        store = app_module._RUN_STORE
        _seed(store, 'r1', status=RUN_COMPLETED)
        _seed_log(store, 'r1', [(f'l{i}', 0, 'info') for i in range(5)])
        resp = client.get('/api/runs/r1/log.txt')
        assert resp.status_code == 200
        assert 'text/plain' in resp.mimetype
        assert 'attachment' in resp.headers['Content-Disposition']
        assert 'run-r1.log' in resp.headers['Content-Disposition']
        text = resp.get_data(as_text=True)
        assert [ln for ln in text.splitlines() if ln] == ['l0', 'l1', 'l2', 'l3', 'l4']

    def test_download_honours_the_same_filters_as_the_page(self, client, app_module):
        """The download must reproduce 「所见」: whatever the viewer is showing is what saves."""
        store = app_module._RUN_STORE
        _seed(store, 'r1', status=RUN_COMPLETED)
        _seed_log(store, 'r1', [('a', 0, 'info'), ('登录墙', 0, 'error'), ('b', 1, 'info')])
        text = client.get('/api/runs/r1/log.txt?level=error').get_data(as_text=True)
        assert [ln for ln in text.splitlines() if ln] == ['登录墙']

    def test_download_of_unknown_run_is_localized_text_404(self, client):
        resp = client.get('/api/runs/nope/log.txt')
        assert resp.status_code == 404
        assert t('api.runNotFound', rid='nope') in resp.get_data(as_text=True)
