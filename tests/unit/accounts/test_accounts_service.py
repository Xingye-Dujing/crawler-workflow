"""The account registry's rules: bootstrap, login, sessions, lockout and administration."""

import os
import time

import pytest
from core.config import Config

from services.accounts import security
from services.accounts.errors import AccountError
from services.accounts.service import AccountService
from services.accounts.store import AccountsStore

PASSWORD = 'correct-horse-battery'


@pytest.fixture
def service(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    monkeypatch.setattr(Config, 'DATA_DIR', str(data))
    monkeypatch.setattr(Config, 'ACCOUNTS_DB', str(data / 'accounts.db'))
    monkeypatch.setattr(Config, 'ADMIN_USER', 'admin')
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', PASSWORD)
    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(Config, 'SESSION_IDLE_MINUTES', 120)
    monkeypatch.setattr(Config, 'SESSION_MAX_HOURS', 24)
    store = AccountsStore(str(data / 'accounts.db'))
    svc = AccountService(store)
    yield svc
    store.close()


def _bootstrap(service):
    admin = service.bootstrap()
    assert admin is not None
    return admin


def _admin(service):
    return _login(service).account


def _login(service, username='admin', password=PASSWORD):
    return service.authenticate(username, password, ip='127.0.0.1')


def test_bootstrap_creates_one_admin_and_never_resets_it(service, monkeypatch):
    admin = _bootstrap(service)
    assert admin['role'] == 'admin'
    assert admin['username'] == 'admin'
    assert 'password_hash' not in admin
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'another-long-password')
    assert service.bootstrap() is None
    # The original password still works and the environment one does not.
    _login(service)
    with pytest.raises(AccountError):
        _login(service, password='another-long-password')


def test_login_returns_a_session_that_resolves_and_revokes(service):
    _bootstrap(service)
    ticket = _login(service)
    account = service.resolve(ticket.token)
    assert account.user_id == ticket.account.user_id
    assert account.role == 'admin'
    assert account.csrf_token == ticket.csrf_token
    service.logout(ticket.token)
    assert service.resolve(ticket.token) is None


def test_the_database_never_stores_the_session_token(service):
    _bootstrap(service)
    ticket = _login(service)
    rows = service.store.list_audit(1)
    assert rows  # audit works and holds no credential
    stored = service.store.get_session(security.token_hash(ticket.token))
    assert stored is not None
    assert ticket.token not in str(stored)


def test_wrong_password_locks_after_five_attempts(service):
    _bootstrap(service)
    for _ in range(4):
        with pytest.raises(AccountError) as exc:
            _login(service, password='wrong-password')
        assert exc.value.key == 'auth.badCredentials'
    with pytest.raises(AccountError) as exc:
        _login(service, password='wrong-password')
    assert exc.value.key == 'accounts.lockedOut'
    # Even the right password is refused while the lock stands.
    with pytest.raises(AccountError) as exc:
        _login(service)
    assert exc.value.key == 'accounts.lockedOut'


def test_unknown_username_answers_the_same_refusal(service):
    _bootstrap(service)
    with pytest.raises(AccountError) as exc:
        _login(service, username='nobody')
    assert exc.value.key == 'auth.badCredentials'
    assert 'nobody' not in str(exc.value)


def test_disabled_account_cannot_log_in(service):
    admin = _bootstrap(service)
    admin = _admin(service)
    bob = service.create_user(admin, 'bob', PASSWORD)
    ticket = service.authenticate('bob', PASSWORD)
    service.set_status(admin, bob['user_id'], 'disabled')
    assert service.resolve(ticket.token) is None
    with pytest.raises(AccountError) as exc:
        service.authenticate('bob', PASSWORD)
    assert exc.value.key == 'accounts.accountDisabled'


