"""The update routes answer the panel without touching the network in a source run."""

from __future__ import annotations

import sys


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


def test_an_unknown_job_is_not_a_green_answer(client):
    response = client.get('/api/update/job/not-a-job')
    assert response.status_code == 404
    assert response.get_json()['ok'] is False
