"""HTTP contract for project bundle export and import."""

import io
import json
import time
import zipfile

import pandas as pd
import pytest
from core.config import Config
from runtime.stores import get_dataset_store

from services.workflows import reusable
from services.workflows.manager import WorkflowManager

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


def _wait(client, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        answer = client.get(f'/api/jobs/{job_id}').get_json()
        assert answer['ok'], answer
        job = answer['job']
        if job['state'] != 'running':
            return job
        time.sleep(0.01)
    raise AssertionError(f'job {job_id} never finished')


def _seed(client):
    dataset = get_dataset_store().put(pd.DataFrame([{'标题': 'a'}, {'标题': 'b'}]), name='raw.csv', source='upload')
    template = reusable.save_template(
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
        template = reusable.save_template(
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
        """The POST parks a job (202); its result is the summary the synchronous route returned.

        ``tests/api/conftest`` runs ``jobs.start`` inline (``run_now``), so the job is already
        finished here; the real 202/poll path is pinned in ``test_document_jobs_api.py``.
        """
        _seed(client)
        exported = client.get('/api/project/export?workflow=项目A')
        response = client.post(
            '/api/project/import',
            data={'file': (io.BytesIO(exported.data), 'project.zip')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 202
        job = response.get_json()['job']
        assert job['state'] == 'done'
        summary = job['result']['summary']
        assert summary['workflows'] == [{'from': '项目A', 'to': '项目A (2)'}]
        assert summary['templates'][0]['name'] == '清洗模板 (2)'
        names = [row['name'] for row in client.get('/api/workflow/list').get_json()['workflows']]
        assert '项目A (2)' in names

    @pytest.mark.async_documents
    def test_the_import_runs_off_the_request_thread_and_is_polled(self, client):
        """The real runner: POST answers 202 at once, the worker writes, the poll returns the summary."""
        _seed(client)
        exported = client.get('/api/project/export?workflow=项目A')
        response = client.post(
            '/api/project/import',
            data={'file': (io.BytesIO(exported.data), 'project.zip')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 202, response.get_json()
        started = response.get_json()['job']
        assert started['state'] == 'running' and started['id']
        job = _wait(client, started['id'])
        assert job['result']['ok'] is True
        imported = job['result']['summary']['workflows'][0]['to']
        assert imported.startswith('项目A (') and imported != '项目A'

    def test_a_busy_registry_refuses_the_upload_by_name(self, client, monkeypatch):
        """A refused upload must not leave its temp file behind (the job never starts to delete it)."""
        from services.reports import jobs

        monkeypatch.setattr(jobs, 'start', lambda *_a, **_k: None)
        response = client.post(
            '/api/project/import',
            data={'file': (io.BytesIO(b'PK'), 'project.zip')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 409
        assert response.get_json()['ok'] is False

    def test_a_broken_bundle_fails_its_job_by_name(self, client):
        bad = client.post(
            '/api/project/import',
            data={'file': (io.BytesIO(b'not a zip'), 'bad.zip')},
            content_type='multipart/form-data',
        )
        assert bad.status_code == 202
        result = bad.get_json()['job']['result']
        assert result['ok'] is False and result['error']

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

    def test_the_bundle_does_not_contain_runtime_state(self, client):
        _seed(client)
        response = client.get('/api/project/export?workflow=项目A')
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            names = set(archive.namelist())
        assert not [name for name in names if name.startswith(('data/', 'logs/', 'cookies/', 'exports/'))]
        assert all(name.endswith('.json') for name in names)
