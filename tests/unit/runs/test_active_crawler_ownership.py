"""A browser belongs to the run that bought it.

The stop path's final sweep runs on a side thread that can outlive the click by a reaper's 12 s join
timeout. It used to close "everything registered right now", and by the time it ran the queue could
have started the NEXT run — whose crawl then failed as a dead session, attributed to a workflow
nobody had stopped. The registry now tags each crawler with the record that registered it, so the
late sweep can name one run.
"""

import pytest
from runtime.state import execution_state

pytestmark = pytest.mark.unit


@pytest.fixture
def registry(monkeypatch):
    """A clean registry, with the slot's identity restored afterwards.

    ``execution_state`` is process-wide and shared with every other test, so both the registry and
    the run identity it reads are snapshotted and put back.
    """
    from runtime.state import ActiveCrawlers

    saved = {key: execution_state.get(key) for key in ('active_crawlers', 'run_id', 'running', 'user_id')}
    execution_state['active_crawlers'] = ActiveCrawlers()
    yield execution_state['active_crawlers']
    execution_state.update(saved)


class _FakeCrawler:
    def __init__(self, name):
        self.name = name
        self.closed = False

    def __repr__(self):
        return f'<crawler {self.name}>'


class TestABrowserIsOwnedByTheRunThatOpenedIt:
    def test_the_late_sweep_closes_only_the_run_it_was_asked_about(self, registry):
        from services.runs.settlement import close_active_crawlers

        execution_state['run_id'] = 'run-a'
        execution_state['running'] = True
        first = _FakeCrawler('a')
        registry.add(first)

        # The queue started the next run before the sweep ran.
        execution_state['run_id'] = 'run-b'
        second = _FakeCrawler('b')
        registry.add(second)

        closed = []
        import services.runs.settlement as settlement

        original = settlement.close_login_browser
        settlement.close_login_browser = lambda crawler, quit_timeout=3.0: closed.append(crawler.name)
        try:
            close_active_crawlers(quit_timeout=0, run_id='run-a')
        finally:
            settlement.close_login_browser = original

        assert closed == ['a'], 'run B was never stopped, so its browser must survive the sweep'

    def test_a_sweep_with_no_id_closes_what_no_live_run_owns(self, registry):
        from services.runs.settlement import close_active_crawlers

        execution_state['run_id'] = 'run-a'
        execution_state['running'] = True
        first = _FakeCrawler('a')
        registry.add(first)
        execution_state['run_id'] = 'run-b'
        second = _FakeCrawler('b')
        registry.add(second)

        closed = []
        import services.runs.settlement as settlement

        original = settlement.close_login_browser
        settlement.close_login_browser = lambda crawler, quit_timeout=3.0: closed.append(crawler.name)
        try:
            # B holds the slot: A's browser is the stray one.
            close_active_crawlers(quit_timeout=0)
        finally:
            settlement.close_login_browser = original

        assert closed == ['a']

    def test_take_all_is_one_atomic_read_and_empties_the_registry(self, registry):
        execution_state['run_id'] = 'run-a'
        first = _FakeCrawler('a')
        registry.add(first)
        assert registry.take_all() == [first]
        assert len(registry) == 0, 'the stop route relies on the snapshot being exclusive'

    def test_the_set_surface_the_executors_use_still_works(self, registry):
        execution_state['run_id'] = 'run-a'
        first = _FakeCrawler('a')
        registry.add(first)
        assert first in list(registry) and len(registry) == 1
        registry.discard(first)
        assert len(registry) == 0
        registry.add(first)
        registry.clear()
        assert len(registry) == 0
