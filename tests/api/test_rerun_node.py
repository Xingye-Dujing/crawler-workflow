"""Single-node rerun (feature 12): wipe one node's subtree, then resume the SAME run so the
engine re-executes exactly that subtree and reuses every kept upstream row.

The real engine is never run here — ``_begin_run`` is monkeypatched — so these tests pin the
endpoint's OWN logic: the downstream closure, the row invalidation against the store, the
delegate-with-``resume_run_id`` hand-off, and the named refusals."""

import pytest

pytestmark = pytest.mark.api


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
    fp = fingerprint or app_module.workflow_fingerprint(app_module.effective_workflow(wf))
    store.start_run(run_id, 'wf', fp)
    for nid in node_ids:
        store.begin_node(run_id, nid, 'process', fingerprint='node-' + nid)
        store.finish_node(run_id, nid, app_module.NODE_DONE)
    store.finish_run(run_id, app_module.RUN_COMPLETED)
    return fp


@pytest.fixture
def fake_begin(monkeypatch):
    """Replace the real start path with a recorder, so nothing runs while we observe the hand-off."""
    import app as app_module

    calls = []

    def _fake(data, lang):
        calls.append((data, lang))
        return {'status': 200, 'body': {'ok': True, 'run_id': data.get('resume_run_id') or 'new'}}

    monkeypatch.setattr(app_module, '_begin_run', _fake)
    return calls


class TestInvalidateNodes:
    def test_a_cleared_node_loses_its_status_and_rows(self, client, app_module):
        store = app_module.get_run_store()
        _seed_completed_run(store, app_module)
        assert store.get_node_status('rerun1', 'n2') == app_module.NODE_DONE
        cleared = store.invalidate_nodes('rerun1', ['n2', 'n3'])
        assert cleared == 2
        assert store.get_node_status('rerun1', 'n2') is None
        assert store.get_node_status('rerun1', 'n3') is None
        # Upstream kept: the whole point is that only the target subtree is re-run.
        assert store.get_node_status('rerun1', 'n1') == app_module.NODE_DONE

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
        assert store.get_node_status('rerun1', 'n2') is None
        assert store.get_node_status('rerun1', 'n1') == app_module.NODE_DONE
        # Delegation went through the ordinary start path AS a resume of that same run.
        assert len(fake_begin) == 1
        sent_data, _lang = fake_begin[0]
        assert sent_data['resume_run_id'] == 'rerun1'
        assert sent_data['node_id'] == 'n2'

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
