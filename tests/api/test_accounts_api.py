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


class TestAMomentShipsFromTheServer:
    """Every moment leaves as both a number and the server's own reading of it.

    The panel renders the second one: a browser formatting an epoch prints the VIEWER's zone, so an
    administrator on UTC+8 and the audit row in ``accounts.db`` disagreed by hours about when someone
    signed in — the same reason ``schedules`` already ships ``next_run_local``.
    """

    _TEXT = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')

    def test_the_account_row_carries_a_server_local_time(self, admin_client):
        rows = admin_client.get('/api/accounts').get_json()['accounts']
        admin = next(row for row in rows if row['username'] == 'admin')
        assert admin['last_login_at'] > 0, admin
        assert self._TEXT.fullmatch(admin['last_login_local']), admin

    def test_a_moment_that_never_happened_is_blank_not_zero(self, admin_client):
        created = _create(admin_client, 'alice').get_json()['user']
        rows = admin_client.get('/api/accounts').get_json()['accounts']
        row = next(item for item in rows if item['user_id'] == created['user_id'])
        # The WORD for “从未” belongs to the panel; a missing moment is data, not a translation.
        assert row['last_login_local'] == '', row

    def test_the_audit_rows_carry_a_server_local_time(self, admin_client):
        _create(admin_client, 'alice')
        entries = admin_client.get('/api/accounts/audit?limit=5').get_json()['entries']
        assert entries
        for row in entries:
            assert self._TEXT.fullmatch(row['ts_local']), row


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

    def test_an_admin_lifts_a_failed_login_lock_over_the_api(self, admin_client):
        """The 5-failures/15-minutes rule is also an availability hole.

        Anyone who knows a username can hold that person out by spraying wrong passwords, and the
        only way back was 重置密码 — a new credential for an account whose owner did nothing wrong.
        The lock is armed here through the service (its own behaviour is pinned in the unit suite) so
        this test is about the ROUTE: admin only, and it restores the same password.
        """
        import time

        bob = _create(admin_client, 'bob').get_json()['user']
        service = accounts_service.get_account_service()
        failures = service.store.bump_failure(bob['user_id'], time.time())
        service.store.set_locked_until(bob['user_id'], time.time() + 900, failures)
        assert float(service.store.get_user(bob['user_id'])['locked_until']) > time.time(), 'the lock is armed'

        unlocked = _post(admin_client, f'/api/accounts/{bob["user_id"]}/unlock', {})
        assert unlocked.status_code == 200, unlocked.get_json()
        assert unlocked.get_json()['ok'] is True
        assert float(service.store.get_user(bob['user_id'])['locked_until'] or 0) == 0.0
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

    def test_a_refused_busy_delete_does_not_revoke_the_accounts_sessions(self, admin_client, monkeypatch):
        """The 409 must arrive BEFORE the force logout. Force-logging-out first meant a refusal
        the operator was told did not happen had already killed every session the account held
        (and filed an audit row saying so)."""
        bob = _create(admin_client, 'bob').get_json()['user']
        service = accounts_service.get_account_service()
        revocations = []
        original = service.force_logout
        monkeypatch.setattr(
            service, 'force_logout', lambda *args, **kwargs: revocations.append(args[1]) or original(*args, **kwargs)
        )
        execution_state['running'] = True
        execution_state['user_id'] = bob['user_id']
        execution_state['run_id'] = 'bobs-live-run'
        try:
            refused = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'bob'})
        finally:
            execution_state['running'] = False
            execution_state['user_id'] = ''
            execution_state['run_id'] = ''
        assert refused.status_code == 409, refused.get_json()
        assert revocations == [], 'a refused delete revoked the account’s sessions anyway'

    def test_the_busy_probe_is_answered_only_to_an_administrator(self, admin_client):
        """“这个账号还有运行中的任务（<run id>）” names another account's run — so the
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

    def test_a_force_logout_closes_the_scope_inside_the_claim_lock(self, admin_client, monkeypatch):
        """ "No run is live" must be proved inside ``execute_lock`` — the lock ``begin_run`` claims under.

        Probing and closing were two separate steps here, so a run could start in the gap and keep a
        ``RunStore`` this route had just closed: the worker dies on ``Cannot operate on a closed
        database`` halfway through a record. The test asks the REAL lock, from the thread that holds
        it: a ``threading.Lock`` is not reentrant, so a non-blocking acquire failing is the proof."""
        from api import accounts as accounts_api

        bob = _create(admin_client, 'bob').get_json()['user']
        held = []

        def spy(user_id):
            acquired = accounts_api.execute_lock.acquire(blocking=False)
            if acquired:
                accounts_api.execute_lock.release()
            held.append(not acquired)
            return user_id

        monkeypatch.setattr(accounts_api.stores, 'release_user', spy)
        assert _post(admin_client, f'/api/accounts/{bob["user_id"]}/logout').status_code == 200
        assert held == [True], 'the stores closed outside the lock a claim takes'

    def test_a_delete_revokes_the_sessions_before_it_moves_the_tree(self, admin_client, monkeypatch):
        """A victim whose session still resolves during the move re-creates the tree being moved.

        The row outlives ``release_user`` by the length of ``shutil.move``: a request in that window
        rebuilt the user's stores, and building them calls ``ensure()`` — a FRESH empty
        ``data/users/<id>/`` the move knows nothing about. The row is deleted right after, so that
        directory is never trashed and its databases are never closed."""
        from api import accounts as accounts_api

        bob = _create(admin_client, 'bob').get_json()['user']
        _settle_password(_login(_new_client(admin_client), 'bob', PASSWORD))
        live_at_release = []

        def spy(user_id):
            rows = accounts_service.get_account_service().store._all(
                'SELECT sid_hash FROM sessions WHERE user_id = ? AND revoked_at IS NULL', (user_id,)
            )
            live_at_release.append(len(rows))

        monkeypatch.setattr(accounts_api.stores, 'release_user', spy)
        response = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'bob'})
        assert response.status_code == 200, response.get_json()
        assert live_at_release == [0], 'a live session could still rebuild the tree mid-move'

    def test_a_delete_that_cannot_move_the_data_back_names_where_it_went(self, admin_client, monkeypatch):
        """The compensation itself can fail, and then “数据仍在原处” is a lie with a direction.

        ``delete_user`` moves the tree, drops the row, and on a refused drop moves it back. A
        Windows rename can fail on a profile a browser still holds — leaving the data in
        ``users/.trash/`` while the account row stays. The refusal has to say where the tree ACTUALLY
        is, or the operator looks in the one directory it is not in."""
        import shutil
        import sqlite3

        from services.accounts.store import AccountsStore

        bob = _create(admin_client, 'bob').get_json()['user']
        real_move = shutil.move
        moves = []

        def move_then_refuse(source, destination):
            moves.append((source, destination))
            if len(moves) > 1:
                raise OSError(13, 'Permission denied')
            return real_move(source, destination)

        def refuse_drop(_self, user_id):
            raise sqlite3.OperationalError(f'database is locked: {user_id}')

        monkeypatch.setattr(accounts_service.shutil, 'move', move_then_refuse)
        monkeypatch.setattr(AccountsStore, 'delete_user', refuse_drop)

        response = _delete(admin_client, f'/api/accounts/{bob["user_id"]}', {'confirm_username': 'bob'})
        assert response.status_code == 500, response.get_json()
        error = response.get_json()['error']
        assert '.trash' in error, error
        assert bob['user_id'] in error, error

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

    def test_a_finished_cookie_job_stays_owner_only(self, admin_client):
        """``active`` going False must not publish the job: the probed URL, the account label and
        the console lines are still the answer that account paid a browser for."""
        from sessions.routes import _COOKIE_JOB

        previous = dict(_COOKIE_JOB)
        _COOKIE_JOB.update(
            active=False,
            owner='u_0123456789ab',
            kind='verify',
            platform='zhihu',
            account='',
            phase='verified',
            error='OSError: F:\\private\\cookies\\zhihu_cookies.json',
            count=3,
            entry='https://www.zhihu.com/secret',
            facts={'login_wall': False, 'url': 'https://www.zhihu.com/secret'},
            lines=['someone else’s diagnosis'],
        )
        try:
            body = admin_client.get('/api/cookies/generate/status').get_json()
            assert body['active'] is False
            assert body['platform'] == '' and body['facts'] == {} and body['lines'] == []
            assert body['entry'] == '' and body['error'] == '' and body['phase'] == ''
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

    def test_a_thread_that_never_started_hands_the_slot_and_identity_back(self, admin_client, monkeypatch):
        """``Thread.start`` can raise on a loaded box. The claim had already stamped the run id and
        the owner; a handler that cleared only ``running`` left every later status answer naming a
        run with no record, and every OTHER account reading ``foreign_run``."""
        import engine.run as run_module

        admin_id = _me(admin_client)['user_id']
        execution_state['user_id'] = admin_id
        execution_state['username'] = 'admin'
        execution_state['run_id'] = 'admins-finished-run'
        execution_state['workflow_labels'] = ['admin’s canvas']

        class _NeverStarts:
            def __init__(self, *args, **kwargs):
                self.name = 'run'

            def start(self):
                raise RuntimeError("can't start new thread")

            def is_alive(self):
                return False

        monkeypatch.setattr(run_module.threading, 'Thread', _NeverStarts)
        answer = _post(
            admin_client,
            '/api/workflow/execute',
            {
                'workflow': {
                    'nodes': [{'id': 'n1', 'type': 'name', 'params': {'name': 'demo'}}],
                    'connections': [],
                },
                'workflow_name': 'demo',
            },
        )
        assert answer.status_code == 500, answer.get_json()
        assert execution_state['running'] is False
        assert execution_state['thread'] is None
        assert execution_state['run_id'] == 'admins-finished-run', 'a thread that never ran stamped a run id'
        assert execution_state['user_id'] == admin_id
        assert execution_state['workflow_labels'] == ['admin’s canvas']
        assert admin_client.get('/api/workflow/status').get_json().get('foreign_run') is not True

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


#: The settings keys that name a file on the machine itself. A plain account has no use for
#: them — they are a fingerprint of the host and a map of what to aim at — so it reads them
#: blanked while still seeing the values its own runs live under.
HOST_PATH_KEYS = (
    'driver_path',
    'browser_binary',
    'latex_binary',
    'catbus_cli',
    'catbus_node',
    'browser_profile_dir',
    'hongguo_player_path',
    'mitmdump_path',
)


def _as_plain_user(admin_client):
    """A second, ordinary account on the same host, logged in on its own client."""
    created = _create(admin_client, 'bob', role='user')
    assert created.status_code in (200, 201), created.get_json()
    other = _new_client(admin_client)
    _login(other, 'bob')
    # The account owes a password change on its first login, and that gate answers before any
    # route it is not on the allow-list for — spend it, or every assertion below proves the
    # gate instead of the permission it was written for.
    return _settle_password(other)


class TestMachineSettingsAreReadWriteForAdminsOnly:
    """``data/settings.json`` is one file for every account: a driver path, the Ollama
    address, the browser every crawl opens. One account may not move another's.

    The write had been gated this way since accounts existed; what was missing is that a
    plain account could still READ every host path, and that nothing told the panel the
    fields were locked — so a user typed into one and met a 403 at save time.
    """

    def test_a_plain_account_reads_the_values_but_not_the_host_paths(self, admin_client):
        bob = _as_plain_user(admin_client)
        body = bob.get('/api/settings').get_json()
        assert body['ok'] is True
        assert body['read_only'] is True, 'the panel has to be told, not left to find out on save'
        for key in HOST_PATH_KEYS:
            assert body['settings'].get(key, 'sentinel') == '', f'{key} leaked the host layout'
        # The values that describe how its OWN runs behave stay readable.
        assert 'page_load_timeout' in body['settings']
        assert 'element_timeout' in body['settings']

    def test_a_plain_account_cannot_write_them(self, admin_client):
        bob = _as_plain_user(admin_client)
        response = _post(bob, '/api/settings', {'settings': {'page_load_timeout': 5}})
        assert response.status_code == 403
        assert 'admin' in response.get_json()['error'].lower()

    def test_an_admin_sees_everything_and_may_write(self, admin_client):
        body = admin_client.get('/api/settings').get_json()
        assert body['read_only'] is False
        for key in HOST_PATH_KEYS:
            assert key in body['settings']
        saved = _post(admin_client, '/api/settings', {'settings': {'element_timeout': 15}})
        assert saved.status_code == 200, saved.get_json()

    def test_a_local_install_with_no_accounts_stays_editable(self, client, monkeypatch):
        """The single-user default: there is nobody to protect the settings FROM."""
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(Config, 'ADMIN_USER', '')
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        accounts_service.reset_service()
        body = client.get('/api/settings').get_json()
        assert body['read_only'] is False
        assert _post(client, '/api/settings', {'settings': {'element_timeout': 15}}).status_code == 200


class TestTheLexiconsAreAMachineLevelWrite:
    """The lexicon store is a singleton with no per-account slot, and every write reloads
    jieba for the whole process — so one account's stopword changes what every other
    account's next tokenisation produces."""

    def test_a_plain_account_may_read_but_not_edit(self, admin_client):
        bob = _as_plain_user(admin_client)
        assert bob.get('/api/lexicon').get_json()['ok'] is True
        added = _post(bob, '/api/lexicon', {'kind': 'stopword', 'terms': ['测试']})
        assert added.status_code == 403
        cleared = _delete(bob, '/api/lexicon', {'kind': 'userdict', 'clear': True})
        assert cleared.status_code == 403

    def test_an_admin_may_edit(self, admin_client):
        added = _post(admin_client, '/api/lexicon', {'kind': 'stopword', 'terms': ['测试']})
        assert added.status_code == 200, added.get_json()
        removed = _delete(admin_client, '/api/lexicon', {'kind': 'stopword', 'term': '测试'})
        assert removed.status_code == 200, removed.get_json()


