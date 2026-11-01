"""Tests for the per-run stop handle in engine/executor.py.

This file used to pin a thread-pool scheduler: ``execute`` / ``run_parallel`` / ``run_serial``
ran the nodes of one workflow level concurrently, with failure isolation (a broken task became
``None`` in place) and a stop short-circuit. None of the three was ever CALLED — the level loop
in ``engine.run`` is serial — so the pinned behaviour described a component the product did not
have, and the one thing the Stop route does (``execution_state['executor'].stop()``) wrote to an
event no loop read.

Wiring it now is not the safe fix it looks like. Pool threads inherit neither the starter's
thread-local nor the account context (``engine.run`` says so at the point where it binds them
for its WORKFLOW threads), and ``_wf_local.idx/name`` is what stamps every node's ``component``
and ``component_name`` — the pair the panel groups a parallel record by. Running level nodes on
a pool would silently mis-file that metadata. What a ``parallel`` run actually runs concurrently
is its workflows, one thread each; node-level concurrency is a separate, larger change.

So this file now pins the part that is real and reachable: the stop handle.
"""

import threading

import pytest

from engine.executor import TaskExecutor

pytestmark = pytest.mark.unit


class TestConstruction:
    def test_defaults_are_four_parallel_workers(self):
        executor = TaskExecutor()
        assert (executor.max_workers, executor.mode) == (4, 'parallel')

    def test_settings_are_kept(self):
        executor = TaskExecutor(max_workers=2, mode='serial')
        assert (executor.max_workers, executor.mode) == (2, 'serial')

    def test_a_fresh_run_has_not_been_asked_to_stop(self):
        assert TaskExecutor().stop_requested is False


class TestTheStopHandle:
    """The object the 停止 route reaches for — and the attribute the run loop reads."""

    def test_stop_is_visible_to_the_run_thread(self):
        executor = TaskExecutor()
        executor.stop()
        assert executor.stop_requested is True

    def test_stop_is_a_latch_not_a_counter(self):
        """Pressed twice, or pressed on a run that already ended: still just True."""
        executor = TaskExecutor()
        executor.stop()
        executor.stop()
        assert executor.stop_requested is True

    def test_reset_gives_the_next_run_a_clean_handle(self):
        executor = TaskExecutor()
        executor.stop()
        executor.reset()
        assert executor.stop_requested is False

    def test_stop_does_not_dismantle_anything(self):
        """Called from the request thread while the run thread owns its state: it may only set
        a flag. A Stop that nulled handles under the run is how a run used to walk away from
        work still writing into the console."""
        executor = TaskExecutor()
        executor.stop()
        assert executor.max_workers == 4 and executor.mode == 'parallel'

    def test_the_run_loops_predicate_can_read_it(self):
        """``engine.run._stopping`` asks both doors; ``getattr`` is the second one, so an
        older handle (or a test stub without this attribute) must not be mistaken for a stop."""
        executor = TaskExecutor()
        assert getattr(executor, 'stop_requested', False) is False
        executor.stop()
        assert getattr(executor, 'stop_requested', False) is True

    def test_a_stub_without_the_attribute_reads_as_not_stopping(self):
        """The seam tests patch: ``app.execution_state['executor']`` is replaced with an object
        carrying ``stop()`` only. The loop must tolerate that, not crash on it."""

        class _Stub:
            def stop(self):
                pass

        assert getattr(_Stub(), 'stop_requested', False) is False


class TestNoPoolIsClaimed:
    def test_the_object_spawns_no_threads(self):
        """The guarantee behind deleting the pool: nothing here starts a thread, so a run
        cannot leak one, and the process panel must not report a pool that never existed."""
        before = threading.active_count()
        executor = TaskExecutor()
        executor.stop()
        executor.reset()
        assert threading.active_count() == before

    def test_there_is_no_execute_method_to_call_by_mistake(self):
        """A caller reaching for ``execute`` today must fail loudly rather than quietly take a
        different failure contract than the serial loop it replaced."""
        assert not hasattr(TaskExecutor(), 'execute')
        assert not hasattr(TaskExecutor(), 'run_parallel')
        assert not hasattr(TaskExecutor(), 'run_serial')
