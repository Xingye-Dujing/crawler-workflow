"""The durable-console write-through behind ``state.set_log_sink`` (``engine.run_logs.RunLogWriter``).

The live console lives in memory and is wiped when the next run starts; the whole point of
this writer is that a run's console survives into ``run_store.run_log`` so it can be read
back after a refresh, after the next run, or after a restart. Three properties make that
promise safe, and each is pinned here:

- lines are attributed to the run that printed them — and, in a serial split, a switch of
  ``execution_state['run_id']`` (workflow zero then one then two, each its own record) must
  flush the previous component's batch under ITS id before the next starts, or one run's
  console is quietly filed under another;
- the buffer is bounded and flushed on a cadence (every N lines, and the instant a line is
  an error) so a crash leaves the tail it printed rather than a whole run unwritten;
- a store failure never surfaces into the crawl and never loses the already-printed lines —
  they are kept for a later flush.

``app`` is reached through the ``app_module`` fixture and never imported at module scope.
"""

import copy

import pytest
from runtime import account_context

pytestmark = pytest.mark.unit


class _RecordingStore:
    """Stand-in for ``RunStore`` that only records what ``append_log`` was handed."""

    def __init__(self):
        self.batches = []  # [(run_id, [row, ...])]
        self.accounts = []  # the account context each batch was written under
        self.fail = False

    def append_log(self, run_id, rows):
        if self.fail:
            raise RuntimeError('db down')
        self.batches.append((run_id, list(rows)))
        self.accounts.append(account_context.current())
        return len(rows)


@pytest.fixture
def writer(app_module):
    """A fresh writer + a recording store wired into the module that writes; state put back after."""
    import engine.run_logs

    state_dict = app_module.execution_state
    saved = {key: copy.deepcopy(state_dict[key]) for key in ('run_id', '_wf_names') if key in state_dict}
    # The writer resolves the store through ITS own module global (``engine.run_logs``, the module
    # that owns it since 2026-10-29), so that is where
    # the recording store goes; patching ``app.get_run_store`` would leave the real store in place
    # and every batch assertion here would measure nothing while still passing on a green app.
    real_get_store = engine.run_logs.get_run_store
    store = _RecordingStore()
    engine.run_logs.get_run_store = lambda: store
    w = engine.run_logs.RunLogWriter()
    try:
        yield app_module, w, store, state_dict
    finally:
        engine.run_logs.get_run_store = real_get_store
        for key in ('run_id', '_wf_names'):
            state_dict.pop(key, None)
        state_dict.update(saved)


def _set_run(state, run_id, wf_names=None):
    state['run_id'] = run_id
    state['_wf_names'] = wf_names or {}


