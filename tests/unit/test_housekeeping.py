"""Housekeeping: the retention settings in config.py must be APPLIED, not just declared."""

import logging

import pytest

from services.housekeeping import Housekeeping

pytestmark = pytest.mark.unit


class _FakeRunStore:
    def __init__(self, result=None, error=None):
        self._result = result if result is not None else {'runs': 1, 'cache_entries': 2, 'seen_keys': 3}
        self._error = error
        self.calls = []

    def purge(self, exclude_run_id=''):
        self.calls.append(exclude_run_id)
        if self._error:
            raise self._error
        return dict(self._result)


class _FakeDatasetStore:
    def __init__(self, removed=0, error=None):
        self._removed = removed
        self._error = error
        self.calls = 0

    def purge_unreferenced(self):
        self.calls += 1
        if self._error:
            raise self._error
        return self._removed


class _Clock:
    """Injectable clock: the gate is the whole design, so tests never sleep."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def logs():
    """Capture housekeeping's own log lines (it reports only when it dropped something)."""
    records = []

    class _Grabber(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Grabber()
    logger = logging.getLogger('services.housekeeping')
    # A library logger has no level of its own, so it inherits the root's —
    # which is WARNING unless the app set it. Pin it for the assertion.
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


class TestSweep:
    def test_reports_what_both_stores_dropped(self):
        runs, files = _FakeRunStore(), _FakeDatasetStore(removed=4)
        result = Housekeeping(runs, files).run_now()
        assert result == {'runs': 1, 'cache_entries': 2, 'seen_keys': 3, 'files': 4}
        assert files.calls == 1

    def test_live_run_id_is_passed_through_as_exempt(self):
        runs = _FakeRunStore()
        Housekeeping(runs, _FakeDatasetStore()).run_now(exclude_run_id='abc123')
        assert runs.calls == ['abc123']

    def test_a_list_of_exempt_ids_reaches_the_store_unharmed(self):
        """``str(['abc'])`` is the literal "['abc']", which names no run.

        A serial run closes one record per workflow and hands the sweep after it a list;
        flattening that list on the way through "protected" every record by deleting them.
        """
        runs = _FakeRunStore()
        Housekeeping(runs, _FakeDatasetStore()).run_now(exclude_run_id=['abc123', 'def456'])
        assert runs.calls == [['abc123', 'def456']]

    def test_nothing_exempted_is_not_the_string_none(self):
        runs = _FakeRunStore()
        Housekeeping(runs, _FakeDatasetStore()).run_now()
        assert runs.calls == [''], 'an absent exemption stays absent, not a name to match'

    def test_a_broken_run_store_does_not_stop_the_file_sweep(self):
        """One store failing must not leave the other growing forever — and the
        failure is reported, not swallowed silently."""
        runs = _FakeRunStore(error=OSError('database is locked'))
        files = _FakeDatasetStore(removed=2)
        result = Housekeeping(runs, files).run_now()
        assert files.calls == 1
        assert result['runs'] == 0
        assert result['files'] == 2

    def test_a_broken_file_store_does_not_stop_the_run_sweep(self):
        runs = _FakeRunStore()
        result = Housekeeping(runs, _FakeDatasetStore(error=OSError('locked'))).run_now()
        assert result['runs'] == 1
        assert result['files'] == 0

    def test_a_purge_returning_nothing_is_not_an_error(self):
        result = Housekeeping(_FakeRunStore(result={}), _FakeDatasetStore(removed=None)).run_now()
        assert result == {'runs': 0, 'cache_entries': 0, 'seen_keys': 0, 'files': 0}

    def test_nothing_is_logged_when_nothing_was_dropped(self, logs):
        Housekeeping(_FakeRunStore(result={}), _FakeDatasetStore(removed=0)).run_now()
        assert logs == []

    def test_something_is_logged_when_it_dropped_something(self, logs):
        Housekeeping(_FakeRunStore(), _FakeDatasetStore(removed=1)).run_now()
        assert len(logs) == 1
        assert '1' in logs[0]


class TestGate:
    def test_first_call_fires_because_nothing_has_run_yet(self):
        clock = _Clock()
        runs = _FakeRunStore()
        assert Housekeeping(runs, _FakeDatasetStore(), interval_seconds=60, clock=clock).maybe_run()
        assert runs.calls == ['']

    def test_a_second_call_inside_the_window_is_skipped(self):
        clock = _Clock()
        runs = _FakeRunStore()
        keeper = Housekeeping(runs, _FakeDatasetStore(), interval_seconds=60, clock=clock)
        keeper.maybe_run()
        clock.advance(59)
        assert keeper.maybe_run() is None
        assert runs.calls == ['']

    def test_a_call_past_the_window_fires_again(self):
        clock = _Clock()
        runs = _FakeRunStore()
        keeper = Housekeeping(runs, _FakeDatasetStore(), interval_seconds=60, clock=clock)
        keeper.maybe_run()
        clock.advance(61)
        assert keeper.maybe_run() is not None
        assert runs.calls == ['', '']

    def test_a_failed_sweep_still_consumes_the_window(self):
        """A locked database retried after every single run would be hammered;
        the gate opens on the attempt, not on the success."""
        clock = _Clock()
        runs = _FakeRunStore(error=OSError('database is locked'))
        keeper = Housekeeping(runs, _FakeDatasetStore(), interval_seconds=60, clock=clock)
        keeper.maybe_run()
        clock.advance(1)
        assert keeper.maybe_run() is None
        assert len(runs.calls) == 1

    def test_zero_interval_sweeps_every_time(self):
        clock = _Clock()
        runs = _FakeRunStore()
        keeper = Housekeeping(runs, _FakeDatasetStore(), interval_seconds=0, clock=clock)
        keeper.maybe_run()
        keeper.maybe_run()
        assert len(runs.calls) == 2

    def test_force_ignores_the_gate(self):
        clock = _Clock()
        runs = _FakeRunStore()
        keeper = Housekeeping(runs, _FakeDatasetStore(), interval_seconds=99999, clock=clock)
        keeper.maybe_run()
        assert len(runs.calls) == 1
        keeper.run_now()
        assert len(runs.calls) == 2
