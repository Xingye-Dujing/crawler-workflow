"""The pool's success/failure contract and the exit a browser is actually given.

Two rules that used to be silently inverted: an empty fact set is "no measurement", never
"the site answered", and a benched exit is replaced for an automatic browser even when the
account is not in pool mode.
"""

import time

import pytest

from services.pool import egress, health, store

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'db_path', lambda: str(tmp_path / 'pool.db'))
    yield


def test_an_empty_fact_set_does_not_clear_a_cooldown():
    store.mark_cooldown('account', 'weibo', 'work', 7200, 'login_wall')
    store.mark_cooldown('exit', 'weibo', 'e1', 7200, 'login_wall')
    before = store.get_health('account', 'weibo', 'work')
    health.observe('weibo', 'work', {}, exit_id='e1')
    assert store.get_health('account', 'weibo', 'work')['state'] == before['state'] == 'cooling'
    assert store.get_health('exit', 'weibo', 'e1')['state'] == 'cooling'
    assert not store.recent_events(5), 'a non-measurement must not write an ok row'
    health.observe('weibo', 'work', {}, exit_id='e1', assume_ok=True)
    assert store.get_health('account', 'weibo', 'work')['state'] == 'ok'
    assert store.get_health('exit', 'weibo', 'e1')['state'] == 'ok'


def test_a_cooling_bound_exit_is_replaced_for_an_automatic_browser(monkeypatch):
    """Only a manually-verified window may look from where the login lives."""
    now = time.time()
    monkeypatch.setattr(store, 'binding_exit_id', lambda platform, account: 'e1')
    monkeypatch.setattr(store, 'exit_secret', lambda exit_id: {'id': exit_id, 'name': exit_id, 'enabled': True})
    monkeypatch.setattr(
        store, 'get_health', lambda kind, platform, subject: {'state': 'cooling', 'cool_until': now + 60}
    )
    monkeypatch.setattr(egress, 'exits_for', lambda platform: [{'id': 'e2'}])
    monkeypatch.setattr(egress, 'healthy_exit', lambda platform, exclude=(): {'id': 'e2'})
    bound = []
    monkeypatch.setattr(store, 'bind', lambda platform, account, exit_id: bound.append((account, exit_id)))

    spec = egress.proxy_for('weibo', 'work')
    assert spec['name'] == 'e2' and bound == [('work', 'e2')]

    # The human door keeps the binding: it is asking what this login sees from where it lives.
    spec = egress.proxy_for('weibo', 'work', even_if_cooling=True)
    assert spec['name'] == 'e1'


def test_an_unverifiable_probe_is_not_recorded_as_a_network_failure():
    """A timeout/captcha/busy profile is "could not be checked", not "the exit is down"."""
    from sessions.preflight import UNKNOWN, _facts_of

    assert _facts_of({'state': UNKNOWN, 'detail': 'captcha'}) == {}
