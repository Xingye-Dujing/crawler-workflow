"""The account-management API: admin-only operations, no credential leakage, isolated data."""

import os
import re

import pytest
from core.config import Config
from runtime.state import execution_state

from services.accounts import service as accounts_service

pytestmark = pytest.mark.api

PASSWORD = 'correct horse battery'
NEW_PASSWORD = 'another good password'


@pytest.fixture
def admin_client(client, monkeypatch):
    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(Config, 'ADMIN_USER', 'admin')
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', PASSWORD)
    accounts_service.reset_service()
    accounts_service.reset_throttle()
    accounts_service.get_account_service().bootstrap()
    _login(client, 'admin', PASSWORD)
    return client


def _login(client, user, password=PASSWORD):
    page = client.get('/login?lang=en')
    match = re.search(r'name="csrf" value="([^"]+)"', page.get_data(as_text=True))
    assert match, 'the login form must carry its CSRF token'
    response = client.post(
        '/login',
        data={'username': user, 'password': password, 'next': '/', 'csrf': match.group(1)},
    )
    assert response.status_code == 302, response.get_data(as_text=True)
    return client


def _new_client(client):
    other = client.application.test_client()
    other.environ_base['HTTP_X_LANG'] = 'en'
    return other


def _csrf(client):
    return client.get('/api/config').get_json()['auth']['csrf_token']


def _post(client, path, payload=None):
    return client.post(path, json=payload or {}, headers={'X-CSRF-Token': _csrf(client)})


def _delete(client, path, payload=None):
    return client.delete(path, json=payload or {}, headers={'X-CSRF-Token': _csrf(client)})


def _create(client, username, password=PASSWORD, role='user'):
    response = _post(client, '/api/accounts', {'username': username, 'password': password, 'role': role})
    return response


def _settle_password(client, old=PASSWORD, new=NEW_PASSWORD):
    """An admin-created account owes a password change on first login; spend it."""
    response = _post(client, '/api/account/password', {'current_password': old, 'new_password': new})
    assert response.status_code == 200, response.get_json()
    return client


class TestOnlyAnAdminManagesAccounts:
    def test_a_regular_user_is_refused_by_name(self, admin_client):
        created = _create(admin_client, 'alice')
        assert created.status_code == 201, created.get_json()
        alice = _settle_password(_login(_new_client(admin_client), 'alice', PASSWORD))
        assert alice.get('/api/accounts').status_code == 403
        assert 'administrator' in alice.get('/api/accounts').get_json()['error']
        assert _post(alice, '/api/accounts', {'username': 'mallory', 'password': PASSWORD}).status_code == 403

    def test_the_signed_in_account_can_see_itself(self, admin_client):
        body = admin_client.get('/api/account/me').get_json()
        assert body['user']['username'] == 'admin'
        assert body['user']['role'] == 'admin'


class TestTheRegistryNeverCarriesACredential:
    def test_no_password_or_hash_reaches_the_browser(self, admin_client):
        created = _create(admin_client, 'alice')
        text = created.get_data(as_text=True)
        assert PASSWORD not in text
        assert 'scrypt' not in text and 'password_hash' not in text
        listing = admin_client.get('/api/accounts')
        text = listing.get_data(as_text=True)
        assert PASSWORD not in text
        assert 'scrypt' not in text and 'password_hash' not in text
        assert {row['username'] for row in listing.get_json()['accounts']} == {'admin', 'alice'}

    def test_every_write_is_audited(self, admin_client):
        _create(admin_client, 'alice')
        entries = admin_client.get('/api/accounts/audit').get_json()['entries']
        events = [row['event'] for row in entries]
        assert 'account_create' in events and 'login_ok' in events
        text = str(entries)
        assert PASSWORD not in text


