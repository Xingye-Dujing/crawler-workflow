"""The streaming sweep must not interrupt a node-trace row still being written by a run worker."""

import pytest

pytestmark = pytest.mark.unit


def test_mark_interrupted_spares_node_trace_streams(data_root):
    from ai import store

    conversation = store.create_conversation('ollama', 'qwen', 'node_trace')
    cid = conversation['id']
    normal = store.append_message(cid, 'assistant', content='a', status='streaming', meta={'kind': 'turn'})
    traced = store.append_message(
        cid,
        'assistant',
        content='b',
        status='streaming',
        meta={'kind': 'trace_call', 'node_trace_stream': True},
    )

    count = store.mark_interrupted(cid)
    assert count == 1, 'only the ordinary streaming row is interrupted'

    assert store.get_message(normal['id'])['status'] == 'interrupted'
    assert store.get_message(traced['id'])['status'] == 'streaming'


def test_mark_interrupted_reaps_an_orphaned_node_trace_stream(data_root):
    """A dead worker leaves its streaming row forever; staleness is the heartbeat that finds it."""
    from datetime import UTC, datetime, timedelta

    from ai import store

    conversation = store.create_conversation('ollama', 'qwen', 'node_trace')
    cid = conversation['id']
    orphan = store.append_message(
        cid,
        'assistant',
        content='half',
        status='streaming',
        meta={'kind': 'trace_call', 'node_trace_stream': True},
    )
    # Simulate a worker killed mid-call: no further update has touched row for over a minute.
    stale = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    from ai.store import connect

    with connect() as conn:
        conn.execute('UPDATE messages SET updated_at = ? WHERE id = ?', (stale, orphan['id']))

    assert store.mark_interrupted(cid) == 1
    assert store.get_message(orphan['id'])['status'] == 'interrupted'
