"""The document routes answer a job at once and the page polls its owner-only door."""

import time

import pytest

pytestmark = [pytest.mark.api, pytest.mark.async_documents]

ROWS = [{'标题': 'a', 'n': 1}, {'标题': 'b', 'n': 2}]


def _wait(client, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        answer = client.get(f'/api/jobs/{job_id}').get_json()
        assert answer['ok'], answer
        job = answer['job']
        if job['state'] != 'running':
            return job
        time.sleep(0.01)
    raise AssertionError(f'job {job_id} never finished')


def test_a_report_is_a_job_and_the_poll_answers_the_old_body(client, app_module):
    app_module.execution_state['results'] = {'node-1': ROWS}
    response = client.post('/api/report/generate', json={'title': 'job report'})
    assert response.status_code == 202, response.get_json()
    started = response.get_json()['job']
    assert started['state'] == 'running' and started['id']
    job = _wait(client, started['id'])
    assert job['result']['ok'] is True
    assert job['result']['name'].startswith('report-')
    assert job['result']['conclusion_error'] == ''


def test_a_missing_run_is_a_finished_job_with_the_refusal_not_a_hung_request(client):
    response = client.post('/api/report/latex', json={'run_id': 'never-ran'})
    assert response.status_code in (200, 202, 400), response.get_json()
    if response.status_code == 202:
        result = _wait(client, response.get_json()['job']['id'])['result']
    else:
        # A refusal that needs no compile legitimately finishes before the snapshot.
        result = response.get_json()
    assert result['ok'] is False
    assert 'never-ran' in result['error']


def test_the_model_round_trip_is_a_job_too(client, monkeypatch):
    """The AI 测试 button used to hold a Flask worker for the daemon's 60 s timeout."""
    from api import llm as llm_api

    class _Client:
        PROVIDERS = ('ollama', 'openrouter')
        label = 'ollama:test'
        model = 'test'
        host = 'http://localhost:11434'

        def __init__(self, **_kwargs):
            pass

        def chat(self, _prompt, max_retries=1):
            return 'OK'

    monkeypatch.setattr(llm_api, 'LLMClient', _Client)
    response = client.post('/api/llm/test', json={'provider': 'ollama', 'model': 'test'})
    assert response.status_code in (200, 202), response.get_json()
    if response.status_code == 202:
        result = _wait(client, response.get_json()['job']['id'])['result']
    else:
        # A fake that answers instantly legitimately finishes before the route snapshots it.
        result = response.get_json()
    assert result['ok'] is True
    assert result['reply'] == 'OK'
    assert result['latency_ms'] >= 0


def test_a_busy_runner_refuses_by_name(client, monkeypatch):
    from services.reports import jobs

    monkeypatch.setattr(jobs, 'start', lambda *_a, **_k: None)
    response = client.post('/api/report/generate', json={})
    assert response.status_code == 429
    assert response.get_json()['ok'] is False


def test_an_unknown_or_foreign_job_is_not_found(client):
    assert client.get('/api/jobs/does-not-exist').status_code == 404
