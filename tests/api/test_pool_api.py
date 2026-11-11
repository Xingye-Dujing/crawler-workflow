"""``/api/pool/*``: what the panel may know, and the four levers it may pull.

The one hard rule is here as a test: the exit inventory answers with a NAME and an address,
never the credential. Everything else is the same envelope the panel already parses.
"""

import pytest
from runtime.state import cookie_manager

from services.pool import store

pytestmark = [pytest.mark.api, pytest.mark.serial]


@pytest.fixture(autouse=True)
def clean_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'db_path', lambda: str(tmp_path / 'pool.db'))
    yield


def _save_cookie(account='work', platform='weibo'):
    cookie_manager.save(platform, [{'name': 'SUB', 'value': account, 'domain': '.weibo.com'}], account)


def test_state_lists_saved_logins_and_exits_without_secrets(client):
    _save_cookie('work')
    saved = client.post(
        '/api/pool/exit/save',
        json={'name': 'hk03', 'host': '10.0.0.1', 'port': 8080, 'username': 'u', 'password': 'p'},
    ).get_json()
    assert saved['ok'] is True
    assert 'password' not in saved['exit']

    body = client.get('/api/pool/state').get_json()
    assert body['ok'] is True
    row = [r for r in body['accounts'] if r['platform'] == 'weibo' and r['account'] == 'work'][0]
    assert row['state'] == 'ok'
    assert row['exit_id'] == ''
    exit_row = body['exits'][0]
    assert exit_row['name'] == 'hk03'
    assert exit_row['has_auth'] is True
    assert 'password' not in exit_row and 'username' not in exit_row
    assert 'cool_until_local' in row


def test_an_account_is_frozen_by_the_run_and_unfrozen_by_the_human(client):
    _save_cookie('work')
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    frozen = client.get('/api/pool/state').get_json()['accounts'][0]
    assert frozen['state'] == 'cooling' and frozen['cool_until_local']

    answer = client.post('/api/pool/account/reset', json={'platform': 'weibo', 'account': 'work'}).get_json()
    assert answer['ok'] is True and answer['count'] == 1
    assert client.get('/api/pool/state').get_json()['accounts'][0]['state'] == 'ok'


def test_disable_is_a_manual_stop_that_a_clock_cannot_lift(client):
    _save_cookie('work')
    assert client.post(
        '/api/pool/account/disable', json={'platform': 'weibo', 'account': 'work', 'disabled': True}
    ).get_json()['ok']
    assert client.get('/api/pool/state').get_json()['accounts'][0]['state'] == 'disabled'
    assert client.post(
        '/api/pool/account/disable', json={'platform': 'weibo', 'account': 'work', 'disabled': False}
    ).get_json()['ok']
    assert client.get('/api/pool/state').get_json()['accounts'][0]['state'] == 'ok'


def test_an_exit_round_trip_binds_and_deletes(client):
    _save_cookie('work')
    exit_row = client.post('/api/pool/exit/save', json={'name': 'sg01', 'host': '10.0.0.2', 'port': 8080}).get_json()[
        'exit'
    ]
    bound = client.post(
        '/api/pool/bind',
        json={'platform': 'weibo', 'account': 'work', 'exit_id': exit_row['id']},
    ).get_json()
    assert bound['ok'] is True
    assert client.get('/api/pool/state').get_json()['accounts'][0]['exit_id'] == exit_row['id']

    assert client.post('/api/pool/exit/delete', json={'id': exit_row['id']}).get_json()['ok'] is True
    # Deleting the exit releases the binding rather than leaving a login pointing at nothing.
    assert client.get('/api/pool/state').get_json()['accounts'][0]['exit_id'] == ''
    missing = client.post('/api/pool/exit/delete', json={'id': 'nope'})
    assert missing.status_code == 404


def test_a_malformed_proxy_is_refused_by_name(client):
    answer = client.post('/api/pool/exit/save', json={'host': '10.0.0.1', 'port': 'not-a-port'})
    assert answer.status_code == 400
    assert answer.get_json()['ok'] is False
    assert answer.get_json()['error']


def test_bulk_import_keeps_the_good_lines_and_counts_the_bad_one(client):
    body = client.post(
        '/api/pool/exit/import',
        json={'text': 'hk03 10.0.0.1:8080\nbroken-line\nsg01 10.0.0.2:8080 u p'},
    ).get_json()
    assert body['ok'] is True
    assert body['saved'] == 2 and body['skipped'] == 1
    names = {row['name'] for row in client.get('/api/pool/state').get_json()['exits']}
    assert names == {'hk03', 'sg01'}
