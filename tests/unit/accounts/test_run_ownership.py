"""Who owns the one run slot: its context, its queue entries, and its scheduled fires."""

from datetime import datetime

import pytest
from runtime import account_context, state
from runtime.account_context import Account
from scheduling import clock

from services.runs import queue

ALICE = Account('u_aaaaaaaaaaaa', 'alice', 'user')
BOB = Account('u_bbbbbbbbbbbb', 'bob', 'user')


@pytest.fixture(autouse=True)
def _clean_globals():
    state.execution_state['user_id'] = ''
    state.execution_state['running'] = False
    with queue.queue_lock:
        queue._RUN_QUEUE.clear()
        queue._MIRRORED_OWNERS.clear()
    yield
    state.execution_state['user_id'] = ''
    state.execution_state['running'] = False
    with queue.queue_lock:
        queue._RUN_QUEUE.clear()
        queue._MIRRORED_OWNERS.clear()
    account_context.clear()


def test_a_run_belongs_to_the_account_that_claimed_it():
    assert state.run_is_foreign() is False
    with account_context.use(ALICE):
        state.execution_state['user_id'] = ALICE.user_id
        assert state.run_is_foreign() is False
    with account_context.use(BOB):
        assert state.run_is_foreign() is True
    account_context.clear()
    assert state.run_is_foreign() is True


def _entry(queue_id: str, user_id: str) -> dict:
    return {
        'id': queue_id,
        'workflow_name': queue_id,
        'nodes': 1,
        'data': {},
        'lang': 'zh',
        'queued_at': '2026-01-01T00:00:00',
        'user_id': user_id,
        'username': '',
    }


def test_the_queue_lists_and_cancels_only_your_own_requests():
    with queue.queue_lock:
        queue._RUN_QUEUE.extend([_entry('a1', ALICE.user_id), _entry('b1', BOB.user_id)])
    with account_context.use(ALICE):
        assert [row['id'] for row in queue.queue_snapshot()] == ['a1']
        assert queue.cancel_queued('b1') is False
        assert queue.cancel_queued('a1') is True
        assert queue.queue_snapshot() == []
    with account_context.use(BOB):
        assert [row['id'] for row in queue.queue_snapshot()] == ['b1']
        assert queue.clear_queue() == 1
    assert queue.queue_snapshot() == []


def test_a_queued_request_whose_account_is_gone_is_dropped():
    # No account registry exists in this test, so the owner cannot be resolved.
    started = []
    with queue.queue_lock:
        queue._RUN_QUEUE.append(_entry('orphan', 'u_0123456789ab'))
    queue.drain_queue(lambda data, lang: started.append(data) or {'status': 200, 'body': {'ok': True, 'run_id': 'x'}})
    assert not started
    assert queue.queue_snapshot() == []


def test_the_clock_reads_each_accounts_schedule_in_its_own_context(monkeypatch):
    seen = []
    task = {'id': 't1', 'name': 'nightly', 'enabled': True, 'next_run': 'whenever', 'lang': 'en'}
    monkeypatch.setattr(clock, '_scopes', lambda: [ALICE, BOB])
    monkeypatch.setattr(clock.store, 'all_tasks', lambda: [task])
    monkeypatch.setattr(clock.store, 'stamp', lambda value: datetime(2026, 1, 1))
    monkeypatch.setattr(clock.store, 'record_event', lambda *args, **kwargs: {})

    def fake_starter(_task, _manual):
        seen.append(account_context.scope_key())
        return {'ok': True, 'run_id': 'r1'}

    clock.set_run_starter(fake_starter)
    try:
        fired = clock.tick(datetime(2026, 1, 2))
    finally:
        clock.set_run_starter(None)
    assert fired, 'the clock saw no due task'
    assert seen == [ALICE.user_id, BOB.user_id]