class TestTheProcessPanelIsWatchOnlyForPlainAccounts:
    """The thread list stays readable for everyone — 只能查看 — but the kill is a
    system-level operation: it injects ``SystemExit`` into a thread of THIS process,
    which also holds the scheduler and every account's worker. So the panel answers
    with the caller's verdict (``can_control``) and the kill refuses a plain account,
    the same shape the settings panel's ``read_only`` uses."""

    def test_the_panel_tells_the_page_who_may_drive_it(self, admin_client):
        bob = _as_plain_user(admin_client)
        assert bob.get('/api/workflow/processes').get_json()['can_control'] is False
        assert admin_client.get('/api/workflow/processes').get_json()['can_control'] is True

    def test_a_plain_account_cannot_kill_but_may_still_watch(self, admin_client):
        bob = _as_plain_user(admin_client)
        # Give the slot to bob, so the refusal below is the ADMIN one and not the
        # foreign-run guard that answers an account with no claim on the slot.
        execution_state['running'] = True
        execution_state['user_id'] = _me(bob)['user_id']
        try:
            refused = _post(bob, '/api/workflow/processes/kill', {'ident': 1})
            assert refused.status_code == 403, refused.get_json()
            assert 'admin' in refused.get_json()['error'].lower()
            # The read side stays open: the panel still answers, view-only.
            watched = bob.get('/api/workflow/processes').get_json()
            assert watched['can_control'] is False and watched.get('foreign_run') is not True
        finally:
            execution_state['running'] = False
            execution_state['user_id'] = ''

    def test_an_admin_keeps_the_kill(self, admin_client):
        # Own the slot, so the request passes the foreign-run guard and reaches the ident checks.
        execution_state['running'] = True
        execution_state['user_id'] = _me(admin_client)['user_id']
        try:
            refused_shape = _post(admin_client, '/api/workflow/processes/kill', {'ident': 1})
            # The admin gate does not fire: a dead ident reaches the not-found answer by name.
            assert refused_shape.status_code == 404, refused_shape.get_json()
        finally:
            execution_state['running'] = False
            execution_state['user_id'] = ''

    def test_a_host_without_accounts_keeps_the_kill_for_its_single_user(self, client, monkeypatch):
        """The single-user default: there is nobody to protect the process FROM."""
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(Config, 'ADMIN_USER', '')
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        accounts_service.reset_service()
        assert client.get('/api/workflow/processes').get_json()['can_control'] is True
        response = _post(client, '/api/workflow/processes/kill', {'ident': 1})
        assert response.status_code == 404, response.get_json()


