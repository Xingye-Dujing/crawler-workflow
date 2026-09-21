"""Tests for the thread-pool scheduler in engine/executor.py.

The executor is what makes "stop the run" and "a broken node must not kill the
run" work, so the pinned behaviour is about failure isolation and the
stop/resume handshake rather than about speed:

- serial mode keeps results positional (a failure becomes ``None`` *in place*),
- parallel mode is unordered but still returns exactly one entry per task,
- a single-task group never pays for a pool,
- ``stop()`` short-circuits both paths and ``reset()`` lets the next run work.
"""
import threading
import time

import pytest

from engine.executor import TaskExecutor

pytestmark = pytest.mark.unit


def _sleeper(value, delay=0.0):
    def task():
        time.sleep(delay)
        return value

    return task


def _exploding(value):
    def task():
        raise RuntimeError(value)

    return task


def _thread_tagger(bucket):
    def task():
        bucket.append(threading.current_thread().name)
        return bucket

    return task


# ─── construction ──────────────────────────────────────────────────────


class TestConstruction:
    def test_defaults_are_four_parallel_workers(self):
        executor = TaskExecutor()
        assert (executor.max_workers, executor.mode) == (4, 'parallel')

    def test_settings_are_kept(self):
        executor = TaskExecutor(max_workers=2, mode='serial')
        assert (executor.max_workers, executor.mode) == (2, 'serial')


# ─── serial path ───────────────────────────────────────────────────────


class TestRunSerial:
    def test_results_stay_positional(self):
        executor = TaskExecutor(mode='serial')
        assert executor.run_serial([_sleeper(i) for i in range(4)]) == [0, 1, 2, 3]

    def test_failure_becomes_none_at_its_index(self):
        executor = TaskExecutor(mode='serial')
        results = executor.run_serial([_sleeper('a'), _exploding('boom'), _sleeper('c')])
        assert results == ['a', None, 'c']

    def test_tasks_run_in_the_calling_thread(self):
        executor = TaskExecutor(mode='serial')
        names = []
        executor.run_serial([_thread_tagger(names)])
        assert names == [threading.current_thread().name]

    def test_stop_short_circuits_before_the_next_task(self):
        executor = TaskExecutor(mode='serial')
        ran = []

        def task(i):
            def run():
                ran.append(i)
                return i

            return run

        executor.stop()
        assert executor.run_serial([task(0), task(1), task(2)]) == []
        assert ran == []

    def test_a_run_after_reset_works_again(self):
        executor = TaskExecutor(mode='serial')
        executor.run_serial([_sleeper(1)])
        executor.stop()
        assert executor.run_serial([_sleeper(2)]) == []
        executor.reset()
        assert executor.run_serial([_sleeper(3)]) == [3]

    def test_empty_task_list_is_nothing(self):
        assert TaskExecutor().run_serial([]) == []


# ─── parallel path ─────────────────────────────────────────────────────


class TestRunParallel:
    def test_every_task_produces_exactly_one_result(self):
        executor = TaskExecutor(max_workers=3, mode='parallel')
        results = executor.run_parallel([_sleeper(i, delay=0.01) for i in range(6)])
        assert sorted(results) == [0, 1, 2, 3, 4, 5]

    def test_results_are_ordered_by_completion_not_submission(self):
        executor = TaskExecutor(max_workers=2, mode='parallel')
        slow = _sleeper('slow', delay=0.15)
        fast = _sleeper('fast')
        assert executor.run_parallel([slow, fast]) == ['fast', 'slow']

    def test_workers_actually_overlap(self):
        executor = TaskExecutor(max_workers=4, mode='parallel')
        started = threading.Barrier(4, timeout=5)

        def task():
            started.wait()
            return threading.current_thread().name

        names = executor.run_parallel([task for _ in range(4)])
        assert len(set(names)) == 4

    def test_failure_becomes_none_without_losing_siblings(self):
        executor = TaskExecutor(max_workers=2, mode='parallel')
        results = executor.run_parallel([_exploding('a'), _sleeper('ok'), _exploding('c')])
        assert len(results) == 3
        assert results.count(None) == 2
        assert 'ok' in results

    def test_pool_is_closed_afterwards(self):
        executor = TaskExecutor(mode='parallel')
        executor.run_parallel([_sleeper(1)])
        assert executor._pool is None
        assert executor._futures == []

    def test_stop_before_submitting_returns_nothing(self):
        executor = TaskExecutor(mode='parallel')
        executor.stop()
        assert executor.run_parallel([_sleeper(i) for i in range(3)]) == []

    def test_empty_task_list_is_nothing(self):
        executor = TaskExecutor(mode='parallel')
        assert executor.run_parallel([]) == []
        assert executor._pool is None


# ─── grouped execution ─────────────────────────────────────────────────


class TestExecute:
    def test_levels_run_in_order_and_results_are_concatenated(self):
        executor = TaskExecutor(mode='serial')
        groups = [[_sleeper('a'), _sleeper('b')], [_sleeper('c')]]
        assert executor.execute(groups) == ['a', 'b', 'c']

    def test_single_task_group_uses_the_serial_path_even_in_parallel_mode(self):
        executor = TaskExecutor(mode='parallel')
        names = []
        executor.execute([[_thread_tagger(names)]])
        assert names == [threading.current_thread().name]

    def test_multi_task_group_uses_the_pool(self):
        executor = TaskExecutor(max_workers=2, mode='parallel')
        names = []
        executor.execute([[_thread_tagger(names) for _ in range(3)]])
        # Nothing ran in the caller's thread, so the group went through the pool.
        assert len(names) == 3
        assert threading.current_thread().name not in names

    def test_parallel_mode_honours_serial_setting(self):
        executor = TaskExecutor(mode='serial')
        names = []
        executor.execute([[_thread_tagger(names) for _ in range(3)]])
        assert set(names) == {threading.current_thread().name}

    def test_stop_reaches_later_levels(self):
        executor = TaskExecutor(mode='serial')
        first = []

        def marker():
            first.append(1)
            executor.stop()
            return 'x'

        assert executor.execute([[marker], [_sleeper('never')]]) == ['x']
        assert first == [1]

    def test_no_groups_is_no_results(self):
        assert TaskExecutor().execute([]) == []
