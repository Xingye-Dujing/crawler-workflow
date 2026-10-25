"""HTTP contract for reusable-node templates: list, read, save, delete."""

import pytest

from config import Config

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def isolated_reusable_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'REUSABLE_DIR', str(tmp_path / 'reusable_nodes'))


FRAGMENT = {
    'name': '清洗流水线',
    'description': '',
    'nodes': [
        {
            'id': 'n1',
            'type': 'process',
            'title': '清洗',
            'params': {'operation': 'clean'},
            'x': 0,
            'y': 0,
            'w': 200,
            'h': 80,
        },
        {
            'id': 'n2',
            'type': 'analysis',
            'title': '去空',
            'params': {'operation': 'drop_null'},
            'x': 240,
            'y': 0,
            'w': 200,
            'h': 80,
        },
    ],
    'connections': [{'from': 'n1', 'to': 'n2'}],
    'inputs': ['n1'],
    'outputs': ['n2'],
}


class TestReusableApi:
    def test_save_list_get_and_delete(self, client):
        saved = client.post('/api/reusable/save', json=FRAGMENT)
        assert saved.status_code == 200
        template = saved.get_json()['template']
        assert template['id'].startswith('r-')
        assert template['name'] == '清洗流水线'

        listed = client.get('/api/reusable').get_json()
        assert listed['ok'] is True
        assert listed['templates'][0]['id'] == template['id']
        assert listed['templates'][0]['nodes'] == 2

        full = client.get('/api/reusable/get?id=' + template['id']).get_json()
        assert full['ok'] is True
        assert full['template']['nodes'][1]['params']['operation'] == 'drop_null'

        deleted = client.post('/api/reusable/delete', json={'id': template['id']}).get_json()
        assert deleted == {'ok': True, 'deleted': True}
        assert client.get('/api/reusable').get_json()['templates'] == []

    def test_a_bad_fragment_is_a_400_with_the_reason(self, client):
        body = dict(FRAGMENT)
        body['nodes'] = [{'id': 'n1', 'type': 'source'}]
        response = client.post('/api/reusable/save', json=body)
        assert response.status_code == 400
        assert 'source' in response.get_json()['error']

    def test_a_missing_template_is_a_named_404(self, client):
        response = client.get('/api/reusable/get?id=r-000000000000')
        assert response.status_code == 404
        assert 'r-000000000000' in response.get_json()['error']

    def test_a_duplicate_name_is_a_400(self, client):
        assert client.post('/api/reusable/save', json=FRAGMENT).status_code == 200
        response = client.post('/api/reusable/save', json=FRAGMENT)
        assert response.status_code == 400
        assert '清洗流水线' in response.get_json()['error']

    def test_delete_is_idempotent(self, client):
        template = client.post('/api/reusable/save', json=FRAGMENT).get_json()['template']
        assert client.post('/api/reusable/delete', json={'id': template['id']}).get_json()['deleted'] is True
        assert client.post('/api/reusable/delete', json={'id': template['id']}).get_json()['deleted'] is False

    def test_id_and_name_types_are_checked(self, client):
        for body in (
            {'id': 3, 'name': 'x'},
            {'name': 3},
            {'name': 'x', 'nodes': [], 'inputs': 'x'},
            {'id': 'bad', 'name': 'x'},
        ):
            response = client.post('/api/reusable/save', json=body)
            assert response.status_code == 400, body
        for body in ({'id': 3}, {}):
            response = client.post('/api/reusable/delete', json=body)
            assert response.status_code == 400, body


class TestAReusableGroupAtTheRunDoor:
    def test_an_unwired_group_is_refused_by_name_before_a_run_is_claimed(self, client):
        group = {
            'id': 'g1',
            'type': 'reusable',
            'title': '测试组',
            'params': {
                'template_name': '测试组',
                'template': {
                    'nodes': [
                        {'id': 'a', 'type': 'process', 'params': {}},
                        {'id': 'b', 'type': 'analysis', 'params': {'operation': 'drop_null'}},
                    ],
                    'connections': [{'from': 'a', 'to': 'b'}],
                    'inputs': ['a'],
                    'outputs': ['b'],
                },
            },
        }
        response = client.post(
            '/api/workflow/execute',
            json={'workflow': {'nodes': [group], 'connections': [], 'settings': {}}, 'workflow_name': 'wf'},
        )
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False
        assert '测试组' in body['error'], body
        assert client.get('/api/runs/list').get_json().get('runs', []) == []
