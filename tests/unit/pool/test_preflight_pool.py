"""The pre-run gate's pool answer: a benched login must not cost a browser.

This is where "don't try it again for two hours" becomes an actual saving rather than a
sentence: the probe reads the stored cooldown and answers without starting Chrome, and a
pool node is refused only when the pool has nothing usable — not because the oldest login
is benched while three others are fine.
"""

import time

import pytest
from runtime import paths
from sessions import preflight
from sessions.cookies import CookieManager

from services.pool import store

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
    preflight.reset()
    manager = CookieManager(str(cookie_dir))
    yield manager
    preflight.reset()


def _login(manager, account, platform='weibo'):
    manager.save(platform, [{'name': 'SUB', 'value': account, 'domain': '.weibo.com'}], account)
    time.sleep(0.01)


def test_a_cooling_account_is_answered_without_opening_a_browser(scope, monkeypatch):
    _login(scope, 'work')
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    monkeypatch.setattr(
        preflight, '_probe_live', lambda *a, **k: pytest.fail('a benched login must not cost a browser')
    )

    verdict = preflight.probe('weibo', account='work')

    assert verdict['state'] == preflight.COOLING
    assert verdict['blocking'] is True
    assert verdict['account'] == 'work'
    assert verdict['detail']


def test_an_empty_pool_is_a_named_no_cookie(scope):
    verdict = preflight.check([{'platform': 'weibo', 'account': '@pool'}])['weibo@@pool']
    assert verdict['state'] == preflight.NO_COOKIE
    assert verdict['blocking'] is True


def test_one_healthy_login_is_enough_for_the_pool(scope, monkeypatch):
    _login(scope, 'work')
    _login(scope, 'home')
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    monkeypatch.setattr(preflight, '_probe_live', lambda *a, **k: pytest.fail('state-based gate opens nothing'))

    verdict = preflight.check([{'platform': 'weibo', 'account': '@pool'}])['weibo@@pool']

    assert verdict['state'] == preflight.VALID
    assert verdict['blocking'] is False
    assert verdict['account'] == '@pool'


def test_every_login_benched_is_a_blocking_pool_verdict(scope):
    _login(scope, 'work')
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    verdict = preflight.check([{'platform': 'weibo', 'account': '@pool'}])['weibo@@pool']
    assert verdict['state'] == preflight.COOLING
    assert verdict['blocking'] is True
    assert verdict['detail']
