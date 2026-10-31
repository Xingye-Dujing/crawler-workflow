"""Single-node rerun (feature 12): prune one node's subtree, then resume the SAME run so the
engine re-executes exactly that subtree and reuses every kept upstream row.

The real engine is never run here — ``begin_run`` is monkeypatched — so these tests pin the
endpoint's OWN logic: the downstream closure, the named refusals, and the hand-off (a resume of that
same run, carrying the subtree to erase). The erase itself belongs to the claimed worker, which is
what :class:`TestTheWipeFollowsTheClaim` pins; ``store.invalidate_nodes`` is exercised directly there.
"""

import pytest

from engine.workflow import effective_workflow
from services.runs.store import NODE_DONE, RUN_COMPLETED, workflow_fingerprint

pytestmark = pytest.mark.api


def _run_module():
    """``engine.run`` owns the run start, so that is where a fake 执行 has to be installed."""
    import engine.run

    return engine.run


def _workflow():
    return {
        'nodes': [
            {'id': 'n1', 'type': 'upload', 'params': {'dataset_id': 'd1'}},
            {'id': 'n2', 'type': 'process', 'params': {'operation': 'keyword'}},
            {'id': 'n3', 'type': 'output', 'params': {}},
        ],
        'connections': [{'from': 'n1', 'to': 'n2'}, {'from': 'n2', 'to': 'n3'}],
    }


def _seed_completed_run(store, app_module, run_id='rerun1', node_ids=('n1', 'n2', 'n3'), fingerprint=None):
    wf = _workflow()
    fp = fingerprint or workflow_fingerprint(effective_workflow(wf))
    store.start_run(run_id, 'wf', fp)
    for nid in node_ids:
        store.begin_node(run_id, nid, 'process', fingerprint='node-' + nid)
        store.finish_node(run_id, nid, NODE_DONE)
    store.finish_run(run_id, RUN_COMPLETED)
    return fp


@pytest.fixture
def fake_begin(monkeypatch):
    """Replace the real start path with a recorder, so nothing runs while we observe the hand-off."""

    calls = []

    def _fake(data, lang):
        calls.append((data, lang))
        return {'status': 200, 'body': {'ok': True, 'run_id': data.get('resume_run_id') or 'new'}}

    monkeypatch.setattr(_run_module(), 'begin_run', _fake)
    return calls


class TestInvalidateNodes:
    def test_a_cleared_node_loses_its_status_and_rows(self, client, app_module):
        store = app_module.get_run_store()
        _seed_completed_run(store, app_module)
        assert store.get_node_status('rerun1', 'n2') == NODE_DONE
        cleared = store.invalidate_nodes('rerun1', ['n2', 'n3'])
        assert cleared == 2
        assert store.get_node_status('rerun1', 'n2') is None
        assert store.get_node_status('rerun1', 'n3') is None
        # Upstream kept: the whole point is that only the target subtree is re-run.
        assert store.get_node_status('rerun1', 'n1') == NODE_DONE

    def test_invalidating_a_node_releases_the_dedupe_claims_it_bought(self, client, app_module):
        """A rerun reuses the SAME per-node fingerprint, so leaving the ``item_seen`` rows
        meant every freshly crawled item hit "already collected" and was dropped: 重跑节点 ran
        the crawl and it settled with zero rows on data the user had just deleted. The claims
        this run bought for THIS node go with its rows."""
        store = app_module.get_run_store()
        _seed_completed_run(store, app_module)
        # n2's scope is 'item:node-n2' (fingerprint='node-'+nid, _item_scope's shape).
        assert store.claim_item('item:node-n2', 'ITEM-A', 'rerun1') is True
        assert store.claim_item('item:node-n2', 'ITEM-A', 'rerun1') is False, 'dedupe holds before the rerun'
        # An upstream node the rerun keeps must keep its own claim.
        assert store.claim_item('item:node-n1', 'KEEP-ME', 'rerun1') is True

        store.invalidate_nodes('rerun1', ['n2', 'n3'])

        assert store.claim_item('item:node-n2', 'ITEM-A', 'rerun1') is True, "n2's claim was not released"
        assert store.claim_item('item:node-n1', 'KEEP-ME', 'rerun1') is False, 'a kept node lost its dedupe'


