"""Spend caps are token facts, not invented money."""

from datetime import UTC, datetime, timedelta


def test_spend_state_names_the_cap_that_was_reached(monkeypatch):
    from ai import costs

    caps = {'ai_budget_conversation_tokens': 100, 'ai_budget_daily_tokens': 200}
    monkeypatch.setattr(costs, 'get_setting', lambda key, *a, **k: caps.get(key, 0))
    monkeypatch.setattr(costs.store, 'token_usage', lambda **_kw: {'tokens': 120, 'cached': 30, 'calls': 3})

    state = costs.spend_state('c1')
    assert state['exceeded'] is True
    assert state['scope'] == 'conversation'
    assert state['spent'] == 120
    assert state['limit'] == 100


def test_a_day_cap_is_reported_when_the_conversation_cap_is_off(monkeypatch):
    from ai import costs

    caps = {'ai_budget_conversation_tokens': 0, 'ai_budget_daily_tokens': 200}
    monkeypatch.setattr(costs, 'get_setting', lambda key, *a, **k: caps.get(key, 0))
    monkeypatch.setattr(costs.store, 'token_usage', lambda **_kw: {'tokens': 250, 'cached': 0, 'calls': 4})

    state = costs.spend_state('c1')
    assert state['scope'] == 'day'
    assert state['spent'] == 250


def test_zero_caps_never_stop_a_turn(monkeypatch):
    from ai import costs

    monkeypatch.setattr(costs, 'get_setting', lambda key, *a, **k: 0)
    monkeypatch.setattr(costs.store, 'token_usage', lambda **_kw: {'tokens': 999999, 'cached': 0, 'calls': 1})

    state = costs.spend_state('c1')
    assert state['exceeded'] is False
    assert state['scope'] == ''


def test_the_day_boundary_asks_the_machine_for_its_timezone():

    from ai.costs import _local_day_start_utc

    start = datetime.fromisoformat(_local_day_start_utc())
    assert start.tzinfo is not None
    assert datetime.now(UTC) - start < timedelta(days=1, hours=1)