class TestAccountLifecycle:
    def test_disable_ends_live_sessions_and_blocks_login(self, admin_client):
        bob = _create(admin_client, 'bob').get_json()['user']
        bob_client = _login(_new_client(admin_client), 'bob', PASSWORD)
        assert bob_client.get('/api/config').status_code == 200
        response = _post(admin_client, f'/api/accounts/{bob["user_id"]}/status', {'status': 'disabled'})
        assert response.status_code == 200, response.get_json()
        assert bob_client.get('/api/config').status_code == 401
        page = bob_client.get('/login?lang=en').get_data(as_text=True)
        token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        refused = bob_client.post(
            '/login',
            data={'username': 'bob', 'password': PASSWORD, 'next': '/', 'csrf': token},
        )
        assert refused.status_code == 401
        assert 'disabled' in refused.get_data(as_text=True).lower()
        # Re-enabling restores the login; the account's own tree was never moved.
        _post(admin_client, f'/api/accounts/{bob["user_id"]}/status', {'status': 'active'})
        _login(_new_client(admin_client), 'bob', PASSWORD)

    def test_delete_needs_the_exact_username_and_moves_the_tree(self, admin_client):
        bob = _create(admin_client, 'bob').get_json()['user']
        wrong = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'carol'})
        assert wrong.status_code == 400
        source = os.path.join(Config.DATA_DIR, 'users', bob['user_id'])
        assert os.path.isdir(source)
        removed = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'bob'})
        assert removed.status_code == 200, removed.get_json()
        assert not os.path.exists(source)
        assert os.path.isdir(removed.get_json()['user']['trashed_to'])

    def test_a_mutating_call_without_the_csrf_token_is_refused(self, admin_client):
        response = admin_client.post('/api/accounts', json={'username': 'alice', 'password': PASSWORD})
        assert response.status_code == 403


class TestDataIsIsolated:
    def test_one_accounts_dataset_is_invisible_to_another(self, admin_client):
        alice = _create(admin_client, 'alice').get_json()['user']
        bob = _create(admin_client, 'bob').get_json()['user']
        alice_client = _settle_password(_login(_new_client(admin_client), 'alice', PASSWORD))
        bob_client = _settle_password(_login(_new_client(admin_client), 'bob', PASSWORD))
        pasted = _post(alice_client, '/api/data/paste', {'data': [{'text': 'alice only'}], 'name': 'secret.csv'})
        assert pasted.status_code == 200, pasted.get_json()
        dataset_id = pasted.get_json()['dataset_id']
        assert [row['dataset_id'] for row in alice_client.get('/api/data/datasets').get_json()['datasets']] == [
            dataset_id
        ]
        assert bob_client.get('/api/data/datasets').get_json()['datasets'] == []
        assert admin_client.get('/api/data/datasets').get_json()['datasets'] == []
        # And the bytes really live in each account's own tree, not in a shared table.
        alice_db = os.path.join(Config.DATA_DIR, 'users', alice['user_id'], 'datasets.db')
        bob_db = os.path.join(Config.DATA_DIR, 'users', bob['user_id'], 'datasets.db')
        assert os.path.isfile(alice_db) and os.path.isfile(bob_db)
        assert alice_db != bob_db

    def test_a_changed_password_ends_the_other_sessions(self, admin_client):
        alice = _create(admin_client, 'alice').get_json()['user']
        alice_client = _login(_new_client(admin_client), 'alice', PASSWORD)
        second = _login(_new_client(admin_client), 'alice', PASSWORD)
        reset = _post(admin_client, f'/api/accounts/{alice["user_id"]}/password', {'password': NEW_PASSWORD})
        assert reset.status_code == 200, reset.get_json()
        assert alice_client.get('/api/config').status_code == 401
        assert second.get('/api/config').status_code == 401
        _login(_new_client(admin_client), 'alice', NEW_PASSWORD)


class TestAnotherAccountsRunIsNotYours:
    def test_status_stop_processes_and_kill_refuse_a_foreign_run(self, admin_client):
        execution_state['user_id'] = 'u_0123456789ab'
        execution_state['running'] = True
        execution_state['logs'] = ['someone else’s console line']
        try:
            status = admin_client.get('/api/workflow/status').get_json()
            assert status['foreign_run'] is True
            assert status['logs'] == [] and status['log_total'] == 0
            assert status['results'] == [] and status['node_states'] == {}
            stop = _post(admin_client, '/api/workflow/stop')
            assert stop.status_code == 409
            assert 'another account' in stop.get_json()['error']
            # The refusal did not touch the run it does not own.
            assert execution_state['running'] is True
            processes = admin_client.get('/api/workflow/processes').get_json()
            assert processes['foreign_run'] is True and processes['threads'] == []
            killed = _post(admin_client, '/api/workflow/processes/kill', {'ident': 1})
            assert killed.status_code == 403
            assert admin_client.get('/api/stats/summary').get_json()['summary'] == {}
        finally:
            execution_state['user_id'] = ''
            execution_state['running'] = False
            execution_state['logs'] = []
