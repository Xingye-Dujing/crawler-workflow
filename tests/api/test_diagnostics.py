"""``POST /api/workflow/diagnostics`` — the schema the edit-time badges read.

The endpoint answers what each node emits (None = unknown) and what it reads, on the
EFFECTIVE graph (a disabled node is not judged) and without running anything. The
properties worth pinning: a crawl stays unknown, a topic_map answers its chart contract,
and a disabled node is dropped exactly as a run would.
"""

import pytest

pytestmark = pytest.mark.api


def test_a_crawl_is_unknown_and_a_topic_map_answers_its_contract(client):
    body = {
        'nodes': {
            's': {'id': 's', 'type': 'source', 'params': {'platform': 'zhihu', 'collect': 'posts'}},
            'a': {'id': 'a', 'type': 'analysis', 'params': {'steps': [{'op': 'topic_map', 'column': '正文'}]}},
        },
        'connections': [{'from': 's', 'to': 'a'}],
        'settings': {},
    }
    r = client.post('/api/workflow/diagnostics', json=body)
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert data['columns']['s'] is None
    assert data['columns']['a'] == ['topic', 'pc1', 'pc2', 'prevalence_pct', 'doc_n', 'feature_words']
    assert data['reads']['a'] == ['正文']


def test_a_disabled_node_is_not_reported(client):
    body = {
        'nodes': {
            'u': {'id': 'u', 'type': 'upload', 'params': {'enabled': False}},
        },
        'connections': [],
        'settings': {},
    }
    data = client.post('/api/workflow/diagnostics', json=body).get_json()
    assert 'u' not in data['columns'], 'a disabled node is not on the canvas a run sees'


def test_a_non_object_json_body_is_a_clean_refusal(client):
    # A body that IS present but is not an object (a JSON array) is refused, not read
    # as "no fields" — that is the case _json_body guards against.
    r = client.post('/api/workflow/diagnostics', json=[1, 2])
    assert r.status_code == 400
