"""The update routes answer the panel without touching the network in a source run.

What each route owes: a named refusal instead of a silent no-op, and a permission that is the
server's (the panel hiding the card is cosmetic). The download is a separate process now, so it is
the restart — not the download — that has to wait for a crawl.
"""

from __future__ import annotations

import sys

import pytest
from api import update as update_api

from i18n import t
from services import update, update_job


def test_a_source_run_offers_no_update(client, monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    body = client.get('/api/update/check').get_json()
    assert body['ok'] is True
    assert body['supported'] is False
    assert body.get('update_available') is not True


def test_downloading_from_source_is_refused_by_name(client, monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    response = client.post('/api/update/download')
    body = response.get_json()
    assert response.status_code == 400
    assert body['ok'] is False
    assert '源码' in body['error']


def test_an_empty_status_answers_idle_rather_than_missing(client, monkeypatch):
    """A page that reloads mid-download reattaches; with no job it gets a state, not a 404."""
    monkeypatch.setattr(update, 'status', lambda: {'state': 'idle', 'version': '', 'progress': 0})
    response = client.get('/api/update/status')
    body = response.get_json()
    assert response.status_code == 200
    assert body['ok'] is True
    assert body['job']['state'] == 'idle'
    assert 'log' in body


def test_a_restart_without_a_staged_package_is_refused_by_name(client, monkeypatch):
    monkeypatch.setattr(update, 'request_restart', lambda: {'ok': False, 'error': '更新包还没有下载完成'})
    response = client.post('/api/update/restart')
    body = response.get_json()
    assert response.status_code == 400
    assert '下载' in body['error']


def test_a_restart_waits_for_the_crawl_but_a_download_does_not(client, monkeypatch):
    """The download runs in its own process; only replacing the program needs the console quiet."""
    monkeypatch.setattr(update, 'prepare', lambda: {'ok': True, 'job': {'state': 'downloading'}})
    monkeypatch.setattr(update, 'request_restart', lambda: {'ok': True, 'restarting': True})
    monkeypatch.setitem(update_api.execution_state, 'running', True)
    try:
        download = client.post('/api/update/download')
        assert download.status_code == 200
        assert download.get_json()['ok'] is True
        restart = client.post('/api/update/restart')
        assert restart.status_code == 409
        assert restart.get_json()['error'] == t('api.updateRunning')
    finally:
        monkeypatch.setitem(update_api.execution_state, 'running', False)


def test_another_account_may_not_replace_the_program(client, monkeypatch):
    """Hiding the card is cosmetic; the 403 is the permission."""
    monkeypatch.setattr(update_api, 'accounts_mode', lambda: True)
    monkeypatch.setattr(update_api, 'is_admin', lambda: False)
    for method, path in (
        ('get', '/api/update/check'),
        ('post', '/api/update/download'),
        ('get', '/api/update/status'),
        ('post', '/api/update/restart'),
        ('post', '/api/update/cancel'),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 403, path
        assert response.get_json()['ok'] is False


def test_cancelling_without_a_job_is_refused_by_name(client, monkeypatch):
    monkeypatch.setattr(update, 'cancel', lambda: {'ok': False, 'error': '现在没有可以取消的更新'})
    response = client.post('/api/update/cancel')
    assert response.status_code == 400
    assert '取消' in response.get_json()['error']


def test_the_status_route_never_ships_a_server_path(client, monkeypatch, tmp_path):
    monkeypatch.setattr(update_job, 'data_dir', lambda root=None: tmp_path / 'data')
    (tmp_path / 'data' / 'updates').mkdir(parents=True)
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(state=update_job.STATE_STAGED, staged=str(tmp_path / 'data' / 'updates' / '2026.11.12.1'))
    monkeypatch.setattr(update, 'status', update_job_public)
    body = client.get('/api/update/status').get_json()
    assert str(tmp_path) not in str(body['job'])


def update_job_public():
    return update_job.public()


@pytest.mark.parametrize('value', [0, 55, 100])
def test_progress_travels_as_a_number(client, monkeypatch, value):
    monkeypatch.setattr(update, 'status', lambda: {'state': 'downloading', 'version': '1', 'progress': value})
    body = client.get('/api/update/status').get_json()
    assert body['job']['progress'] == value
