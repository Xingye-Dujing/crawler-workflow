"""The account registry's rules: bootstrap, login, sessions, lockout and administration."""

import contextlib
import os
import threading
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
    for _ in range(5):
        with pytest.raises(AccountError) as exc:
            _login(service, password='wrong-password')
        # The lock never announces itself to a WRONG password: “登录失败次数过多” is a fact about
        # the account existing, and the lock is doing its job either way.
        assert exc.value.key == 'auth.badCredentials'
    row = service.store.get_user_by_username('admin')
    assert float(row['locked_until']) > time.time(), 'the fifth failure did not lock the account'
    # Even the right password is refused while the lock stands — and only now does it say why.
    with pytest.raises(AccountError) as exc:
        _login(service)
    assert exc.value.key == 'accounts.lockedOut'


def test_a_locked_name_does_not_answer_differently_to_a_wrong_one(service):
    """The lockout refusal sits behind the password check on purpose. Answering it first made the
    public login form enumerate usernames: five attempts on “admin” return “请 15 分钟后再试”
    while five attempts on a name nobody registered return the generic refusal."""
    _bootstrap(service)
    for _ in range(6):
        with pytest.raises(AccountError):
            _login(service, username='admin', password='wrong-password')
    keys = []
    for username in ('admin', 'nobody-at-all'):
        with pytest.raises(AccountError) as exc:
            _login(service, username=username, password='wrong-password')
        keys.append(exc.value.key)
    assert keys == ['auth.badCredentials', 'auth.badCredentials'], keys


def test_unknown_username_answers_the_same_refusal(service):
    _bootstrap(service)
    with pytest.raises(AccountError) as exc:
        _login(service, username='nobody')
    assert exc.value.key == 'auth.badCredentials'
    assert 'nobody' not in str(exc.value)