class TestTheWipeFollowsTheClaim:
    """The erase belongs to the run that owns the slot, never to the request that asked for it.

    The route used to delete the subtree and only THEN call ``begin_run``. Anything that won the
    claim in that gap — a scheduled fire, the queue draining another account's run, a second 运行
    press — answered this press with a refusal AFTER its rows and the 「已采集」 claims bought with them
    were gone. Pressing again was then refused forever (「该节点没有可重跑的结果」), and the only way
    back was 继续, which re-crawls the platform and re-pays for rows the user had in hand."""

    def test_a_rerun_that_lost_the_slot_keeps_every_row(self, client, app_module, monkeypatch):
        store = app_module.get_run_store()
        _seed_completed_run(store, app_module)
        assert store.claim_item('item:node-n2', 'ITEM-A', 'rerun1') is True

        def refused(_data, _lang):
            return {'status': 409, 'body': {'ok': False, 'error': 'someone else owns the slot'}}

        monkeypatch.setattr(_run_module(), 'begin_run', refused)
        response = client.post(
            '/api/workflow/rerun-node',
            json={'workflow': _workflow(), 'workflow_name': 'wf', 'node_id': 'n2'},
        )
        assert response.status_code == 409
        assert store.get_node_status('rerun1', 'n2') == NODE_DONE, 'a refused rerun erased anyway'
        assert store.claim_item('item:node-n2', 'ITEM-A', 'rerun1') is False, 'a refused rerun released its claims'

    def test_the_worker_erases_only_the_subtree_its_own_run_named(self, client, app_module):
        from engine.run import _invalidate_rerun_nodes, _rerun_request

        store = app_module.get_run_store()
        _seed_completed_run(store, app_module)
        rerun = _rerun_request({'rerun_invalidate': {'run_id': 'rerun1', 'node_ids': ['n2', 'n3']}}, 'rerun1')
        assert rerun == {'run_id': 'rerun1', 'node_ids': ['n2', 'n3']}

        assert _invalidate_rerun_nodes(store, 'another-run', rerun) == []
        assert store.get_node_status('rerun1', 'n2') == NODE_DONE, 'a wipe for a different run id ran anyway'

        assert _invalidate_rerun_nodes(store, 'rerun1', rerun) == ['n2', 'n3']
        assert store.get_node_status('rerun1', 'n2') is None
        assert store.get_node_status('rerun1', 'n3') is None
        # Upstream kept: the whole point is that only the pressed subtree is re-run.
        assert store.get_node_status('rerun1', 'n1') == NODE_DONE

    def test_a_payload_naming_a_different_run_is_not_a_wipe_order(self):
        """A mirrored entry restored after a restart, or a hand-made payload, must not be allowed to
        name some other run's rows."""
        from engine.run import _rerun_request

        assert _rerun_request({'rerun_invalidate': {'run_id': 'stale', 'node_ids': ['n2']}}, 'rerun1') is None
        assert _rerun_request({'rerun_invalidate': {'run_id': 'rerun1', 'node_ids': []}}, 'rerun1') is None
        assert _rerun_request({'rerun_invalidate': 'not-a-dict'}, 'rerun1') is None
        assert _rerun_request({}, 'rerun1') is None


