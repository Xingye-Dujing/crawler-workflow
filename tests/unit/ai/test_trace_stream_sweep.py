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
