"""The durable-console write-through behind ``state.set_log_sink`` (``engine.run.RunLogWriter``).

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

pytestmark = pytest.mark.unit


class _RecordingStore:
    """Stand-in for ``RunStore`` that only records what ``append_log`` was handed."""

    def __init__(self):
        self.batches = []  # [(run_id, [row, ...])]
        self.fail = False

    def append_log(self, run_id, rows):
        if self.fail:
            raise RuntimeError('db down')
        self.batches.append((run_id, list(rows)))
        return len(rows)


@pytest.fixture
def writer(app_module):
    """A fresh writer + a recording store wired into the module that writes; state put back after."""
    import engine.run

    state_dict = app_module.execution_state
    saved = {key: copy.deepcopy(state_dict[key]) for key in ('run_id', '_wf_names') if key in state_dict}
    # The writer resolves the store through ITS own module global (``engine.run``), so that is where
    # the recording store goes; patching ``app.get_run_store`` would leave the real store in place
    # and every batch assertion here would measure nothing while still passing on a green app.
    real_get_store = engine.run.get_run_store
    store = _RecordingStore()
    engine.run.get_run_store = lambda: store
    w = engine.run.RunLogWriter()
    try:
        yield app_module, w, store, state_dict
    finally:
        engine.run.get_run_store = real_get_store
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

    def test_reset_takes_the_console_lock(self, writer, monkeypatch):
        """reset() swaps ``_buf`` while push() appends to it under ``_completed_lock``.

        Doing the swap outside the lock let a concurrent push append into the list reset had
        just replaced, so a stopped run's durable console lost its tail. reset() must acquire
        the same lock flush() uses."""

        _module, w, _store, _state = writer
        import engine.run

        class _Probe:
            def __init__(self):
                self.n = 0

            def __enter__(self):
                self.n += 1
                return self

            def __exit__(self, *_exc):
                return False

        probe = _Probe()
        monkeypatch.setattr(engine.run, '_completed_lock', probe)
        w.reset()
        assert probe.n == 1, 'reset must serialize with push under _completed_lock'


class TestStoreFailure:
    def test_a_failed_flush_keeps_the_lines_for_a_later_try(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX')
        store.fail = True
        w.push(['keep me'], 0, 'info')
        w.flush()  # drains → append_log raises → swallowed, batch retained
        assert [r[4] for r in w._buf] == ['keep me']
        store.fail = False
        w.flush()  # the retained batch goes out on the next attempt
        assert store.batches and store.batches[0][1][0][4] == 'keep me'

    def test_a_persistently_failing_store_is_bounded(self, writer):
        _module, w, store, state = writer
        _set_run(state, 'rX')
        store.fail = True
        for _ in range(w.HARD_CAP + 200):
            w.push(['x'], 0, 'info')
        # Never a growing leak: whatever is retained stays within the hard cap.
        assert len(w._buf) <= w.HARD_CAP


class TestSinkWiring:
    def test_the_writer_is_a_valid_state_sink(self, app_module):
        """The arm point passes ``writer.push`` into ``state.set_log_sink``; the sink is
        called as ``_log_sink(parts, wf_idx, level)``. A signature drift here is silent in
        the fast tier unless pinned, and would mean no durable log at all."""
        import inspect

        import engine.run

        sig = inspect.signature(engine.run.RunLogWriter.push)
        assert list(sig.parameters) == ['self', 'parts', 'wf_idx', 'level']
