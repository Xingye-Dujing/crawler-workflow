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
def ran_setup(client, app_module):
    """One finished run of a real bibliometrics node, plus the exact canvas that produced it.

    Function-scoped because the isolated ``client`` is: a module-scoped run would be read
    through a data root that has since been torn down. The canvas travels with it because a
    capture can only verify its parameters against the file that actually ran — saving a
    look-alike canvas would prove the guard fires, not that it passes.
    """
    import time

    dataset_id = _upload(client, 'biblio_cnki_demo.txt')
    canvas = _canvas(dataset_id)
    started = client.post(
        '/api/workflow/execute',
        json={'workflow': canvas, 'workflow_name': 'biblio-workspace'},
    )
    assert started.status_code == 200, started.get_json()
    run_id = started.get_json()['run_id']
    deadline = time.time() + 60
    while time.time() < deadline and app_module.execution_state.get('running'):
        time.sleep(0.1)
    assert not app_module.execution_state.get('running'), 'the run did not finish'
    return {'run_id': run_id, 'canvas': canvas}


@pytest.fixture
def ran(ran_setup):
    return ran_setup['run_id']


@pytest.fixture
def ran_canvas(ran_setup):
    return ran_setup['canvas']


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


def _project(client, name: str = '数字治理') -> str:
    created = client.post('/api/biblio/project', json={'name': name, 'note': '跟踪五年'}).get_json()
    assert created['ok'] is True, created
    return created['project']['project_id']


class TestProjects:
    def test_a_named_project_round_trips_with_its_note(self, client):
        project_id = _project(client)
        listed = client.get('/api/biblio/projects').get_json()['projects']
        mine = next(p for p in listed if p['project_id'] == project_id)
        assert mine['name'] == '数字治理' and mine['note'] == '跟踪五年'
        assert mine['snapshots'] == []

    def test_an_untitled_project_is_refused_rather_than_stored(self, client):
        response = client.post('/api/biblio/project', json={'name': '   '})
        assert response.status_code == 400
        assert response.get_json()['ok'] is False

    def test_renaming_something_that_is_not_there_names_it(self, client):
        response = client.post('/api/biblio/project/rename', json={'project_id': 'nope', 'name': 'X'})
        assert response.status_code == 404
        assert 'nope' in response.get_json()['error']

    def test_deleting_a_project_takes_its_captures_with_it(self, client, ran):
        project_id = _project(client)
        captured = client.post(
            '/api/biblio/snapshot', json={'project_id': project_id, 'run_id': ran, 'node_id': 'node-2'}
        )
        assert captured.get_json()['ok'] is True
        listed = next(
            p for p in client.get('/api/biblio/projects').get_json()['projects'] if p['project_id'] == project_id
        )
        assert len(listed['snapshots']) == 1
        gone = client.post('/api/biblio/project/delete', json={'project_id': project_id}).get_json()
        assert gone['ok'] is True and gone['removed_snapshots'] == 1
        assert all(p['project_id'] != project_id for p in client.get('/api/biblio/projects').get_json()['projects'])


