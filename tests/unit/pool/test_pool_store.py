"""The pool's durable verdicts: what a cooldown means, and what survives a restart.

The premise is a platform control that lasts hours, so the expensive mistake is trying again
too soon. These cases pin the three answers that decision rests on — cooling, expired
cooling and a manual stop — plus the exit inventory's one hard rule: a credential never
travels back out of the store.
"""

import time

import pytest

from services.pool import store

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_pool(tmp_path, monkeypatch):
    db = tmp_path / 'pool.db'
    monkeypatch.setattr(store, 'db_path', lambda: str(db))
    yield
    for suffix in ('', '-wal', '-shm'):
        path = tmp_path / f'pool.db{suffix}'
        if path.exists():
            path.unlink()


@pytest.mark.skipif(__import__('os').name == 'nt', reason='POSIX mode bits; Windows uses ACLs')
def test_the_credential_database_is_private_to_its_owner(tmp_path):
    """It stores paid-proxy usernames and passwords in clear; umask 022 would publish it."""
    import os as _os

    path = tmp_path / 'pool.db'
    store.connect().close()
    assert _os.stat(path).st_mode & 0o077 == 0, oct(_os.stat(path).st_mode)
    assert _os.stat(tmp_path).st_mode & 0o077 == 0, oct(_os.stat(tmp_path).st_mode)


def test_an_expired_cooldown_reads_as_usable_without_a_sweeper():
    store.mark_cooldown('account', 'weibo', 'work', 60, 'login_wall')
    row = store.get_health('account', 'weibo', 'work')
    assert row['state'] == 'cooling'
    assert row['cool_until_local']
    # The clock, not a background thread, is what ends a cooldown: a server switched off
    # overnight must wake with every expired term already gone.
    from services.pool import health

    assert health.effective_state(row) == 'cooling'
    assert health.effective_state(row, now=time.time() + 61) == 'ok'


def test_a_manual_stop_never_expires_on_a_clock():
    store.set_disabled('account', 'weibo', 'work', True, note='banned for good')
    row = store.get_health('account', 'weibo', 'work')
    from services.pool import health

    assert row['state'] == 'disabled'
    assert health.effective_state(row, now=time.time() + 10 * 86400) == 'disabled'
    store.set_disabled('account', 'weibo', 'work', False)
    assert store.get_health('account', 'weibo', 'work')['state'] == 'ok'


def test_reset_clears_the_term_and_the_strikes():
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    assert store.get_health('account', 'weibo', 'work')['strikes'] == 2
    store.reset('account', 'weibo', 'work')
    row = store.get_health('account', 'weibo', 'work')
    assert row['state'] == 'ok' and row['strikes'] == 0 and not row['cool_until']


def test_success_clears_the_cooldown():
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    store.mark_ok('account', 'weibo', 'work')
    row = store.get_health('account', 'weibo', 'work')
    assert row['state'] == 'ok' and row['strikes'] == 0


def test_an_exit_password_never_leaves_the_store():
    row = store.save_exit({'name': 'hk03', 'host': '10.0.0.1', 'port': 8080, 'username': 'u', 'password': 'p'})
    assert row['has_auth'] is True
    assert 'password' not in row and 'username' not in row
    assert store.exit_secret(row['id'])['password'] == 'p'
    # An edit that leaves the password blank keeps the stored one: the panel never receives
    # it, so a save that always posted the blank field would erase a working credential.
    store.save_exit({'id': row['id'], 'name': 'hk03', 'host': '10.0.0.2', 'port': 8080})
    assert store.exit_secret(row['id'])['password'] == 'p'
    assert store.get_exit(row['id'])['host'] == '10.0.0.2'


def test_a_deleted_exit_takes_its_bindings_and_health_with_it():
    row = store.save_exit({'host': '10.0.0.1', 'port': 8080})
    store.bind('weibo', 'work', row['id'])
    store.mark_cooldown('exit', 'weibo', row['id'], 60, 'risk')
    assert store.delete_exit(row['id']) is True
    assert store.binding_exit_id('weibo', 'work') == ''
    assert store.get_health('exit', 'weibo', row['id']) == {}


def test_the_event_trail_names_the_pair_and_the_run():
    store.record_event(kind='login_wall', platform='weibo', account='work', run_id='r1', node_id='n2', rows=0)
    events = store.recent_events(10)
    assert events[0]['platform'] == 'weibo'
    assert events[0]['account'] == 'work'
    assert events[0]['run_id'] == 'r1'
    assert events[0]['at_local']
