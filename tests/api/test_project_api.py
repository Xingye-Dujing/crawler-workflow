"""HTTP contract for project bundle export and import."""

import io
import json
import zipfile

import pandas as pd
import pytest
from core.config import Config
from stores import get_dataset_store

from services import reusable_store
from services.workflow_manager import WorkflowManager

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def isolated_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'REUSABLE_DIR', str(tmp_path / 'reusable_nodes'))


def _workflow(dataset_id, template_id):
    return {
        'nodes': [
            {
                'id': 'node-0',
                'type': 'upload',
                'params': {'dataset_id': dataset_id, 'dataset_name': 'raw.csv', 'row_count': 2},
                'x': 0,
                'y': 0,
            },
            {
                'id': 'node-1',
                'type': 'reusable',
                'params': {
                    'template_id': template_id,
                    'template_name': '清洗模板',
                    'template': {'nodes': [], 'connections': [], 'inputs': [], 'outputs': []},
                },
                'x': 200,
                'y': 0,
            },
        ],
        'connections': [{'from': 'node-0', 'to': 'node-1'}],
    }


def _seed(client):
    dataset = get_dataset_store().put(pd.DataFrame([{'标题': 'a'}, {'标题': 'b'}]), name='raw.csv', source='upload')
    template = reusable_store.save_template(
        {
            'name': '清洗模板',
            'description': '',
            'nodes': [
                {'id': 'a', 'type': 'process', 'title': '清洗', 'params': {'operation': 'clean'}, 'x': 0, 'y': 0},
            ],
            'connections': [],
            'inputs': ['a'],
            'outputs': ['a'],
        }
    )
    saved = client.post(
        '/api/workflow/save', json={'name': '项目A', 'workflow': _workflow(dataset['dataset_id'], template['id'])}
    )
    assert saved.status_code == 200
    return dataset, template


class TestProjectApi:
    def test_export_returns_a_zip_with_the_current_workflow(self, client):
        dataset, template = _seed(client)
        response = client.get('/api/project/export?workflow=项目A')
        assert response.status_code == 200
        assert response.mimetype == 'application/zip'
        assert response.headers.get('X-Project-Warnings') == '0'
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            assert manifest['workflows'][0]['name'] == '项目A'
            assert manifest['datasets'][0]['id'] == dataset['dataset_id']
            assert manifest['templates'][0]['id'] == template['id']
            assert 'attachment' in response.headers.get('Content-Disposition', '')

    def test_export_all_without_a_current_file(self, client, tmp_path, monkeypatch):
        # The suite shares one workflow directory across tests (and old fixtures may
        # reference deleted datasets, which "all" must refuse by name). Point this
        # case at its own directory so the assertion is about the endpoint, not
        # about whatever another test left behind.
        monkeypatch.setattr(Config, 'WORKFLOW_DIR', str(tmp_path / 'workflows'))
        dataset = get_dataset_store().put(pd.DataFrame([{'标题': 'a'}]), name='raw.csv', source='upload')
        template = reusable_store.save_template(
            {
                'name': '清洗模板',
                'description': '',
                'nodes': [{'id': 'a', 'type': 'process', 'title': '清洗', 'params': {}, 'x': 0, 'y': 0}],
                'connections': [],
                'inputs': ['a'],
                'outputs': ['a'],
            }
        )
        WorkflowManager().save('项目A', _workflow(dataset['dataset_id'], template['id']))
        response = client.get('/api/project/export?all=1')
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            assert [row['name'] for row in manifest['workflows']] == ['项目A']

    def test_import_round_trip_renames_on_collision(self, client):
        _seed(client)
        exported = client.get('/api/project/export?workflow=项目A')
        response = client.post(
            '/api/project/import',
            data={'file': (io.BytesIO(exported.data), 'project.zip')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 200
        summary = response.get_json()['summary']
        assert summary['workflows'] == [{'from': '项目A', 'to': '项目A (2)'}]
        assert summary['templates'][0]['name'] == '清洗模板 (2)'
        names = [row['name'] for row in client.get('/api/workflow/list').get_json()['workflows']]
        assert '项目A (2)' in names

    def test_refusals_are_named(self, client):
        missing = client.get('/api/project/export?workflow=不存在')
        assert missing.status_code == 400
        assert '不存在' in missing.get_json()['error']
        empty = client.get('/api/project/export')
        assert empty.status_code == 400
        assert empty.get_json()['error']
        no_file = client.post('/api/project/import', data={}, content_type='multipart/form-data')
        assert no_file.status_code == 400
        assert no_file.get_json()['error']
        bad = client.post(
            '/api/project/import',
            data={'file': (io.BytesIO(b'not a zip'), 'bad.zip')},
            content_type='multipart/form-data',
        )
        assert bad.status_code == 400
        assert bad.get_json()['error']

    def test_the_bundle_does_not_contain_runtime_state(self, client):
        _seed(client)
        response = client.get('/api/project/export?workflow=项目A')
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            names = set(archive.namelist())
        assert not [name for name in names if name.startswith(('data/', 'logs/', 'cookies/', 'exports/'))]
        assert all(name.endswith('.json') for name in names)