def test_create_user_is_admin_only_and_names_are_case_insensitive(service):
    _bootstrap(service)
    bob = service.create_user(_login(service).account, 'bob', PASSWORD)
    assert bob['role'] == 'user'
    assert os.path.isdir(os.path.join(Config.DATA_DIR, 'users', bob['user_id']))
    bob_account = _login(service, 'bob', PASSWORD).account
    with pytest.raises(AccountError) as exc:
        service.create_user(bob_account, 'carol', PASSWORD)
    assert exc.value.key == 'accounts.adminRequired'
    with pytest.raises(AccountError) as exc:
        service.create_user(_login(service).account, 'BOB', PASSWORD)
    assert exc.value.key == 'accounts.usernameTaken'


def test_password_reset_revokes_every_session_and_forces_a_change(service):
    _bootstrap(service)
    admin = _admin(service)
    bob = service.create_user(admin, 'bob', PASSWORD)
    ticket = _login(service, 'bob', PASSWORD)
    service.reset_password(admin, bob['user_id'], 'brand-new-password')
    assert service.resolve(ticket.token) is None
    new_ticket = service.authenticate('bob', 'brand-new-password')
    assert new_ticket.account.must_change_password is True


def test_change_password_keeps_the_current_session_only(service):
    _bootstrap(service)
    first = _login(service)
    second = _login(service)
    service.change_password(first.account, PASSWORD, 'a-brand-new-password', first.token)
    assert service.resolve(first.token) is not None
    assert service.resolve(second.token) is None
    with pytest.raises(AccountError) as exc:
        service.change_password(first.account, PASSWORD, 'yet-another-password', first.token)
    assert exc.value.key == 'accounts.currentPasswordWrong'


def test_the_last_active_admin_cannot_be_disabled_or_deleted(service):
    _bootstrap(service)
    admin = _admin(service)
    other = service.create_user(admin, 'root2', PASSWORD, role='admin')
    service.set_status(admin, other['user_id'], 'disabled')
    with pytest.raises(AccountError) as exc:
        service.set_status(admin, admin.user_id, 'disabled')
    assert exc.value.key == 'accounts.cannotDisableSelf'
    actor = service.authenticate('admin', PASSWORD).account
    with pytest.raises(AccountError) as exc:
        service.delete_user(actor, admin.user_id, 'admin')
    assert exc.value.key == 'accounts.cannotDeleteSelf'


def test_delete_moves_the_tree_to_the_trash(service):
    _bootstrap(service)
    admin = _admin(service)
    bob = service.create_user(admin, 'bob', PASSWORD)
    source = os.path.join(Config.DATA_DIR, 'users', bob['user_id'])
    with open(os.path.join(source, 'runs.db'), 'wb') as handle:
        handle.write(b'not-empty')
    result = service.delete_user(admin, bob['user_id'], 'bob')
    assert not os.path.exists(source)
    assert os.path.isdir(result['trashed_to'])
    assert os.path.isfile(os.path.join(result['trashed_to'], 'runs.db'))
    assert service.store.get_user(bob['user_id']) is None
    assert any(row['event'] == 'account_delete' for row in service.store.list_audit(50))


def test_an_idle_session_is_refused_and_revoked(service, monkeypatch):
    monkeypatch.setattr(Config, 'SESSION_IDLE_MINUTES', 1)
    _bootstrap(service)
    ticket = _login(service)
    service.store._write(
        'UPDATE sessions SET last_seen_at = ? WHERE sid_hash = ?',
        (time.time() - 600, security.token_hash(ticket.token)),
    )
    assert service.resolve(ticket.token) is None
    assert service.store.get_session(security.token_hash(ticket.token))['revoked_at'] is not None


def test_validation_rules_and_hashes():
    with pytest.raises(AccountError):
        security.validate_username('a')
    with pytest.raises(AccountError):
        security.validate_username('bad name!')
    with pytest.raises(AccountError):
        security.validate_password('short', 'alice')
    with pytest.raises(AccountError):
        security.validate_password('alice-123456', 'Alice-123456')
    digest = security.hash_password(PASSWORD)
    assert PASSWORD not in digest
    assert security.verify_password(PASSWORD, digest)
    assert not security.verify_password('wrong', digest)
    assert not security.verify_password(PASSWORD, 'garbage')
    assert security.lock_seconds(4) == 0
    assert security.lock_seconds(5) == 15 * 60
    assert security.lock_seconds(9) == 60 * 60
