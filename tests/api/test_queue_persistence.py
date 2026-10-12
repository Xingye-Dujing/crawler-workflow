"""The waiting-run queue survives a restart.

Queued requests used to live in memory only, so a server restart silently dropped
every run the user had parked. They are now mirrored to ``runs.db`` on every change
and reloaded at boot. These tests drive that in-memory ↔ disk round trip the way a
restart exercises it: enqueue, clear the in-memory list, and come back through the
loader.
"""

import pytest

pytestmark = pytest.mark.api


def _data(name):
    return {
        'workflow_name': name,
        'workflow': {'nodes': [{'id': 'node-1', 'type': 'source', 'params': {'platform': 'weibo'}}], 'connections': []},
    }


@pytest.fixture(autouse=True)
def _drain(app_module):
    yield
    with app_module._queue_lock:
        app_module._RUN_QUEUE[:] = []


class TestQueueDurability:
    def test_enqueued_requests_are_mirrored_and_come_back_in_order(self, app_module):
        first = app_module._enqueue_run(_data('first'), 'en')['body']['queue_id']
        second = app_module._enqueue_run(_data('second'), 'en')['body']['queue_id']
        assert [e['id'] for e in app_module.queue_snapshot()] == [first, second]

        # A restart: the in-memory list is gone, the mirror is reloaded.
        with app_module._queue_lock:
            app_module._RUN_QUEUE[:] = []
        restored = app_module._load_pending_queue()
        assert restored == 2
        assert [e['id'] for e in app_module.queue_snapshot()] == [first, second]
        assert [e['workflow_name'] for e in app_module._RUN_QUEUE] == ['first', 'second']

    def test_cancelling_one_updates_the_mirror(self, app_module):
        app_module._enqueue_run(_data('a'), 'en')
        keep = app_module._enqueue_run(_data('b'), 'en')['body']['queue_id']
        dropped = app_module._RUN_QUEUE[0]['id']

        assert app_module.cancel_queued(dropped) is True
        with app_module._queue_lock:
            app_module._RUN_QUEUE[:] = []
        app_module._load_pending_queue()
        assert [e['id'] for e in app_module.queue_snapshot()] == [keep]

    def test_clearing_empties_the_mirror_too(self, app_module):
        app_module._enqueue_run(_data('a'), 'en')
        app_module._enqueue_run(_data('b'), 'en')
        assert app_module.clear_queue() == 2
        with app_module._queue_lock:
            app_module._RUN_QUEUE[:] = []
        assert app_module._load_pending_queue() == 0

    def test_reload_does_not_clobber_a_live_in_memory_queue(self, app_module):
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
        with app_module._queue_lock:
            app_module._RUN_QUEUE[:] = [live]
        assert app_module._load_pending_queue() == 0
        assert [e['id'] for e in app_module._RUN_QUEUE] == ['live']
