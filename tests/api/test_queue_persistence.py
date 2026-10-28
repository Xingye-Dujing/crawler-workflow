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
from state import _RUN_QUEUE

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