class TestRerunEndpoint:
    def test_rerunning_a_middle_node_wipes_it_and_its_downstream(self, client, app_module, fake_begin):
        store = app_module.get_run_store()
        _seed_completed_run(store, app_module)
        response = client.post(
            '/api/workflow/rerun-node',
            json={'workflow': _workflow(), 'workflow_name': 'wf', 'node_id': 'n2'},
        )
        body = response.get_json()
        assert response.status_code == 200
        assert body['ok'] is True
        # The closure is exactly {n2, n3}; the kept upstream n1 is not touched.
        assert sorted(body['invalidated']) == ['n2', 'n3']
        # Delegation went through the ordinary start path AS a resume of that same run.
        assert len(fake_begin) == 1
        sent_data, _lang = fake_begin[0]
        assert sent_data['resume_run_id'] == 'rerun1'
        assert sent_data['node_id'] == 'n2'
        # The request DOES NOT WIPE. The subtree travels in the payload and the worker erases it
        # once the slot is genuinely its own — see :class:`TestTheWipeFollowsTheClaim`.
        # ``node_ids`` is compared as a SET on purpose: the closure is a graph walk, and its order is
        # not a contract (the assertion above reads it sorted for the same reason).
        assert sent_data['rerun_invalidate']['run_id'] == 'rerun1'
        assert set(sent_data['rerun_invalidate']['node_ids']) == {'n2', 'n3'}
        assert store.get_node_status('rerun1', 'n2') == NODE_DONE
        assert store.get_node_status('rerun1', 'n1') == NODE_DONE

    def test_an_unknown_node_is_refused_by_name(self, client, app_module, fake_begin):
        store = app_module.get_run_store()
        _seed_completed_run(store, app_module)
        response = client.post(
            '/api/workflow/rerun-node',
            json={'workflow': _workflow(), 'workflow_name': 'wf', 'node_id': 'ghost'},
        )
        assert response.status_code == 400
        assert 'ghost' in response.get_json()['error']
        assert fake_begin == [], 'a refusal must never start a run'

    def test_a_node_that_never_ran_there_is_refused(self, client, app_module, fake_begin):
        store = app_module.get_run_store()
        # Only n1 has a stored row; n2 is on the canvas but produced nothing.
        _seed_completed_run(store, app_module, node_ids=('n1',))
        response = client.post(
            '/api/workflow/rerun-node',
            json={'workflow': _workflow(), 'workflow_name': 'wf', 'node_id': 'n2'},
        )
        assert response.status_code == 409
        assert fake_begin == []

    def test_a_workflow_with_no_prior_run_is_refused(self, client, app_module, fake_begin):
        response = client.post(
            '/api/workflow/rerun-node',
            json={'workflow': _workflow(), 'workflow_name': 'wf', 'node_id': 'n2'},
        )
        assert response.status_code == 404
        assert fake_begin == []

    def test_a_resume_run_from_another_workflow_is_refused(self, client, app_module, fake_begin):
        store = app_module.get_run_store()
        # Seed a run whose fingerprint is NOT the submitted canvas's.
        _seed_completed_run(store, app_module, fingerprint='totally-different')
        response = client.post(
            '/api/workflow/rerun-node',
            json={
                'workflow': _workflow(),
                'workflow_name': 'wf',
                'node_id': 'n2',
                'resume_run_id': 'rerun1',
            },
        )
        assert response.status_code == 409
        assert fake_begin == []

    def test_rerunning_a_node_of_a_live_run_is_refused_and_keeps_every_row(self, client, app_module, fake_begin):
        """A run that is still executing is not a rerun target.

        Its subtree is the record a live worker is writing: erasing it would drop rows and release
        the 「已采集」 claims out from under that thread, and the 继续 it leaves behind re-crawls work
        that had already landed. The refusal is by name, and nothing is touched."""
        store = app_module.get_run_store()
        wf = _workflow()
        fp = workflow_fingerprint(effective_workflow(wf))
        store.start_run('live1', 'wf', fp)  # no finish_run → the run stays RUN_RUNNING
        for nid in ('n1', 'n2', 'n3'):
            store.begin_node('live1', nid, 'process', fingerprint='node-' + nid)
            store.finish_node('live1', nid, NODE_DONE)
        store.claim_item('item:node-n2', 'ITEM-A', 'live1')

        response = client.post(
            '/api/workflow/rerun-node',
            json={'workflow': wf, 'workflow_name': 'wf', 'node_id': 'n2', 'resume_run_id': 'live1'},
        )
        assert response.status_code == 409
        assert fake_begin == [], 'a refused live rerun must not start anything'
        assert store.get_node_status('live1', 'n2') == NODE_DONE, 'the live run was wiped anyway'
        # The claim is still held → the running worker's dedupe was not released under it.
        assert store.claim_item('item:node-n2', 'ITEM-A', 'live1') is False, 'a live run lost its dedupe claim'

    def test_another_live_run_is_refused_before_the_wipe_keeps_the_rows(self, client, app_module, fake_begin):
        """A rerun is never parked, so a busy slot answers this press by name.

        Queueing it would erase the subtree at drain time — minutes later, on a canvas the user has
        since moved on. The data itself is safe either way now that the erase happens inside the
        claimed worker; this refusal is about not deleting someone's results behind their back."""
        store = app_module.get_run_store()
        _seed_completed_run(store, app_module)
        app_module.execution_state['running'] = True
        try:
            response = client.post(
                '/api/workflow/rerun-node',
                json={'workflow': _workflow(), 'workflow_name': 'wf', 'node_id': 'n2', 'resume_run_id': 'rerun1'},
            )
        finally:
            app_module.execution_state['running'] = False
        assert response.status_code == 409
        assert response.get_json()['error']
        assert fake_begin == [], 'a refused rerun must not start anything'
        assert store.get_node_status('rerun1', 'n2') == NODE_DONE, 'the rows were wiped before the refusal'

    def test_a_live_run_is_refused_even_on_the_probe_path(self, client, app_module, fake_begin):
        """The records panel always sends ``resume_run_id``, but a hand-built call omits it and the
        endpoint's ``include_finished=True`` probe would otherwise pick the newest (running) row."""
        store = app_module.get_run_store()
        wf = _workflow()
        fp = workflow_fingerprint(effective_workflow(wf))
        store.start_run('live2', 'wf', fp)
        for nid in ('n1', 'n2', 'n3'):
            store.begin_node('live2', nid, 'process', fingerprint='node-' + nid)
            store.finish_node('live2', nid, NODE_DONE)

        response = client.post(
            '/api/workflow/rerun-node', json={'workflow': wf, 'workflow_name': 'wf', 'node_id': 'n2'}
        )
        assert response.status_code == 409
        assert fake_begin == []
        assert store.get_node_status('live2', 'n2') == NODE_DONE
