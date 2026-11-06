"""The two routes the environment panel reads and the install job it starts.

The probe itself is exercised in ``tests/unit/components``; here the boundary is the HTTP shape:
a GET never downloads, an unknown component is a 400, and a running install is a job the panel can
poll. ``environment`` is stubbed so this case cannot touch Chrome or Ollama.
"""

from __future__ import annotations

import pytest
from api import components as components_api

from services.components import jobs


@pytest.fixture(autouse=True)
def _reset_jobs():
    jobs.reset()
    yield
    jobs.reset()


def test_environment_answers_the_matrix_without_probing_devices(client, monkeypatch):
    report = {
        'schema': 1,
        'os': 'win32',
        'root': 'C:/CaiXiHui/components',
        'capabilities': [{'id': 'core', 'label_key': 'env.capCore', 'state': 'ok', 'reason_key': 'env.coreOk'}],
        'components': [],
        'catalog': {'generated_at': '', 'components': 0},
    }
    monkeypatch.setattr(components_api, 'environment', lambda: report)
    body = client.get('/api/environment').get_json()
    assert body['ok'] is True
    assert body['capabilities'][0]['id'] == 'core'
    assert body['root'].endswith('components')


def test_the_catalogue_lists_the_domestic_defaults(client):
    body = client.get('/api/components').get_json()
    assert body['ok'] is True
    rows = {row['id']: row for row in body['components']}
    assert {'app', 'chrome', 'chromedriver', 'node', 'catbus'} <= set(rows)
    assert rows['chrome']['downloadable'] is True
    assert rows['xelatex']['downloadable'] is False, 'detection-only components are not downloaded'


def test_an_unknown_component_is_refused_before_any_download(client):
    response = client.post('/api/components/install', json={'id': 'nope'})
    assert response.status_code == 400
    body = response.get_json()
    assert body['ok'] is False and 'nope' in body['error']


def test_install_starts_a_job_and_the_job_can_be_polled(client, monkeypatch):
    monkeypatch.setattr(
        components_api.jobs,
        'start',
        lambda catalog, component_id, root: {
            'id': 'job1',
            'component': component_id,
            'state': 'running',
            'done': 0,
            'total': 10,
            'error': '',
            'path': '',
            'cancellable': True,
        },
    )
    started = client.post('/api/components/install', json={'id': 'node'}).get_json()
    assert started['ok'] is True and started['job']['id'] == 'job1'
    monkeypatch.setattr(components_api.jobs, 'get', lambda job_id: started['job'] if job_id == 'job1' else None)
    polled = client.get('/api/components/jobs/job1').get_json()
    assert polled['job']['state'] == 'running'
    assert client.get('/api/components/jobs/missing').status_code == 404


def test_the_application_itself_cannot_be_removed_from_the_panel(client):
    response = client.post('/api/components/remove', json={'id': 'app'})
    assert response.status_code == 400
    assert response.get_json()['ok'] is False
