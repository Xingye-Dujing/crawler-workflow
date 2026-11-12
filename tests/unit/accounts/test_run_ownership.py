"""Who owns the one run slot: its context, its queue entries, and its scheduled fires."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from runtime import account_context, state
from runtime.account_context import Account
from scheduling import clock

from engine import run as run_engine
from services.runs import queue

ALICE = Account('u_aaaaaaaaaaaa', 'alice', 'user')
BOB = Account('u_bbbbbbbbbbbb', 'bob', 'user')


@pytest.fixture(autouse=True)
def _clean_globals():
    state.execution_state['user_id'] = ''
    state.execution_state['running'] = False
    state.execution_state['owned_records'] = set()
    state.execution_state['record_owners'] = {}
    with queue.queue_lock:
        queue._RUN_QUEUE.clear()
        queue._MIRRORED_OWNERS.clear()
    yield
    state.execution_state['user_id'] = ''
    state.execution_state['running'] = False
    state.execution_state['owned_records'] = set()
    state.execution_state['record_owners'] = {}
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


def test_an_orphaned_record_is_settled_in_its_owners_store(monkeypatch):
    """A record opened by A must be repaired through A's runs.db even when B's request is
    the one that notices it; the request account's store cannot see A's row."""
    from services.runs import settlement

    seen = []

    class _Store:
        def promote_stale_runs(self, only, note):
            seen.append((account_context.current(), set(only), note))
            return list(only)

    monkeypatch.setattr(settlement, 'get_run_store', _Store)
    monkeypatch.setattr(settlement, 'add_log', lambda _line: None)
    state.execution_state['running'] = False
    state.execution_state['thread'] = None
    state.execution_state['owned_records'] = {'r-alice'}
    state.execution_state['record_owners'] = {'r-alice': ALICE}
    with account_context.use(BOB):
        assert settlement.settle_orphaned_records() == 1
    assert seen and seen[0][0] == ALICE, f'the store was opened as {seen[0][0]}'


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


def test_a_disabled_accounts_queue_slice_is_skipped_not_written(monkeypatch):
    """The store guard refuses a non-active owner; the mirror must skip that slice, not abort.

    ``mirror_queue`` writes one slice per owner inside one ``try``, so an exception from a disabled
    account would leave every other account's queued requests unmirrored.
    """
    from types import SimpleNamespace

    disabled = {'user_id': ALICE.user_id, 'username': 'alice', 'role': 'user', 'status': 'disabled'}
    monkeypatch.setattr(
        'services.accounts.service.get_account_service',
        lambda: SimpleNamespace(store=SimpleNamespace(get_user=lambda _uid: disabled)),
    )
    written = []
    monkeypatch.setattr(queue, 'get_run_store', lambda: SimpleNamespace(save_queue=written.append))
    queue._save_owner_mirror(ALICE.user_id, [_entry('q1', ALICE.user_id)])
    assert written == []


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


def test_the_run_console_does_not_take_another_accounts_lines():
    """The console belongs to the run slot's owner; a request from another account must not
    print into it (or through its durable sink)."""
    saved = (
        list(state.execution_state['logs']),
        state.execution_state['_log_total'],
        dict(state.execution_state['_wf_logs']),
        state.execution_state['user_id'],
    )
    try:
        state.execution_state['logs'] = []
        state.execution_state['_log_total'] = 0
        state.execution_state['_wf_logs'] = {}
        state.execution_state['user_id'] = BOB.user_id
        with account_context.use(ALICE):
            state.add_log('alice must not write Bob’s console')
        assert state.execution_state['logs'] == []
        with account_context.use(BOB):
            state.add_log('bob’s own line')
        assert any('bob’s own line' in line for line in state.execution_state['logs'])
    finally:
        state.execution_state['logs'] = saved[0]
        state.execution_state['_log_total'] = saved[1]
        state.execution_state['_wf_logs'] = saved[2]
        state.execution_state['user_id'] = saved[3]


def test_a_parallel_workflow_thread_runs_as_the_runs_owner(monkeypatch):
    """A pool thread starts with no ContextVar — the wrapper binds the run's account, so its
    exports and run store do not fall back to the checkout-level tree."""
    seen = []

    def fake_single(_engine, _idx, _ctx, _headless):
        seen.append(account_context.scope_key())
        return {}

    monkeypatch.setattr(run_engine, '_run_single_workflow', fake_single)
    previous_lang = state.execution_state.get('lang')
    state.execution_state['lang'] = 'en'
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(run_engine._run_workflow_wrapper, object(), 0, {}, True, {}, threading.Lock(), ALICE).result()
    finally:
        state.execution_state['lang'] = previous_lang
    assert seen == [ALICE.user_id]


def test_the_durable_console_follows_the_run_owner_not_the_printing_thread(monkeypatch):
    """A pool thread that prints the 200th console line has NO account context; the flush must
    still land in the owner's ``runs.db``. Resolving the store per flush wrote an account's batch
    into the checkout-level tree and left a hole in its own durable log."""
    from engine import run_logs

    class _Sink:
        def __init__(self):
            self.scopes = []

        def append_log(self, run_id, rows):
            self.scopes.append(account_context.scope_key())
            return len(rows)

    sink = _Sink()
    monkeypatch.setattr(run_logs, 'get_run_store', lambda: sink)
    previous_run_id = state.execution_state.get('run_id')
    state.execution_state['run_id'] = 'owned-run'
    try:
        writer = run_logs.RunLogWriter()
        writer.arm(ALICE)
        account_context.clear()  # what an unbound LLM pool thread / Stop reaper looks like
        writer.push(['a line printed by nobody’s context'], 0, 'error')
        writer.flush()
        assert sink.scopes and set(sink.scopes) == {ALICE.user_id}, sink.scopes
    finally:
        state.execution_state['run_id'] = previous_run_id
        account_context.clear()


def test_a_gone_account_cannot_open_a_store_and_mint_its_tree(monkeypatch, tmp_path):
    """The central guard: every reader (routes, worker, clock) goes through ``_user_slot``.

    Without it a lingering thread bound to a deleted account ran ``paths.for_user(id).ensure()``
    through the first store getter and recreated ``data/users/<deleted_id>/``.
    """
    from types import SimpleNamespace

    from core.config import Config
    from runtime import stores

    from services.accounts.errors import AccountError

    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr('services.accounts.service.accounts_mode', lambda: True)
    monkeypatch.setattr(
        'services.accounts.service.get_account_service',
        lambda: SimpleNamespace(store=SimpleNamespace(get_user=lambda _uid: None)),
    )
    with account_context.use(ALICE), pytest.raises(AccountError) as caught:
        stores.get_run_store()
    assert caught.value.key == 'accounts.ownerGone'
    assert not (tmp_path / 'users' / ALICE.user_id).exists(), 'the refusal still created a tree'


def test_a_retired_account_stays_closed_even_while_its_row_is_still_there(monkeypatch, tmp_path):
    """``retire_user`` is stamped BEFORE the registry row goes, closing the ``shutil.move`` window."""
    from types import SimpleNamespace

    from core.config import Config
    from runtime import stores

    from services.accounts.errors import AccountError

    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr('services.accounts.service.accounts_mode', lambda: True)
    monkeypatch.setattr(
        'services.accounts.service.get_account_service',
        lambda: SimpleNamespace(
            store=SimpleNamespace(get_user=lambda uid: {'user_id': uid, 'status': 'active'}),
        ),
    )
    try:
        with account_context.use(ALICE):
            stores.retire_user(ALICE.user_id)
            with pytest.raises(AccountError):
                stores.get_run_store()
            assert not (tmp_path / 'users' / ALICE.user_id).exists()
            stores.unretire_user(ALICE.user_id)
            assert stores.get_run_store() is not None
    finally:
        stores.unretire_user(ALICE.user_id)
        stores.release_user(ALICE.user_id)


def test_owner_is_live_asks_the_account_registry(monkeypatch):
    from types import SimpleNamespace

    from runtime import stores

    monkeypatch.setattr('services.accounts.service.accounts_mode', lambda: True)
    rows = {'u_one': {'user_id': 'u_one', 'status': 'active'}}

    def account_service():
        return SimpleNamespace(store=SimpleNamespace(get_user=rows.get))

    monkeypatch.setattr('services.accounts.service.get_account_service', account_service)
    assert stores.owner_is_live(Account('u_one', 'one')) is True
    assert stores.owner_is_live(Account('u_gone', 'gone')) is False
    assert stores.owner_is_live(None) is True
