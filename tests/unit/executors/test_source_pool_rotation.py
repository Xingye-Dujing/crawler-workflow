"""Pool mode at the source node: WHEN a second login may take over.

The rule under test is the one that keeps the ledger honest: a wall met before a single row
was stored is safe to hand to another login, while a wall met after rows exist keeps the
existing "settle partial, continue later" path. The other half is the gate: each attempt
must take the lane of the account it actually uses, or the pool's parallelism becomes a
single queue again.
"""

import contextlib
import time

import pytest
from nodes.context import NodeCall
from nodes.executors import source
from runtime import paths
from sessions.cookies import CookieManager

from crawlers.core.faults import SessionBlockedError
from services.pool import health, selector, store

pytestmark = pytest.mark.unit


class _Scope:
    def __init__(self, cookie_dir):
        self.cookie_dir = cookie_dir


@pytest.fixture(autouse=True)
def scope(tmp_path, monkeypatch):
    cookie_dir = tmp_path / 'cookies'
    cookie_dir.mkdir()
    monkeypatch.setattr(paths, 'active', lambda: _Scope(str(cookie_dir)))
    monkeypatch.setattr(store, 'db_path', lambda: str(tmp_path / 'pool.db'))
    values = {
        'pool_cooldown_seconds': 7200,
        'pool_network_cooldown_seconds': 300,
        'pool_escalate': False,
        'pool_allow_direct_fallback': False,
        'pool_skip_wall_backoff': True,
    }
    monkeypatch.setattr(health, 'get_setting', lambda key: values.get(key, 0))
    monkeypatch.setattr(selector, 'get_setting', lambda key: values.get(key, False))
    selector.reset_leases()
    yield CookieManager(str(cookie_dir))
    selector.reset_leases()


def _login(manager, account, platform='weibo'):
    manager.save(platform, [{'name': 'SUB', 'value': account, 'domain': '.weibo.com'}], account)
    # Creation order is a filesystem fact and two writes in one clock tick are a tie.
    time.sleep(0.01)


def _node(account='@pool'):
    return {
        'id': 'node-4',
        'type': 'source',
        'platform': 'weibo',
        'params': {'platform': 'weibo', 'collect': 'posts', 'account': account},
    }


def _call():
    return NodeCall(
        headless=True,
        current_input=[],
        run_ctx=None,
        upstream=None,
        ctx=None,
        platform_of=None,
        label_of=None,
    )


@pytest.fixture
def lanes(monkeypatch):
    """The gate, recorded instead of taken: no sleeps and no cross-test locks."""
    seen = []

    @contextlib.contextmanager
    def hold(platform, log=None, abort=None, account=''):
        seen.append(account)
        yield False

    monkeypatch.setattr(source.gate, 'hold', hold)
    return seen


def test_a_wall_before_the_first_row_rotates_to_the_next_login(scope, lanes, monkeypatch):
    _login(scope, 'work')
    _login(scope, 'home')
    attempts = []

    def fake(node, headless, ctx=None, upstream=None, account_override=None, proxy=None, pool_mode=False):
        attempts.append((account_override, pool_mode))
        if account_override == 'work':
            raise SessionBlockedError('wall', reason=health.LOGIN_WALL, platform='weibo', account='work')
        return [{'标题': 'ok'}]

    monkeypatch.setattr(source, 'execute_source_node', fake)
    logs = []
    monkeypatch.setattr(source, 'add_log', logs.append)

    rows = source.run(_node(), _call())

    assert rows == [{'标题': 'ok'}]
    assert attempts == [('work', True), ('home', True)]
    # The gate belongs to the login each attempt really used, never to the sentinel.
    assert lanes == ['work', 'home']
    assert store.get_health('account', 'weibo', 'work')['state'] == 'cooling'
    assert store.get_health('account', 'weibo', 'home')['state'] == 'ok'
    # One line says which login was lost, one says which one took over: the console is the
    # only place a user can see a rotation happened at all.
    assert any('work' in line for line in logs), logs
    assert any('home' in line for line in logs), logs


def test_the_attempt_cap_bounds_how_much_of_the_pool_is_spent(scope, lanes, monkeypatch):
    for name in ('work', 'home', 'third'):
        _login(scope, name)
    attempts = []

    def fake(node, headless, ctx=None, upstream=None, account_override=None, proxy=None, pool_mode=False):
        attempts.append(account_override)
        raise SessionBlockedError('wall', reason=health.LOGIN_WALL, platform='weibo', account=account_override)

    monkeypatch.setattr(source, 'execute_source_node', fake)
    monkeypatch.setattr(source.pool, 'max_attempts', lambda: 2)

    with pytest.raises(ValueError) as caught:
        source.run(_node(), _call())

    assert attempts == ['work', 'home']
    # The sentence names every login it spent and the reason it was spent (translated, so
    # the assertion checks the facts it carries, not a particular language's wording).
    assert 'work' in str(caught.value) and 'home' in str(caught.value)
    # The login nobody spent is still healthy.
    assert store.get_health('account', 'weibo', 'third').get('state', 'ok') == 'ok'


def test_an_exhausted_pool_is_refused_by_name_before_any_attempt(scope, lanes, monkeypatch):
    _login(scope, 'work')
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    monkeypatch.setattr(source, 'execute_source_node', lambda *a, **k: pytest.fail('no attempt may start'))
    with pytest.raises(ValueError) as caught:
        source.run(_node(), _call())
    # Named refusal, in the run's language, saying the pool has nothing usable — the fact
    # that matters, not the catalogue key that produced it.
    from i18n import platform_label

    assert platform_label('weibo') in str(caught.value)
    assert lanes == []


def test_a_fixed_account_never_touches_the_pool(scope, lanes, monkeypatch):
    _login(scope, 'work')
    calls = []
    monkeypatch.setattr(source.pool, 'claim', lambda *a, **k: calls.append('claim'))
    monkeypatch.setattr(
        source,
        'execute_source_node',
        lambda node, headless, ctx=None, upstream=None: [{'标题': 'fixed'}],
    )
    assert source.run(_node(account='work'), _call()) == [{'标题': 'fixed'}]
    assert calls == []
    assert lanes == ['work']


def test_a_pool_comment_node_is_left_to_the_comment_engine(scope, lanes, monkeypatch):
    """The comment engine rotates per LINK and takes its own lane there; the source wrapper
    must not take a node-level turn for a fake sentinel account."""
    _login(scope, 'work')
    node = _node()
    node['params']['collect'] = 'comments'
    monkeypatch.setattr(source, 'execute_source_node', lambda node, headless, ctx=None, upstream=None: ['comment'])
    assert source.run(node, _call()) == ['comment']
    assert lanes == []


def test_the_pool_value_is_a_storage_sentinel_not_an_account():
    assert selector.is_pool_value(selector.POOL_VALUE)
    assert not CookieManager.is_account(selector.POOL_VALUE)