def test_a_burst_of_wrong_passwords_locks_the_account_not_one_attempt(service, monkeypatch):
    """The failed-attempt counter is added IN THE ROW, not in Python.

    Reading ``failed_attempts``, adding one and writing the total back is the classic lost update:
    a scripted burst of five concurrent guesses all read the same number, so the account ended the
    attack at “1 failure” and “连续 5 次锁 15 分钟” — the whole point of the lock — never arrived.
    The barrier makes the burst real instead of hoping threads interleave: every thread has already
    read the row before any of them increments it.
    """
    from services.accounts import service as accounts_service

    attempts = 5
    accounts_service.reset_throttle()
    _bootstrap(service)
    arrived = threading.Barrier(attempts)

    def everyone_has_read_the_row(_password, _hash):
        arrived.wait(timeout=10)
        return False

    monkeypatch.setattr(security, 'verify_password', everyone_has_read_the_row)

    def guess():
        with contextlib.suppress(AccountError):
            _login(service, password='wrong-password')

    threads = [threading.Thread(target=guess) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    row = service.store.get_user_by_username('admin')
    assert int(row['failed_attempts']) == attempts, row['failed_attempts']
    assert float(row['locked_until']) > time.time(), 'a five-guess burst left the account unlocked'


def test_a_lock_is_never_armed_over_a_login_that_just_succeeded(service):
    """The lock write re-checks the counter it was computed from.

    The increment and the lock are two writes, and a correct login can land between them and zero
    the counter. Arming anyway would refuse the person who just proved the password — so the row
    must still be at that number for the lock to be written."""
    admin = _bootstrap(service)
    user_id = admin['user_id']
    assert service.store.bump_failure(user_id, time.time()) == 1
    service.store.record_login(user_id, time.time(), '127.0.0.1')
    assert service.store.set_locked_until(user_id, time.time() + 900, 1) is False
    assert float(service.store.get_user(user_id)['locked_until']) == 0


def test_the_failure_window_is_bounded_by_size_not_by_politeness(service, monkeypatch):
    """A stranger typing a thousand random usernames used to leave a thousand permanent entries.

    ``_prune`` only ever cleans the key a login just touched, so nothing revisits the entries an
    attacker abandoned: memory grew with the traffic and every later login scanned a longer
    dictionary. The window therefore has a size ceiling, and the entries it drops are the oldest —
    the per-account lock lives in the database and is not affected."""
    from services.accounts import service as accounts_service

    accounts_service.reset_throttle()
    monkeypatch.setattr(accounts_service, 'MAX_WINDOWS', 8)
    throttle = accounts_service._throttle
    for index in range(40):
        throttle.record('10.0.0.1', f'guessed-name-{index}')
    assert len(throttle._hits) <= 8, len(throttle._hits)
    assert throttle._key('10.0.0.1', 'guessed-name-39') in throttle._hits
    assert throttle._key('10.0.0.1', 'guessed-name-0') not in throttle._hits


def test_a_wrong_current_password_is_refused_like_a_wrong_login(service, monkeypatch):
    """The change-password endpoint proved the old password with no window at all.

    Anyone holding a live session — a shared unlocked browser, any same-origin script — could guess
    “当前密码” without limit, and every guess costs this server a scrypt run: an unbounded request
    that is also unbounded CPU. The login window is the same guard, keyed to the account."""
    from services.accounts import service as accounts_service

    accounts_service.reset_throttle()
    monkeypatch.setattr(accounts_service, 'IP_FAILURE_LIMIT', 3)
    _bootstrap(service)
    ticket = _login(service, username='admin', password=PASSWORD)
    for _ in range(3):
        with pytest.raises(AccountError) as exc:
            service.change_password(ticket.account, 'nope', 'a-brand-new-password', ticket.token, ip='10.2.2.2')
        assert exc.value.key == 'accounts.currentPasswordWrong'
    with pytest.raises(AccountError) as exc:
        service.change_password(ticket.account, 'nope', 'a-brand-new-password', ticket.token, ip='10.2.2.2')
    assert exc.value.key == 'accounts.tooManyAttempts'
    # The right answer from a fresh address is still accepted, and it clears that address's window.
    service.change_password(ticket.account, PASSWORD, 'a-brand-new-password', ticket.token, ip='10.3.3.3')
    assert not accounts_service._throttle.blocked('10.3.3.3', 'change:' + ticket.account.user_id)
    accounts_service.reset_throttle()


def test_a_successful_login_does_not_clear_the_change_password_window(service, monkeypatch):
    """A login clears the address+name pair it just proved, not every window at the address.

    The 改密 route files its ``current_password`` guesses under the same ``ip|`` prefix, so a broad
    clear here deleted the only limit on guessing a live session's password: one ordinary login —
    on this account or any other sharing the address — reset it.
    """
    from services.accounts import service as accounts_service

    accounts_service.reset_throttle()
    monkeypatch.setattr(accounts_service, 'IP_FAILURE_LIMIT', 2)
    _bootstrap(service)
    ticket = service.authenticate('admin', PASSWORD, ip='10.9.9.9')
    window = f'change:{ticket.account.user_id}'
    accounts_service._throttle.record('10.9.9.9', window)
    accounts_service._throttle.record('10.9.9.9', window)
    assert accounts_service._throttle.blocked('10.9.9.9', window)
    service.authenticate('admin', PASSWORD, ip='10.9.9.9')
    assert accounts_service._throttle.blocked('10.9.9.9', window), 'a login wiped the 改密 guessing window'
    accounts_service.reset_throttle()


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


def test_the_delete_probe_never_hands_out_the_row(service):
    """:meth:`check_deletable` reads the ``users`` table, so it must answer in the public shape.

    The route discards the value today — one line of luck, not a rule. A row carries
    ``password_hash``, and this service promises never to return one."""
    _bootstrap(service)
    admin = _admin(service)
    bob = service.create_user(admin, 'bob', PASSWORD)
    answer = service.check_deletable(admin, bob['user_id'], 'bob')
    assert 'password_hash' not in answer, sorted(answer)
    assert answer['username'] == 'bob'
    with pytest.raises(AccountError) as exc:
        service.check_deletable(admin, bob['user_id'], 'nobody')
    assert exc.value.key == 'accounts.confirmMismatch'


def test_replacing_the_service_closes_the_store_it_replaced(tmp_path, monkeypatch):
    """Dropping the singleton is not dropping its connection.

    ``AccountsStore`` holds one SQLite handle for its lifetime, so every replacement left a live
    ``accounts.db`` connection (and its ``-wal``/``-shm``) behind — on Windows that is also a
    directory nothing can delete, and across a test session it is one handle per login."""
    import sqlite3

    from services.accounts import service as accounts_service

    database = tmp_path / 'accounts.db'
    monkeypatch.setattr(Config, 'ACCOUNTS_DB', str(database))
    first = AccountService()
    accounts_service.reset_service(first)
    accounts_service.reset_service(AccountService())
    with pytest.raises(sqlite3.ProgrammingError):
        first.store._conn.execute('SELECT 1')
    accounts_service.reset_service()


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


def test_two_admins_cannot_disable_each_other_at_the_same_moment(service):
    """The last-admin rule is a check-then-write; the write lock plus a fresh actor check keeps
    two simultaneous requests from leaving the registry with no enabled administrator."""
    _bootstrap(service)
    first = _admin(service)
    second_row = service.create_user(first, 'root2', PASSWORD, role='admin')
    second = service.authenticate('root2', PASSWORD).account
    barrier = threading.Barrier(2)
    answers = []

    def act(actor, target):
        barrier.wait()
        try:
            service.set_status(actor, target, 'disabled')
        except AccountError as exc:
            answers.append(exc.key)
        else:
            answers.append('ok')

    threads = [
        threading.Thread(target=act, args=(first, second_row['user_id'])),
        threading.Thread(target=act, args=(second, first.user_id)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert answers.count('ok') == 1, answers
    assert answers.count('accounts.adminRequired') == 1, answers
    assert service.store.count_active_admins() == 1


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
