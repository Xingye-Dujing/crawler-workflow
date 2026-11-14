"""``GET /api/run/phases``: the Console's timing strip, scoped to the caller.

Two things are asserted that the unit test cannot: the endpoint answers the caller's own
entries only (an account's timings are run facts like any other), and it keeps showing the
last run's tail after the run finished — the panel is a log, not a live gauge.
"""

import pytest
from runtime import account_context, phases
from runtime.account_context import Account
from runtime.state import execution_state

pytestmark = pytest.mark.api


def test_the_endpoint_returns_the_rolling_tail(client):
    phases.record('browser', 1.2, label='xiaohongshu', platform='xiaohongshu')
    body = client.get('/api/run/phases').get_json()
    assert body['ok'] is True
    assert [entry['phase'] for entry in body['phases']] == ['browser']
    assert body['phases'][0]['seconds'] == 1.2


def test_another_account_never_sees_these_timings(client):
    with account_context.use(Account('u_other', 'other')):
        phases.record('browser', 9.9, label='xiaohongshu')
    body = client.get('/api/run/phases').get_json()
    assert body['phases'] == [], "a foreign account read this account's phase log"


def test_the_last_run_stays_visible_after_it_finishes(client, monkeypatch):
    monkeypatch.setitem(execution_state, 'run_id', 'r_done')
    monkeypatch.setitem(execution_state, 'running', False)
    phases.record('crawl', 55.0, label='xiaohongshu', platform='xiaohongshu', rows=2)
    body = client.get('/api/run/phases').get_json()
    assert body['running'] is False
    assert [entry['seconds'] for entry in body['phases']] == [55.0], (
        'the strip blanked the timings the user opened it to read'
    )
