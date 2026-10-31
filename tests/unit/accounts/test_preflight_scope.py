"""The pre-run cookie gate is about ONE account's saved session.

Two failures are pinned here:

* a verdict cached under one account used to answer another (one account's dead cookie refused a
  healthy run, or a live session cleared a gate the dead one should have stopped);
* ``check()`` probes in pool threads, which inherit no ``ContextVar``, so every probe read the
  checkout-level ``data/cookies`` instead of the caller's.
"""

import pytest
from runtime import account_context
from runtime.account_context import Account
from sessions import preflight

ALICE = Account('u_aaaaaaaaaaaa', 'alice', 'user')
BOB = Account('u_bbbbbbbbbbbb', 'bob', 'user')


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch):
    """Answer the questions around the probe without a Chrome."""
    preflight.reset()
    monkeypatch.setattr(preflight, 'knows', lambda platform: True)
    monkeypatch.setattr(preflight, 'is_crawlable', lambda platform: True)
    monkeypatch.setattr(preflight, '_needs_session', lambda platform: True)
    monkeypatch.setattr(preflight, 'has_session_to_test', lambda *a, **k: True)
    monkeypatch.setattr(preflight.profiles, 'profile_dir_for', lambda *a, **k: '')
    yield
    preflight.reset()


def test_a_verdict_is_cached_per_account(monkeypatch):
    seen = []

    def fake_probe(platform, **_kwargs):
        seen.append(account_context.scope_key())
        return {'login_wall': True}

    monkeypatch.setattr(preflight, '_probe_live', fake_probe)

    with account_context.use(ALICE):
        assert preflight.probe('zhihu')['state'] == preflight.EXPIRED
        # Cached for Alice: a second press answers without a second browser.
        assert preflight.probe('zhihu')['state'] == preflight.EXPIRED
    assert seen == [ALICE.user_id]

    with account_context.use(BOB):
        assert preflight.probe('zhihu')['state'] == preflight.EXPIRED
    assert seen == [ALICE.user_id, BOB.user_id], "Bob reused Alice's verdict from another cookie file"


def test_the_parallel_probe_runs_in_the_callers_scope(monkeypatch):
    seen = []

    def fake_probe(platform, **_kwargs):
        seen.append(account_context.scope_key())
        return preflight._verdict(platform, preflight.VALID, probed=True)

    monkeypatch.setattr(preflight, 'probe', fake_probe)
    with account_context.use(ALICE):
        answers = preflight.check(['zhihu'])
    assert answers, 'the check answered nothing'
    assert seen == [ALICE.user_id], 'a pool thread lost the account and read the system cookie dir'
