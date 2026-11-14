"""``runtime.phases``: the Console's phase timings, as data.

Owner scoping is the whole point of the store side: a timing recorded by one account's
crawler must never answer another account's panel. The ring bound is the other: a crawl
records one entry per page/link, and a diagnostic that grows without limit is a leak.
"""

import pytest
from runtime import account_context, phases
from runtime.account_context import Account

pytestmark = pytest.mark.unit


def test_an_entry_carries_the_phase_seconds_and_its_facts():
    entry = phases.record('walk', 11.54, label='xiaohongshu', platform='xiaohongshu', status='ok', rows=3)
    assert entry['phase'] == 'walk'
    assert entry['seconds'] == 11.54, 'seconds are rounded to milliseconds'
    assert entry['status'] == 'ok' and entry['rows'] == 3
    assert phases.snapshot() == [entry]


def test_the_run_and_account_are_stamped_by_the_store(monkeypatch):
    from runtime.state import execution_state

    monkeypatch.setitem(execution_state, 'run_id', 'r_1')
    with account_context.use(Account('u_1', 'a')):
        entry = phases.record('browser', 1.2)
    assert entry['run_id'] == 'r_1' and entry['user_id'] == 'u_1'


def test_snapshot_filters_by_run_and_account():
    with account_context.use(Account('u_a', 'a')):
        phases.record('browser', 1.0)
    with account_context.use(Account('u_b', 'b')):
        other = phases.record('browser', 2.0)
    mine = phases.snapshot(user_id='u_a')
    assert [entry['user_id'] for entry in mine] == ['u_a']
    assert phases.snapshot(user_id='u_b') == [other]
    assert phases.snapshot(user_id='nobody') == []


def test_an_empty_run_id_is_a_value_not_wildcard():
    """A probe's browser is recorded outside any run; asking for run ``''`` must find it."""
    phases.record('browser', 0.5)
    assert len(phases.snapshot(run_id='')) == 1
    assert phases.snapshot(run_id='some-run') == []


def test_the_ring_keeps_the_newest_entries():
    for index in range(phases.MAX_ENTRIES + 5):
        phases.record('walk', index)
    entries = phases.snapshot(limit=phases.MAX_ENTRIES + 10)
    assert len(entries) == phases.MAX_ENTRIES
    assert entries[0]['seconds'] == 5.0, 'the ring must drop the oldest, not the newest'
    assert entries[-1]['seconds'] == float(phases.MAX_ENTRIES + 4)


def test_a_limit_returns_the_tail():
    for index in range(10):
        phases.record('walk', index)
    assert [entry['seconds'] for entry in phases.snapshot(limit=3)] == [7.0, 8.0, 9.0]


def test_reset_forgets_everything():
    phases.record('browser', 1.0)
    phases.reset()
    assert phases.snapshot() == []


def test_a_phase_is_visible_while_it_runs_and_closes_in_place(monkeypatch):
    """A completed-only log shows silence for the minutes the first note takes."""
    entry = phases.begin('walk', 'xiaohongshu', url='https://www.xiaohongshu.com/explore/x')
    running = phases.snapshot()
    assert running[-1]['running'] is True and running[-1]['url'].endswith('/x')

    monkeypatch.setattr(phases.time, 'time', lambda: entry['at'] + 74.2)
    done = phases.end(entry, status='ok', rows=3)
    assert done['running'] is False
    assert done['seconds'] == 74.2, 'a phase that finishes without an explicit clock reads its own start'
    assert done['status'] == 'ok' and done['rows'] == 3
    assert phases.snapshot()[-1]['running'] is False
