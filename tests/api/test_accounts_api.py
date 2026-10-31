"""The account-management API: admin-only operations, no credential leakage, isolated data."""

import os
import re
import threading

import pytest
from core.config import Config
from runtime.account_context import Account
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


def _me(client) -> dict:
    """The signed-in account as the server describes it."""
    return client.get('/api/account/me').get_json()['user']


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

    def test_machine_settings_can_only_be_written_by_an_admin(self, admin_client):
        """settings.json is machine-level (driver/browser paths, timeouts); a regular account may
        read the page but must not rewrite what every account runs against."""
        created = _create(admin_client, 'alice')
        assert created.status_code == 201, created.get_json()
        alice = _settle_password(_login(_new_client(admin_client), 'alice', PASSWORD))
        refused = _post(alice, '/api/settings', {'settings': {'page_load_timeout': 5}})
        assert refused.status_code == 403
        assert 'administrator' in refused.get_json()['error']
        allowed = _post(admin_client, '/api/settings', {'settings': {}})
        assert allowed.status_code == 200, allowed.get_json()

    def test_an_oversized_password_is_refused_like_a_wrong_one(self, admin_client):
        anonymous = _new_client(admin_client)
        page = anonymous.get('/login?lang=en').get_data(as_text=True)
        token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        refused = anonymous.post(
            '/login',
            data={'username': 'admin', 'password': 'x' * 5000, 'next': '/', 'csrf': token},
        )
        assert refused.status_code == 401
        assert 'wrong username or password' in refused.get_data(as_text=True).lower()

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

    def test_delete_closes_the_accounts_stores_before_moving_the_tree(self, admin_client, monkeypatch):
        """Windows refuses to rename a directory whose SQLite files are still open."""
        from api import accounts as accounts_api

        bob = _create(admin_client, 'bob').get_json()['user']
        service = accounts_service.get_account_service()
        events = []
        original_delete = service.delete_user
        monkeypatch.setattr(accounts_api.stores, 'release_user', lambda user_id: events.append(('release', user_id)))

        def spy(*args, **kwargs):
            events.append(('delete', args[1]))
            return original_delete(*args, **kwargs)

        monkeypatch.setattr(service, 'delete_user', spy)
        response = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'bob'})
        assert response.status_code == 200, response.get_json()
        assert events[:2] == [('release', bob['user_id']), ('delete', bob['user_id'])]

    def test_a_refused_delete_never_closes_another_accounts_stores(self, admin_client, monkeypatch):
        """The order used to be: close the handles, then find out whether this was allowed. A
        wrong confirmation answered 400, and a caller who is not an administrator answered 403 —
        both AFTER pulling the account's open databases out from under it."""
        from api import accounts as accounts_api

        bob = _create(admin_client, 'bob').get_json()['user']
        _create(admin_client, 'mallory')
        mallory = _settle_password(_login(_new_client(admin_client), 'mallory', PASSWORD))
        releases = []
        monkeypatch.setattr(accounts_api.stores, 'release_user', releases.append)

        wrong = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'nobody'})
        assert wrong.status_code == 400, wrong.get_json()
        assert releases == [], 'a refused delete closed Bob’s stores'

        refused = _delete(mallory, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'bob'})
        assert refused.status_code == 403, refused.get_json()
        assert releases == [], 'a non-admin closed Bob’s stores without deleting anything'

    def test_the_busy_probe_is_answered_only_to_an_administrator(self, admin_client):
        """「这个账号还有运行中的任务（<run id>）」 names another account's run — so the
        administrator check must come before the probe, not after it."""
        bob = _create(admin_client, 'bob').get_json()['user']
        _create(admin_client, 'mallory')
        mallory = _settle_password(_login(_new_client(admin_client), 'mallory', PASSWORD))
        execution_state['running'] = True
        execution_state['user_id'] = bob['user_id']
        execution_state['run_id'] = 'bobs-secret-run'
        try:
            refused = _post(mallory, f'/api/accounts/{bob["user_id"]}/status', {'status': 'disabled'})
            assert refused.status_code == 403, refused.get_json()
            assert 'bobs-secret-run' not in refused.get_data(as_text=True), 'the probe leaked the run id'
            # The administrator still gets the guard, named.
            guarded = _post(admin_client, f'/api/accounts/{bob["user_id"]}/status', {'status': 'disabled'})
            assert guarded.status_code == 409, guarded.get_json()
            assert 'bobs-secret-run' in guarded.get_json()['error']
        finally:
            execution_state['running'] = False
            execution_state['user_id'] = ''
            execution_state['run_id'] = ''

    def test_a_move_that_fails_is_named_in_json_and_deletes_nothing(self, admin_client, monkeypatch):
        """A profile a browser still holds makes ``shutil.move`` refuse on Windows; every caller
        of this panel parses JSON, and the account must not be half-deleted."""
        import shutil as shutil_module

        bob = _create(admin_client, 'bob').get_json()['user']

        def boom(*_args, **_kwargs):
            raise PermissionError('the file is being used by another process')

        monkeypatch.setattr(shutil_module, 'move', boom)
        response = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'bob'})
        assert response.status_code == 500, response.get_json()
        assert response.is_json, 'a storage failure answered with an HTML page'
        assert 'PermissionError' in response.get_json()['error']
        assert os.path.isdir(os.path.join(Config.DATA_DIR, 'users', bob['user_id'])), 'the tree moved anyway'
        assert bob['user_id'] in [row['user_id'] for row in admin_client.get('/api/accounts').get_json()['accounts']]

    def test_force_logout_releases_the_scope_only_when_no_run_is_writing(self, admin_client, monkeypatch):
        from api import accounts as accounts_api

        bob = _create(admin_client, 'bob').get_json()['user']
        releases = []
        monkeypatch.setattr(accounts_api.stores, 'release_user', releases.append)
        assert _post(admin_client, f'/api/accounts/{bob["user_id"]}/logout').status_code == 200
        assert releases == [bob['user_id']]

        execution_state['running'] = True
        execution_state['user_id'] = bob['user_id']
        execution_state['run_id'] = 'bobs-run'
        try:
            assert _post(admin_client, f'/api/accounts/{bob["user_id"]}/logout').status_code == 200
        finally:
            execution_state['running'] = False
            execution_state['user_id'] = ''
            execution_state['run_id'] = ''
        assert releases == [bob['user_id']], 'a force logout closed a live run’s stores'

    def test_delete_refuses_while_that_accounts_cookie_window_is_open(self, admin_client):
        """The account's Chrome profile is in use; moving its tree would fail (and strand it)."""
        from sessions.routes import _COOKIE_JOB

        bob = _create(admin_client, 'bob').get_json()['user']
        previous = dict(_COOKIE_JOB)
        _COOKIE_JOB.update(active=True, owner=bob['user_id'], kind='login', platform='zhihu')
        try:
            response = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'bob'})
            assert response.status_code == 409
            assert os.path.isdir(os.path.join(Config.DATA_DIR, 'users', bob['user_id']))
        finally:
            _COOKIE_JOB.clear()
            _COOKIE_JOB.update(previous)

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
    def test_live_results_are_never_previewed_or_reported(self, admin_client):
        execution_state['user_id'] = 'u_0123456789ab'
        execution_state['running'] = True
        execution_state['run_id'] = 'foreign-run'
        execution_state['results'] = {'node-1': [{'text': 'someone else’s row'}]}
        try:
            preview = _post(admin_client, '/api/data/preview', {'node_id': 'node-1'})
            body = preview.get_json()
            assert preview.status_code == 400
            assert body.get('code') == 'no_run_data', 'the live results leaked into a preview'
            assert 'someone else' not in preview.get_data(as_text=True)
            # A report with no run id means "the last run in this process" — that run is not ours.
            report = _post(admin_client, '/api/report/generate', {})
            assert report.status_code == 409
            # ...and the live status names no record we do not own.
            status = admin_client.get('/api/runs/status').get_json()
            assert status['running'] is False
            assert status['run_id'] == ''
            assert status.get('foreign_run') is True
        finally:
            execution_state['user_id'] = ''
            execution_state['running'] = False
            execution_state['run_id'] = ''
            execution_state['results'] = {}

    def test_a_stopped_run_still_settling_keeps_its_account_alive(self):
        """Stop clears ``running`` while the worker is still settling; disabling/deleting the
        account then would close its stores under a live writer."""
        from api.accounts import _busy_run

        class _Alive:
            def is_alive(self):
                return True

        execution_state['running'] = False
        execution_state['thread'] = _Alive()
        execution_state['user_id'] = 'u_0123456789ab'
        execution_state['run_id'] = 'settling-run'
        try:
            assert _busy_run('u_0123456789ab') == 'settling-run'
            assert _busy_run('u_bbbbbbbbbbbb') == ''
        finally:
            execution_state['thread'] = None
            execution_state['user_id'] = ''
            execution_state['run_id'] = ''

    def test_another_accounts_cookie_job_is_invisible_and_not_answerable(self, admin_client):
        from sessions.routes import _COOKIE_JOB

        previous = dict(_COOKIE_JOB)
        _COOKIE_JOB.update(
            active=True,
            owner='u_0123456789ab',
            kind='verify',
            platform='zhihu',
            account='',
            phase='verified',
            error='',
            count=3,
            entry='https://www.zhihu.com/secret',
            facts={'login_wall': False, 'url': 'https://www.zhihu.com/secret'},
            lines=['someone else’s diagnosis'],
        )
        try:
            body = admin_client.get('/api/cookies/generate/status').get_json()
            assert body['active'] is False
            assert body['platform'] == '' and body['facts'] == {} and body['lines'] == []
            assert body['entry'] == ''
            assert _post(admin_client, '/api/cookies/generate/confirm').status_code == 400
            assert _post(admin_client, '/api/cookies/generate/cancel').status_code == 400
        finally:
            _COOKIE_JOB.clear()
            _COOKIE_JOB.update(previous)

    def test_a_refused_claim_does_not_take_over_the_slot(self, admin_client, monkeypatch):
        """The LLM-requirement refusals come AFTER the run id and the owner are stamped. A loser
        must hand both back: otherwise its own console poll answers with the previous owner's
        lines and results, and the true owner is told its run is foreign."""
        from runtime import account_context
        from runtime.state import ambient, set_ambient

        admin_id = _me(admin_client)['user_id']
        _create(admin_client, 'alice')
        alice = _settle_password(_login(_new_client(admin_client), 'alice', PASSWORD))
        monkeypatch.setattr('engine.run.workflow_needs_llm', lambda _workflow: True)

        execution_state['user_id'] = admin_id
        execution_state['username'] = 'admin'
        execution_state['run_id'] = 'admins-finished-run'
        execution_state['results'] = {'node-1': [{'text': 'admin’s own row'}]}
        execution_state['workflow_labels'] = ['admin’s canvas']
        with account_context.use(Account(admin_id, 'admin', 'admin')):
            set_ambient('admin’s canvas', 'admin-fingerprint')
            own_status = admin_client.get('/api/workflow/status').get_json()
        assert own_status.get('foreign_run') is not True and own_status['results'], 'the owner lost its own run'

        refused = _post(
            alice,
            '/api/workflow/execute',
            {
                'workflow': {'nodes': [{'id': 'node-1', 'type': 'source'}], 'connections': []},
                'workflow_name': 'alice’s canvas',
                'llm': {'provider': 'ollama', 'model': ''},
            },
        )
        assert refused.status_code == 400, refused.get_json()

        assert execution_state['user_id'] == admin_id, 'a refused claim re-stamped the slot owner'
        assert execution_state['run_id'] == 'admins-finished-run', 'a refused claim stamped a run id'
        assert execution_state['workflow_labels'] == ['admin’s canvas']
        alice_id = _me(alice)['user_id']
        with account_context.use(Account(alice_id, 'alice', 'user')):
            assert ambient() == {}, 'a refused claim re-keyed the loser’s canvas identity'
        with account_context.use(Account(admin_id, 'admin', 'admin')):
            assert ambient()['workflow_name'] == 'admin’s canvas', 'the refusal clobbered the owner’s canvas'
        # The loser sees an idle slot, and the owner still sees its own console.
        assert alice.get('/api/workflow/status').get_json()['foreign_run'] is True
        with account_context.use(Account(admin_id, 'admin', 'admin')):
            after = admin_client.get('/api/workflow/status').get_json()
        assert after['results'] and not after.get('foreign_run')

    def test_the_process_panel_sees_only_your_own_run_threads(self, admin_client):
        """A thread list is a MACHINE fact. On a shared host it also holds the scheduler (killing
        it stops every account's 定时任务) and another account's cookie-capture window, so the
        panel must neither list them nor accept their idents."""
        admin_id = _me(admin_client)['user_id']
        keeper = threading.Event()
        stranger = threading.Thread(target=keeper.wait, name='cookie-login-window', daemon=True)
        stranger.start()
        execution_state['running'] = True
        execution_state['user_id'] = admin_id
        try:
            listed = admin_client.get('/api/workflow/processes').get_json()
            names = [row['name'] for row in listed['threads']]
            idents = [row['ident'] for row in listed['threads']]
            assert 'cookie-login-window' not in names, names
            assert stranger.ident not in idents, idents
            assert all(name == 'run' or name.startswith('ThreadPoolExecutor') for name in names), names
            killed = _post(admin_client, '/api/workflow/processes/kill', {'ident': stranger.ident})
            assert killed.status_code == 403, killed.get_json()
            assert 'cookie-login-window' in killed.get_json()['error']
            assert stranger.is_alive(), 'the refusal still injected SystemExit into the thread'
        finally:
            keeper.set()
            execution_state['running'] = False
            execution_state['user_id'] = ''

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
