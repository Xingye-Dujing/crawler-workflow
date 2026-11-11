"""Who may crawl next: the pool's ordering, its leases, and the exit it picks.

Two mistakes are expensive here and both are cases below: two parallel nodes claiming the
same login (the lease), and an account being declared unusable because its IP is benched
while another healthy exit could carry it ("换 IP 不换号").
"""

import time

import pytest
from runtime import paths
from sessions.cookies import CookieManager

from services.pool import selector, store

pytestmark = pytest.mark.unit


class _Scope:
    """A cookie directory standing in for one signed-in account's tree."""

    def __init__(self, cookie_dir):
        self.cookie_dir = cookie_dir


@pytest.fixture(autouse=True)
def scope(tmp_path, monkeypatch):
    cookie_dir = tmp_path / 'cookies'
    cookie_dir.mkdir()
    fake = _Scope(str(cookie_dir))
    monkeypatch.setattr(paths, 'active', lambda: fake)
    monkeypatch.setattr(store, 'db_path', lambda: str(tmp_path / 'pool.db'))
    # The declared defaults, regardless of the machine's settings.json.
    from services.pool import health

    values = {
        'pool_cooldown_seconds': 7200,
        'pool_network_cooldown_seconds': 300,
        'pool_escalate': False,
        'pool_allow_direct_fallback': False,
    }
    monkeypatch.setattr(health, 'get_setting', lambda key: values.get(key, 0))
    monkeypatch.setattr(selector, 'get_setting', lambda key: values.get(key, False))
    selector.reset_leases()
    yield CookieManager(str(cookie_dir))
    selector.reset_leases()


def _session(manager, account, platform='weibo'):
    manager.save(platform, [{'name': 'SUB', 'value': account, 'domain': '.weibo.com'}], account)
    # Creation order is read off the filesystem, and two writes inside one clock tick are a
    # tie; a real user's second login is minutes later, so the test spends the same gap.
    time.sleep(0.01)


def test_candidates_are_creation_ordered_and_exclude_cooling_accounts(scope):
    _session(scope, 'work')
    _session(scope, 'home')
    assert [c.account for c in selector.candidates('weibo')] == ['work', 'home']

    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    assert [c.account for c in selector.candidates('weibo')] == ['home']
    snapshot = selector.snapshot('weibo')
    assert (snapshot['total'], snapshot['usable']) == (2, 1)
    by_name = {row['account']: row for row in snapshot['accounts']}
    assert by_name['work']['state'] == 'cooling'
    assert by_name['work']['reason'] == 'login_wall'
    assert by_name['work']['cool_until_local']
    assert by_name['home']['state'] == 'ok'


def test_a_claim_leases_the_login_so_a_parallel_node_takes_the_next(scope):
    _session(scope, 'work')
    _session(scope, 'home')
    first = selector.claim('weibo')
    second = selector.claim('weibo')
    assert (first.account, second.account) == ('work', 'home')
    assert selector.claim('weibo') is None
    selector.release(first)
    assert selector.claim('weibo').account == 'work'


def test_an_account_without_a_saved_login_is_not_a_candidate(scope):
    _session(scope, 'work')
    manager = CookieManager(scope.cookie_dir)
    manager.delete('weibo', 'work')
    assert selector.candidates('weibo') == []


def test_an_exit_is_bound_once_and_reused(scope):
    _session(scope, 'work')
    store.save_exit({'name': 'hk03', 'host': '10.0.0.1', 'port': 8080})
    candidate = selector.claim('weibo')
    assert candidate.exit_name == 'hk03'
    assert store.binding_exit_id('weibo', 'work') == candidate.exit_id
    # Sticky: the next run uses the same exit rather than a fresh choice.
    selector.release(candidate)
    again = selector.claim('weibo')
    assert again.exit_id == candidate.exit_id


def test_a_benched_exit_moves_the_same_login_to_another(scope):
    _session(scope, 'work')
    first = store.save_exit({'name': 'hk03', 'host': '10.0.0.1', 'port': 8080})
    second = store.save_exit({'name': 'sg01', 'host': '10.0.0.2', 'port': 8080})
    store.bind('weibo', 'work', first['id'])
    store.mark_cooldown('exit', 'weibo', first['id'], 7200, 'risk')
    candidate = selector.claim('weibo')
    assert candidate.account == 'work'
    assert candidate.exit_id == second['id']
    assert store.binding_exit_id('weibo', 'work') == second['id']


def test_every_exit_benched_refuses_the_account_unless_direct_is_allowed(scope, monkeypatch):
    _session(scope, 'work')
    first = store.save_exit({'host': '10.0.0.1', 'port': 8080})
    store.bind('weibo', 'work', first['id'])
    store.mark_cooldown('exit', 'weibo', first['id'], 7200, 'risk')
    assert selector.candidates('weibo') == []
    # The fallback is read per call, never cached: a run started after the switch flips
    # obeys the new answer, which is the whole point of having it in settings.
    monkeypatch.setattr(selector, 'get_setting', lambda key: key == 'pool_allow_direct_fallback')
    assert [c.account for c in selector.candidates('weibo')] == ['work']


def test_the_exit_pool_is_scoped_to_the_platforms_it_serves(scope):
    _session(scope, 'work')
    store.save_exit({'name': 'cn', 'host': '10.0.0.1', 'port': 8080, 'platforms': 'zhihu'})
    # This exit does not serve weibo, so that crawl goes direct rather than through it.
    assert selector.claim('weibo').exit_id == ''


def test_the_sentinel_is_not_an_account_name():
    assert selector.is_pool_value('@pool') is True
    assert selector.is_pool_value(' pool ') is False
    assert selector.is_pool_value('default') is False
