"""The waiting-run queue survives a restart.

Queued requests used to live in memory only, so a server restart silently dropped
every run the user had parked. They are now mirrored to ``runs.db`` on every change
and reloaded at boot. These tests drive that in-memory ↔ disk round trip the way a
restart exercises it: enqueue, clear the in-memory list, and come back through the
loader.

They speak to :mod:`services.runs.queue` — where the queue lives now — rather than
through ``app``: the drain that *starts* a waiting request is a different seam and is
exercised in ``test_api_hardening``.
"""

import pytest
from runtime import account_context
from runtime.account_context import Account
from runtime.state import _RUN_QUEUE

from services.runs import queue as run_queue

pytestmark = pytest.mark.api


def _data(name):
    return {
        'workflow_name': name,
        'workflow': {'nodes': [{'id': 'node-1', 'type': 'source', 'params': {'platform': 'weibo'}}], 'connections': []},
    }


def _empty_queue():
    """Wipe the in-memory list the way a restart leaves it, lock included."""
    with run_queue.queue_lock:
        _RUN_QUEUE[:] = []


@pytest.fixture(autouse=True)
def _drain():
    yield
    _empty_queue()


class TestQueueDurability:
    def test_enqueued_requests_are_mirrored_and_come_back_in_order(self):
        first = run_queue.enqueue_run(_data('first'), 'en')['body']['queue_id']
        second = run_queue.enqueue_run(_data('second'), 'en')['body']['queue_id']
        assert [e['id'] for e in run_queue.queue_snapshot()] == [first, second]

        # A restart: the in-memory list is gone, the mirror is reloaded.
        _empty_queue()
        assert run_queue.load_pending_queue() == 2
        assert [e['id'] for e in run_queue.queue_snapshot()] == [first, second]
        assert [e['workflow_name'] for e in _RUN_QUEUE] == ['first', 'second']

    def test_cancelling_one_updates_the_mirror(self):
        run_queue.enqueue_run(_data('a'), 'en')
        keep = run_queue.enqueue_run(_data('b'), 'en')['body']['queue_id']
        dropped = _RUN_QUEUE[0]['id']

        assert run_queue.cancel_queued(dropped) is True
        _empty_queue()
        run_queue.load_pending_queue()
        assert [e['id'] for e in run_queue.queue_snapshot()] == [keep]

    def test_clearing_empties_the_mirror_too(self):
        run_queue.enqueue_run(_data('a'), 'en')
        run_queue.enqueue_run(_data('b'), 'en')
        assert run_queue.clear_queue() == 2
        _empty_queue()
        assert run_queue.load_pending_queue() == 0

    def test_reload_does_not_clobber_a_live_in_memory_queue(self):
        # The guard against an older disk snapshot overwriting current work: if memory
        # already holds a request, the loader leaves it alone.
        live = {
            'id': 'live',
            'workflow_name': 'live',
            'nodes': 1,
            'queued_at': 'now',
            'data': _data('live'),
            'lang': 'en',
        }
        with run_queue.queue_lock:
            _RUN_QUEUE[:] = [live]
        assert run_queue.load_pending_queue() == 0
        assert [e['id'] for e in _RUN_QUEUE] == ['live']

    def test_a_payload_that_could_never_run_is_refused_at_the_door(self):
        """Checked when the button was pressed, not minutes later in an unwatched thread —
        and a refused request must not occupy a slot either way."""
        answer = run_queue.enqueue_run({'workflow': {'nodes': ['not a node dict']}}, 'en')
        assert answer['status'] == 400
        assert answer['body']['ok'] is False
        assert _RUN_QUEUE == [], 'the refusal still entered the queue'

    def test_the_cap_refuses_by_naming_the_number(self, monkeypatch):
        monkeypatch.setattr(run_queue, 'QUEUE_MAX', 1)
        assert run_queue.enqueue_run(_data('a'), 'en')['body']['queued'] is True
        second = run_queue.enqueue_run(_data('b'), 'en')
        assert second['status'] == 409
        assert '1' in second['body']['error'], second

    def test_the_cap_is_per_owner_not_shared(self, monkeypatch):
        """One account filling its own slots must not refuse another account's request."""
        alice = Account('u_aaaaaaaaaaaa', 'alice')
        bob = Account('u_bbbbbbbbbbbb', 'bob')
        monkeypatch.setattr(run_queue, 'QUEUE_MAX', 1)
        monkeypatch.setattr(run_queue, 'mirror_queue', lambda: None)
        with account_context.use(alice):
            assert run_queue.enqueue_run(_data('a1'), 'en')['body']['queued'] is True
            assert run_queue.enqueue_run(_data('a2'), 'en')['status'] == 409
        with account_context.use(bob):
            assert run_queue.enqueue_run(_data('b1'), 'en')['body']['queued'] is True
        assert len(_RUN_QUEUE) == 2

    def test_a_popped_entry_names_its_owner_until_the_claim(self, monkeypatch):
        monkeypatch.setattr(run_queue, 'mirror_queue', lambda: None)
        alice = Account('u_aaaaaaaaaaaa', 'alice')
        monkeypatch.setattr(run_queue, '_account_for', lambda entry: alice)
        with account_context.use(alice):
            run_queue.enqueue_run(_data('a1'), 'en')
        seen = []

        def start_run(_data, _lang):
            seen.append(run_queue.draining_owner())
            return {'status': 200, 'body': {'ok': True, 'run_id': 'r1'}}

        run_queue.drain_queue(start_run)
        assert seen == ['u_aaaaaaaaaaaa']
        assert run_queue.draining_owner() == ''

    def test_a_drained_request_that_was_parked_again_is_not_duplicated(self):
        """A lost race hands the entry back; a start path that ALREADY re-parked it must not
        also get the original pushed back. Two entries for one button press means the canvas is
        crawled (and paid for) twice, and both entries survive the restart.

        And the ONE entry that stays keeps the id the caller was given: the panel holds that id in its
        取消 button, so a re-park under a fresh id is a request the user can no longer cancel, waiting
        behind the canvases that arrived after it."""
        first = run_queue.enqueue_run(_data('mine'), 'en')['body']['queue_id']
        parked = {
            'id': 'fresh',
            'workflow_name': 'fresh',
            'nodes': 1,
            'data': _data('fresh'),
            'lang': 'en',
            'queued_at': '2026-01-01T00:00:01',
            'user_id': '',
            'username': '',
        }

        def start_but_lose_the_race(_data_, _lang):
            # What ``begin_run`` does when another run holds the slot: it queues the payload
            # itself (mirror included, exactly as ``enqueue_run`` does) and answers ``queued``.
            with run_queue.queue_lock:
                _RUN_QUEUE.append(parked)
            run_queue.mirror_queue()
            return {'status': 200, 'body': {'ok': True, 'queued': True, 'queue_id': 'fresh'}}

        run_queue.drain_queue(start_but_lose_the_race)
        assert [e['id'] for e in _RUN_QUEUE] == [first], 'the same request is queued twice'
        _empty_queue()
        run_queue.load_pending_queue()
        assert [e['id'] for e in _RUN_QUEUE] == [first], 'the duplicate reached the disk mirror'