class TestTheProfileTemplateIsAnOperatorAction:
    """The template is the SHARED ancestor of every account's browser profile, and
    rebuilding it launches a real Chrome on the host. That is an operator's move —
    the same class of machine-level write as settings.json — so with accounts on
    the machine it answers to the admin."""

    def test_a_plain_account_cannot_rebuild_the_shared_template(self, admin_client):
        bob = _as_plain_user(admin_client)
        refused = _post(bob, '/api/browser/profiles/template', {'force': False})
        assert refused.status_code == 403, refused.get_json()
        assert 'admin' in refused.get_json()['error'].lower()

    def test_an_admin_may_rebuild_it(self, admin_client, monkeypatch):
        import sessions.routes as routes

        monkeypatch.setattr(routes, 'ensure_profile_template', lambda force=False: {'ok': True, 'stubbed': True})
        response = _post(admin_client, '/api/browser/profiles/template', {'force': False})
        assert response.status_code == 200, response.get_json()
        assert response.get_json()['stubbed'] is True


class TestComponentAndUpdateWritesAreOperatorActions:
    """Installing/removing a component rewrites the tree every account's next run spawns, and the
    self-update replaces the program and restarts the process. Both are machine-level writes, so
    with accounts on they answer to the admin — the same door settings/lexicon/template use."""

    def test_a_plain_account_cannot_install_a_component(self, admin_client):
        alice = _as_plain_user(admin_client)
        refused = _post(alice, '/api/components/install', {'id': 'chromedriver'})
        assert refused.status_code == 403, refused.get_json()
        assert 'admin' in refused.get_json()['error'].lower()

    def test_a_plain_account_cannot_remove_a_component(self, admin_client):
        alice = _as_plain_user(admin_client)
        refused = _post(alice, '/api/components/remove', {'id': 'chromedriver'})
        assert refused.status_code == 403, refused.get_json()

    def test_a_plain_account_cannot_download_or_apply_an_update(self, admin_client):
        alice = _as_plain_user(admin_client)
        for path in ('/api/update/download', '/api/update/restart', '/api/update/cancel'):
            refused = _post(alice, path, {})
            assert refused.status_code == 403, (path, refused.get_json())
        assert alice.get('/api/update/status').status_code == 403

    def test_an_admin_reaches_the_body_checks_not_the_gate(self, admin_client):
        """An admin on a SOURCE run is refused by the updater's own rule, never with a 403."""
        refused = _post(admin_client, '/api/update/download', {})
        assert refused.status_code != 403, refused.get_json()
