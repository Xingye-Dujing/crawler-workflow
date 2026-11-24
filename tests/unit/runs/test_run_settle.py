"""The attempt's verdict: settle first, then count — and the four rules that count encodes.

``engine.run.settle`` is the small module the 400-line worker body was hiding: which nodes count as
broken, what a stop is allowed to blame, and the one sentence the console prints. Each rule here
cost a bug once, so each gets its own case rather than being read off the finish line in an API test.
"""

import pytest
from runtime.state import execution_state

from engine.run.settle import finish_line, settle_attempt, verdict
from i18n import t
from services.runs.store import (
    NODE_DONE,
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_SKIPPED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_INTERRUPTED,
)

pytestmark = pytest.mark.unit


class _Store:
    """The two store questions the verdict asks, and a record of what it was told to settle."""

    def __init__(self, rows: dict):
        self.rows = rows
        self.settled: list = []

    def settle_nodes(self, rid: str) -> None:
        self.settled.append(rid)

    def node_statuses(self, rid: str) -> dict:
        return self.rows.get(rid, {})


@pytest.fixture
def attempt(monkeypatch):
    """This attempt's population, in the shape the worker leaves it."""
    monkeypatch.setitem(execution_state, 'attempted_nodes', {'a', 'b', 'c'})
    monkeypatch.setitem(execution_state, 'stopped_node_ids', set())
    monkeypatch.setitem(execution_state, 'completed_nodes', 1)
    monkeypatch.setitem(execution_state, 'total_nodes', 3)
    monkeypatch.setitem(execution_state, 'skipped_nodes', 0)
    monkeypatch.setitem(execution_state, 'failed_nodes', 0)
    monkeypatch.setitem(execution_state, 'outcome', '')
    return execution_state


class TestSettlingTheRecords:
    def test_every_record_is_settled_and_its_statuses_merged(self, attempt):
        store = _Store({'r1': {'a': {'status': NODE_DONE}}, 'r2': {'b': {'status': NODE_DONE}}})
        settled = settle_attempt(store, ['r1', 'r2'], still_running=True)
        assert store.settled == ['r1', 'r2'], 'a serial split writes one record per workflow; both must settle'
        assert settled['statuses'] == {'a': {'status': NODE_DONE}, 'b': {'status': NODE_DONE}}
        assert settled['broken'] == 0

    def test_the_settled_numbers_land_on_the_shared_state(self, attempt):
        store = _Store({'r1': {'a': {'status': NODE_FAILED}}})
        settle_attempt(store, ['r1'], still_running=True)
        assert attempt['failed_nodes'] == 1
        assert attempt['outcome'] == 'failed'


class TestWhatCountsAsBroken:
    def test_a_failed_node_is_broken(self, attempt):
        store = _Store({'r1': {'a': {'status': NODE_FAILED}}})
        assert settle_attempt(store, ['r1'], still_running=True)['broken'] == 1

    def test_a_partial_node_is_broken_too(self, attempt):
        """Half a table is a gap 继续 must offer: PARTIAL is not "done enough"."""
        store = _Store({'r1': {'b': {'status': NODE_PARTIAL}}})
        assert settle_attempt(store, ['r1'], still_running=True)['broken'] == 1

    def test_a_node_the_stop_cut_is_not_a_failure(self, attempt):
        attempt['stopped_node_ids'].add('a')
        store = _Store({'r1': {'a': {'status': NODE_PARTIAL}}})
        settled = settle_attempt(store, ['r1'], still_running=False)
        assert settled['stopped'] == {'a'}
        assert settled['broken'] == 0, 'the user pressed Stop; the verdict may not call that a broken workflow'

    def test_a_node_this_attempt_never_visited_is_not_counted(self, attempt):
        """A node deleted from the canvas keeps its old FAILED row; blaming this run for it is the bug."""
        store = _Store({'r1': {'a': {'status': NODE_DONE}, 'gone': {'status': NODE_FAILED}}})
        assert settle_attempt(store, ['r1'], still_running=True)['broken'] == 0

    def test_a_skipped_node_is_neither_done_nor_broken(self, attempt):
        store = _Store({'r1': {'c': {'status': NODE_SKIPPED}}})
        assert settle_attempt(store, ['r1'], still_running=True)['broken'] == 0


class TestTheFinishLine:
    def test_it_names_the_skipped_stopped_and_failed_counts(self, attempt):
        line = finish_line(stopped={'a'}, broken=2)
        assert t('run.finished.stopped', n=1) in line
        assert t('run.finished.failed', n=2) in line
        assert line.index(t('run.finished.stopped', n=1)) < line.index(t('run.finished.failed', n=2))

    def test_a_clean_run_has_no_extra_clause(self, attempt):
        clean = t('run.finished', done=1, total=3)
        assert finish_line(stopped=set(), broken=0) == clean

    def test_skipped_nodes_get_their_own_clause(self, attempt):
        attempt['skipped_nodes'] = 2
        assert t('run.finished.skipped', n=2) in finish_line(stopped=set(), broken=0)


class TestTheVerdict:
    def test_a_stop_outranks_a_failure(self):
        assert verdict(still_running=False, broken=3) == RUN_INTERRUPTED

    def test_one_broken_node_downgrades_the_run(self):
        assert verdict(still_running=True, broken=1) == RUN_FAILED

    def test_nothing_broken_is_completed(self):
        assert verdict(still_running=True, broken=0) == RUN_COMPLETED