class TestCapturing:
    def test_a_capture_holds_the_whole_table_not_one_page(self, client, ran):
        project_id = _project(client)
        table = client.get(f'/api/biblio/table?run_id={ran}&node_id=node-2').get_json()
        body = client.post(
            '/api/biblio/snapshot',
            json={'project_id': project_id, 'run_id': ran, 'node_id': 'node-2', 'label': '基线'},
        ).get_json()
        assert body['ok'] is True, body
        snapshot = body['snapshot']
        assert snapshot['label'] == '基线'
        assert snapshot['node_count'] == table['total'], 'a prefix of a table is not a capture of it'
        assert snapshot['shape'] == 'nodes'
        assert snapshot['run_id'] == ran and snapshot['node_id'] == 'node-2'

    def test_parameters_are_only_filed_when_they_are_provably_the_ones_that_ran(self, client, ran):
        """The canvas this run came from was POSTed and never saved, so the server cannot show
        that any stored settings produced these rows — the capture says so instead of inventing
        provenance."""
        project_id = _project(client)
        snapshot = client.post(
            '/api/biblio/snapshot', json={'project_id': project_id, 'run_id': ran, 'node_id': 'node-2'}
        ).get_json()['snapshot']
        assert snapshot['params_verified'] == 0

    def test_a_saved_canvas_lets_the_capture_carry_verified_parameters(self, client, ran, ran_canvas):
        """The guard passes for the canvas that actually ran: same nodes, same dataset id, so the
        recomputed fingerprint equals the one the run recorded."""
        project_id = _project(client, '已存画布')
        saved = client.post('/api/workflow/save', json={'name': 'biblio-workspace', 'workflow': ran_canvas})
        assert saved.status_code == 200, saved.get_json()
        body = client.post(
            '/api/biblio/snapshot', json={'project_id': project_id, 'run_id': ran, 'node_id': 'node-2'}
        ).get_json()
        assert body['ok'] is True, body
        detail = client.get(f'/api/biblio/snapshots/{body["snapshot"]["snapshot_id"]}').get_json()
        assert detail['snapshot']['params_verified'] == 1
        assert detail['params']['entity_type'] == 'keyword'
        assert detail['node_total'] == detail['snapshot']['node_count']

    def test_capturing_into_a_missing_project_names_it(self, client, ran):
        response = client.post('/api/biblio/snapshot', json={'project_id': 'nope', 'run_id': ran, 'node_id': 'node-2'})
        assert response.status_code == 404
        assert 'nope' in response.get_json()['error']

    def test_capturing_a_non_bibliometrics_node_is_refused_by_name(self, client, ran):
        project_id = _project(client)
        response = client.post(
            '/api/biblio/snapshot', json={'project_id': project_id, 'run_id': ran, 'node_id': 'node-1'}
        )
        assert response.status_code == 400
        assert 'node-1' in response.get_json()['error']


class TestComparing:
    @pytest.fixture
    def two(self, client, ran):
        project_id = _project(client, '对比用')
        ids = []
        for label in ('A', 'B'):
            captured = client.post(
                '/api/biblio/snapshot',
                json={'project_id': project_id, 'run_id': ran, 'node_id': 'node-2', 'label': label},
            ).get_json()
            assert captured['ok'] is True, captured
            ids.append(captured['snapshot']['snapshot_id'])
        return ids

    def test_two_captures_of_the_same_rows_differ_in_nothing(self, client, two):
        diff = client.get(f'/api/biblio/compare?a={two[0]}&b={two[1]}').get_json()['diff']
        assert diff['nodes']['added']['total'] == 0
        assert diff['nodes']['removed']['total'] == 0
        assert diff['nodes']['changed']['total'] == 0
        assert diff['params_differ']['total'] == 0
        assert diff['a']['label'] == 'A' and diff['b']['label'] == 'B'
        assert diff['same_project'] is True

    def test_comparing_one_capture_with_itself_is_refused(self, client, two):
        assert client.get(f'/api/biblio/compare?a={two[0]}&b={two[0]}').status_code == 400
        assert client.get(f'/api/biblio/compare?a={two[0]}').status_code == 400

    def test_a_missing_capture_in_a_comparison_is_named(self, client, two):
        response = client.get(f'/api/biblio/compare?a={two[0]}&b=nope')
        assert response.status_code == 404
        assert 'nope' in response.get_json()['error']

    def test_deleting_one_capture_leaves_the_other_intact(self, client, two):
        assert client.post('/api/biblio/snapshot/delete', json={'snapshot_id': two[1]}).get_json()['ok'] is True
        assert client.get(f'/api/biblio/snapshots/{two[1]}').status_code == 404
        assert client.get(f'/api/biblio/snapshots/{two[0]}').get_json()['ok'] is True