class TestAttribution:
    def test_lines_are_file_under_the_run_that_printed_them(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX')
        w.push(['first line', 'second line'], 0, 'info')
        w.flush()
        # Every row is the (ts, wf_idx, wf_name, level, line) tuple the store expects.
        run_id, rows = store.batches[0]
        assert run_id == 'rX'
        assert [r[4] for r in rows] == ['first line', 'second line']
        assert all(r[3] == 'info' for r in rows)

    def test_a_run_id_switch_drains_the_previous_batch_first(self, writer):
        """The serial-split case, and the one that answers "run A's log survives run B".

        Workflow zero, one and two each own a record and set ``execution_state['run_id']``
        as their turn arrives. A batch that spans the switch must be closed under the OLD
        id before any of the new component's lines are appended — otherwise A's console is
        written onto B's record and the viewer for A comes back empty.
        """
        _module, w, store, state = writer
        _set_run(state, 'A')
        w.push(['A line 1', 'A line 2'], 0, 'info')
        _set_run(state, 'B')
        w.push(['B line 1'], 1, 'info')
        w.flush()
        assert [b[0] for b in store.batches] == ['A', 'B']
        assert [r[4] for r in store.batches[0][1]] == ['A line 1', 'A line 2']
        assert [r[4] for r in store.batches[1][1]] == ['B line 1']

    def test_the_workflow_name_is_taken_from_the_shared_buffer(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX', {0: '微博'})
        w.push(['抓取完成'], 0, 'info')
        w.flush()
        assert store.batches[0][1][0][2] == '微博'

    def test_no_run_id_captures_nothing(self, writer):
        # Before a run is armed (or after it is disarmed) there is no record to file under;
        # a stray add_log must not manufacture orphan durable rows.
        _module, w, store, state = writer
        state['run_id'] = ''
        w.push(['orphan?'], 0, 'info')
        w.flush()
        assert store.batches == []


class TestFlushCadence:
    def test_an_error_line_flushes_immediately(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX')
        w.push(['boom'], 0, 'error')
        # The batch is already on disk before the next line — a crash cannot lose the error.
        assert store.batches and store.batches[0][1][0][3] == 'error'

    def test_it_batches_until_the_threshold_then_flushes(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX')
        for _ in range(w.FLUSH_EVERY - 1):
            w.push(['x'], 0, 'info')
        assert store.batches == [], 'under the threshold nothing is written yet'
        w.push(['x'], 0, 'info')  # the FLUSH_EVERY-th line trips it
        written = sum(len(rows) for _rid, rows in store.batches)
        assert written == w.FLUSH_EVERY
        assert w._buf == []

    def test_reset_drops_the_batch_without_writing(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX')
        w.push(['x'], 0, 'info')
        w.reset()
        w.flush()
        assert store.batches == [], 'a new run must not inherit the previous buffer'

    def test_reset_takes_the_writer_lock(self, writer, monkeypatch):
        """reset() swaps ``_buf`` under the writer's OWN lock, the one push() runs under.

        The sink is deliberately called OUTSIDE ``_completed_lock`` (state.py takes it off
        the console lock so a SQLite flush can never re-enter a plain Lock), so the console
        lock serializes nothing here — reset() swapping without the writer's lock let a
        concurrent push append into the list reset had just replaced, and a stopped run's
        durable console lost its tail."""

        _module, w, _store, _state = writer

        class _Probe:
            def __init__(self):
                self.n = 0

            def __enter__(self):
                self.n += 1
                return self

            def __exit__(self, *_exc):
                return False

        probe = _Probe()
        monkeypatch.setattr(w, '_lock', probe)
        w.reset()
        assert probe.n == 1, 'reset must serialize with push under the writer lock'

    def test_parallel_pushes_lose_no_line(self, writer):
        """push() runs OUTSIDE ``_completed_lock``, so parallel writers (pool threads, the
        run thread, requests) race here on their own. Without the writer lock a thread in
        ``_drain`` could swap ``_buf`` while another was appending — a line printed by the
        console vanishing from the durable log (or one batch written twice). Every line
        pushed by N threads must come out exactly once."""
        import threading

        _module, w, store, state = writer
        _set_run(state, 'rX')
        threads, per_thread = 8, 60

        def worker(k):
            for i in range(per_thread):
                w.push([f't{k} l{i}'], 0, 'info')

        runners = [threading.Thread(target=worker, args=(k,)) for k in range(threads)]
        for runner in runners:
            runner.start()
        for runner in runners:
            runner.join()
        w.flush()
        lines = [r[4] for _rid, rows in store.batches for r in rows]
        assert len(lines) == threads * per_thread, 'a lost line is a durable-log hole'
        assert len(set(lines)) == len(lines), 'a duplicated batch is a durable-log lie'


class TestStoreFailure:
    def test_a_failed_flush_keeps_the_lines_for_a_later_try(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX')
        store.fail = True
        w.push(['keep me'], 0, 'info')
        w.flush()  # drains → append_log raises → swallowed, batch retained (with its run id)
        store.fail = False
        w.flush()  # the retained batch goes out on the next attempt
        # Asserted through the STORE, not through a field: the retained lines are kept in a
        # per-run queue now (``_pending``), and what this test is about is that they survive.
        assert store.batches and store.batches[0][0] == 'rX'
        assert store.batches[0][1][0][4] == 'keep me'

    def test_kept_lines_go_back_to_the_run_that_printed_them(self, writer):
        """Retaining a batch must retain its RUN ID with it — and that only bites under a RACE.

        ``_drain`` empties ``_buf`` (line "published before the write") and then opens SQLite, which
        is slow enough for the next run's first line to arrive. That line sets ``_buf_run_id`` to the
        NEW id. If the write then fails, the retained batch is prepended back to the buffer: with the
        old code the id stayed on the new run, so run A's console was written under run B — A's viewer
        comes back empty and B's shows lines B never printed. The injection below IS that window.
        """
        _module, w, store, state = writer
        _set_run(state, 'A')
        w.push(['A line'], 0, 'info')

        real_append = store.append_log

        def failing_append(_run_id, _rows):
            # The next run prints while this (doomed) write is in flight.
            _set_run(state, 'B')
            w.push(['B line'], 1, 'info')
            raise RuntimeError('db down')

        store.append_log = failing_append
        w.flush()  # A's batch fails; B's line is now in the buffer too

        store.append_log = real_append
        w.flush()
        by_run = {}
        for run_id, rows in store.batches:
            by_run.setdefault(run_id, []).extend(row[4] for row in rows)
        assert by_run.get('A') == ['A line'], by_run
        assert 'A line' not in by_run.get('B', []), "run A's console was filed under run B"

    def test_kept_lines_go_back_to_the_account_that_printed_them(self, writer):
        """A kept batch must keep its OWNER, not only its run id.

        ``disarm`` drops ``_account`` at the end of a run; the next account's run then arms the
        writer. The pending batch is still A's console, and writing it under B's context would file
        it in B's ``runs.db`` — the cross-account leak ``_account`` exists to prevent.
        """
        _module, w, store, state = writer
        owner_a = account_context.Account(user_id='user-a', username='a')
        owner_b = account_context.Account(user_id='user-b', username='b')
        _set_run(state, 'A')
        w.arm(owner_a)
        w.push(['A line'], 0, 'info')
        store.fail = True
        w.flush()  # A's batch is kept in _pending
        w.disarm()
        _set_run(state, 'B')
        w.arm(owner_b)
        w.push(['B line'], 0, 'info')
        store.fail = False
        w.flush()

        filed = {run_id: account for (run_id, _rows), account in zip(store.batches, store.accounts, strict=True)}
        assert filed['A'].user_id == 'user-a', "a kept batch was filed under the next run's account"
        assert filed['B'].user_id == 'user-b'

    def test_a_retried_older_batch_is_written_before_the_newer_one(self, writer):
        """Two failed drains must keep print order: the durable log is read by ``seq``, so a
        newer batch placed ahead of the older one reads as a reordered console."""
        _module, w, store, state = writer
        _set_run(state, 'A')
        store.fail = True
        w.push(['older'], 0, 'info')
        w.flush()
        w.push(['newer'], 0, 'info')
        w.flush()
        store.fail = False
        w.flush()
        lines = [row[4] for _run_id, rows in store.batches for row in rows]
        assert lines == ['older', 'newer'], lines

    def test_a_persistently_failing_store_is_bounded(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX')
        store.fail = True
        for _ in range(w.HARD_CAP + 200):
            w.push(['x'], 0, 'info')
        # Never a growing leak: the queue that is actually retained (``_pending``) stays within the
        # hard cap. ``_buf`` is emptied on every attempt, so asserting on it measured nothing.
        retained = sum(len(rows) for _owner, _rid, rows in w._pending)
        assert 0 < retained <= w.HARD_CAP, retained

    def test_a_store_that_logs_while_opening_does_not_deadlock_the_flush(self, writer):
        """``get_run_store()`` can create the store, and creation logs a line that the console
        handler feeds back into ``push`` on the same thread. Holding the writer's non-reentrant
        lock across the lookup froze the run thread and every later flush."""
        import threading

        import engine.run_logs

        _module, w, store, state = writer
        _set_run(state, 'rX')
        w.push(['first'], 0, 'info')
        calls = {'n': 0}

        def opening_store():
            calls['n'] += 1
            if calls['n'] == 1:
                w.push(['opening'], 0, 'info')
            return store

        engine.run_logs.get_run_store = opening_store
        thread = threading.Thread(target=w.flush)
        thread.start()
        thread.join(5)
        assert not thread.is_alive(), 'the flush deadlocked on the store that logged while opening'
        assert [row[4] for row in store.batches[0][1]] == ['first']
        w.flush()
        assert [row[4] for row in store.batches[1][1]] == ['opening']


class TestSinkWiring:
    def test_the_writer_is_a_valid_state_sink(self, app_module):
        """The arm point passes ``writer.push`` into ``state.set_log_sink``; the sink is
        called as ``_log_sink(parts, wf_idx, level)``. A signature drift here is silent in
        the fast tier unless pinned, and would mean no durable log at all."""
        import inspect

        import engine.run_logs

        sig = inspect.signature(engine.run_logs.RunLogWriter.push)
        assert list(sig.parameters) == ['self', 'parts', 'wf_idx', 'level']
