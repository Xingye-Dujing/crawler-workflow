"""HTTP contract for run-to-run comparison."""

import pytest
from stores import get_run_store

from services.run_store import NODE_DONE, RUN_COMPLETED

pytestmark = pytest.mark.api


def _seed(store, run_id, node_rows):
    store.start_run(run_id, 'wf', 'fp-a', node_total=len(node_rows))
    for node_id, rows in node_rows.items():
        store.begin_node(run_id, node_id, 'output', title=node_id, fingerprint=node_id)
        store.append_rows(run_id, node_id, rows)
        store.finish_node(run_id, node_id, NODE_DONE)
    store.finish_run(run_id, RUN_COMPLETED)


class TestRunCompareApi:
    def test_compare_reports_the_table_diff(self, client):
        store = get_run_store()
        _seed(store, 'r1', {'node-0': [{'id': 1, 'v': 'a'}, {'id': 2, 'v': 'b'}]})
        _seed(store, 'r2', {'node-0': [{'id': 1, 'v': 'a'}, {'id': 3, 'v': 'c'}]})
        response = client.get('/api/runs/compare?a=r1&b=r2')
        assert response.status_code == 200
        diff = response.get_json()['diff']
        assert diff['a']['run_id'] == 'r1'
        assert diff['node']['node_id'] == 'node-0'
        assert diff['diff']['added_count'] == 1
        assert diff['diff']['removed_count'] == 1

    def test_a_named_node_and_key_are_honoured(self, client):
        store = get_run_store()
        _seed(store, 'r1', {'node-0': [{'id': 1, 'v': 'a'}]})
        _seed(store, 'r2', {'node-0': [{'id': 1, 'v': 'b'}]})
        response = client.get('/api/runs/compare?a=r1&b=r2&node=node-0&key=id')
        assert response.status_code == 200
        assert response.get_json()['diff']['diff']['changed_count'] == 1

    def test_refusals_are_named(self, client):
        store = get_run_store()
        _seed(store, 'r1', {'node-0': [{'id': 1}]})
        assert client.get('/api/runs/compare?a=r1').status_code == 400
        assert client.get('/api/runs/compare?a=r1&b=r1').status_code == 400
        missing = client.get('/api/runs/compare?a=r1&b=nope')
        assert missing.status_code == 404
        assert 'nope' in missing.get_json()['error']
        bad_limit = client.get('/api/runs/compare?a=r1&b=r1&limit=x')
        assert bad_limit.status_code == 400
        node = client.get('/api/runs/compare?a=r1&b=r1&node=missing')
        assert node.status_code in (400, 404)
