"""The Bibliometrics Workspace's read side: /api/biblio/runs and /api/biblio/table.

Both routes answer from the DURABLE ledger, so the cases run a real canvas first and then read
what the run left behind — including after asking for a page of it. A refusal has to name the
run or node it could not find: a panel that showed an empty table for a wrong id would read as
"that run produced nothing".
"""

import io
from pathlib import Path

import pytest

pytestmark = pytest.mark.api

SAMPLES = Path(__file__).resolve().parents[2] / 'samples'


def _upload(client, name: str) -> str:
    response = client.post(
        '/api/data/upload',
        data={'file': (io.BytesIO((SAMPLES / name).read_bytes()), name)},
        content_type='multipart/form-data',
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()['dataset_id']


def _canvas(dataset_id: str) -> dict:
    """Upload → bibliometrics (keywords, clustered) → nothing: the panel reads the node table."""
    return {
        'nodes': [
            {
                'id': 'node-1',
                'type': 'upload',
                'title': '上传文献',
                'params': {'dataset_id': dataset_id, 'dataset_name': 'cnki.txt', 'row_count': 36},
                'x': 0,
                'y': 0,
            },
            {
                'id': 'node-2',
                'type': 'biblio',
                'title': '关键词图谱',
                'params': {
                    'entity_type': 'keyword',
                    'slice_years': 2,
                    'selection': 'top_n',
                    'top_n': 50,
                    'link_measure': 'cosine',
                    'pruning': 'none',
                    'cluster': True,
                    'burst': False,
                    'output_shape': 'nodes',
                    'export_files': True,
                },
                'x': 240,
                'y': 0,
            },
        ],
        'connections': [{'from': 'node-1', 'to': 'node-2'}],
        'settings': {'mode': 'serial', 'headless': True, 'max_workers': 1},
    }


@pytest.fixture
def ran(client, app_module):
    """One finished run of a real bibliometrics node.

    Function-scoped because the isolated ``client`` is: a module-scoped run would be read
    through a data root that has since been torn down.
    """
    import time

    dataset_id = _upload(client, 'biblio_cnki_demo.txt')
    started = client.post(
        '/api/workflow/execute',
        json={'workflow': _canvas(dataset_id), 'workflow_name': 'biblio-workspace'},
    )
    assert started.status_code == 200, started.get_json()
    run_id = started.get_json()['run_id']
    deadline = time.time() + 60
    while time.time() < deadline and app_module.execution_state.get('running'):
        time.sleep(0.1)
    assert not app_module.execution_state.get('running'), 'the run did not finish'
    return run_id


class TestRunsList:
    def test_a_run_with_a_biblio_node_is_listed_with_its_node(self, client, ran):
        body = client.get('/api/biblio/runs').get_json()
        assert body['ok'] is True
        run = next((r for r in body['runs'] if r['run_id'] == ran), None)
        assert run is not None, 'a finished bibliometrics run must be findable after a restart'
        node = next((n for n in run['nodes'] if n['node_id'] == 'node-2'), None)
        assert node is not None
        assert node['title'] == '关键词图谱'
        assert node['row_count'] > 0
        # The node wrote GraphML/GML/JSON/CSV; the panel offers them for download.
        assert {entry['kind'] for entry in node['files']} >= {'biblio_graphml', 'biblio_nodes'}

    def test_the_upload_node_is_not_a_biblio_node(self, client, ran):
        body = client.get('/api/biblio/runs').get_json()
        run = next(r for r in body['runs'] if r['run_id'] == ran)
        assert 'node-1' not in {n['node_id'] for n in run['nodes']}


class TestTableRead:
    def test_the_stored_table_comes_back_with_its_shape(self, client, ran):
        body = client.get(f'/api/biblio/table?run_id={ran}&node_id=node-2').get_json()
        assert body['ok'] is True
        assert body['shape'] == 'nodes'
        assert '节点' in body['columns'] and '连接' in body['columns']
        assert body['total'] == len(body['rows'])
        assert {row['节点'] for row in body['rows']}

    def test_a_page_is_a_page_and_the_total_stays_the_whole_table(self, client, ran):
        first = client.get(f'/api/biblio/table?run_id={ran}&node_id=node-2&limit=3').get_json()
        assert len(first['rows']) == 3
        assert first['total'] > 3, 'the sample data must be deep enough for this to prove paging'
        second = client.get(f'/api/biblio/table?run_id={ran}&node_id=node-2&limit=3&offset=3').get_json()
        assert {row['节点'] for row in first['rows']}.isdisjoint({row['节点'] for row in second['rows']})
        assert second['total'] == first['total']

    def test_a_nonsense_page_size_is_a_smaller_view_not_a_crash(self, client, ran):
        body = client.get(f'/api/biblio/table?run_id={ran}&node_id=node-2&limit=abc').get_json()
        assert body['ok'] is True and len(body['rows']) <= 200


class TestRefusals:
    def test_an_unknown_run_is_refused_by_id(self, client):
        response = client.get('/api/biblio/table?run_id=nope&node_id=node-2')
        assert response.status_code == 404
        assert 'nope' in response.get_json()['error']

    def test_a_node_the_run_never_had_is_refused_by_id(self, client, ran):
        response = client.get(f'/api/biblio/table?run_id={ran}&node_id=node-99')
        assert response.status_code == 404
        assert 'node-99' in response.get_json()['error']

    def test_a_node_that_is_not_bibliometrics_is_refused_by_name(self, client, ran):
        response = client.get(f'/api/biblio/table?run_id={ran}&node_id=node-1')
        assert response.status_code == 400
        assert 'node-1' in response.get_json()['error']

    def test_a_node_whose_rows_were_cleared_says_so_instead_of_painting_nothing(self, client, app_module, ran):
        """Reaching "record there, rows gone" the way the store itself does it: a node whose own
        fingerprint changed drops its rows (they describe a different node) and keeps its record."""
        store = app_module.get_run_store()
        assert store.begin_node(ran, 'node-2', 'biblio', '关键词图谱', 'a-different-shape') is True
        body = client.get(f'/api/biblio/table?run_id={ran}&node_id=node-2').get_json()
        assert body['ok'] is True
        assert body['rows'] == [] and body['total'] == 0
        assert 'node-2' in body['note'], 'an empty table has to name the node that is empty'
        assert body['shape'] == '', 'no columns means no claim about the shape'
