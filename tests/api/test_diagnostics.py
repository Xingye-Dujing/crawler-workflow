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


def test_a_node_whose_params_are_a_sentence_answers_instead_of_500(client):
    """The crash that blanked every badge: `node_params` assumed an object.

    ``upload.emit_columns`` read ``node_params(node).get('dataset_id')`` and an AI-written
    ``"params": "去重，按评论内容"`` made it raise AttributeError — an HTML 500 the canvas cannot
    parse, so every column badge silently disappeared. The shape is now a per-node problem the
    badge shows, and the rest of the graph is still answered.
    """
    body = {
        'nodes': {
            'u': {'id': 'u', 'type': 'upload', 'params': '去重，按评论内容'},
            'a': {'id': 'a', 'type': 'analysis', 'params': {'steps': [{'op': 'topic_map', 'column': '正文'}]}},
        },
        'connections': [{'from': 'u', 'to': 'a'}],
        'settings': {},
    }
    response = client.post('/api/workflow/diagnostics', json=body)
    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    assert data['columns']['u'] is None
    assert data['columns']['a'] == ['topic', 'pc1', 'pc2', 'prevalence_pct', 'doc_n', 'feature_words']
    assert data['problems']['u'][0]['code'] == 'params_shape'


def test_a_failed_column_check_logs_one_message_and_keeps_the_traceback(client, monkeypatch):
    """A plugin hook that raises is caught, but ``logger.exception(msg, exc)`` used to hand the
    exception as a %-format argument to a message with no placeholder, so logging raised
    "not all arguments converted" and threw away the traceback it was meant to capture."""
    from api import diagnostics

    calls = []
    monkeypatch.setattr(diagnostics, 'compute_columns', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    monkeypatch.setattr(diagnostics.logger, 'exception', lambda *args, **kwargs: calls.append((args, kwargs)))

    body = {'nodes': {'u': {'id': 'u', 'type': 'upload', 'params': {}}}, 'connections': [], 'settings': {}}
    response = client.post('/api/workflow/diagnostics', json=body)
    assert response.status_code == 200
    assert response.get_json()['ok'] is False
    assert len(calls) == 1
    assert len(calls[0][0]) == 1  # only the message; the traceback comes from exc_info, not an arg


def test_diagnostics_carries_the_run_gates_validation(client):
    """The panel badges read the same rule body a run is gated by — one evaluator, two surfaces."""
    body = {
        'nodes': {'s': {'id': 's', 'type': 'source', 'params': {}}},
        'connections': [],
        'settings': {},
    }
    data = client.post('/api/workflow/diagnostics', json=body).get_json()
    validation = data['validation']
    assert validation['entries'][0]['id'] == 's'
    assert validation['entries'][0]['code'] == 'engine.source'
    assert validation['perNode']['s'] == [validation['entries'][0]['message']]
    assert validation['messages'] == [entry['message'] for entry in validation['entries']]


def test_the_run_gate_is_its_own_endpoint_and_answers_by_name(client):
    """`/api/workflow/validate` is what the browser calls before POSTing a run.

    A source with no platform is refused by the matrix rule, and the answer carries both the flat
    list (the toast) and the per-node map (the badges) from that one pass.
    """
    body = {'nodes': {'s': {'id': 's', 'type': 'source', 'params': {}}}, 'connections': [], 'settings': {}}
    r = client.post('/api/workflow/validate', json=body)
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert data['messages'], 'an empty platform is refused'
    assert data['perNode']['s'] == data['messages']
    assert data['entries'][0]['code'] == 'engine.source'


def test_a_clean_canvas_passes_the_run_gate(client):
    body = {
        'nodes': {
            'n': {'id': 'n', 'type': 'name', 'params': {'workflow_name': 'x'}},
            'u': {'id': 'u', 'type': 'upload', 'params': {'dataset_id': 'd1'}},
            'o': {'id': 'o', 'type': 'output', 'params': {'operation': 'save', 'filename': 'x.csv'}},
        },
        'connections': [{'from': 'n', 'to': 'u'}, {'from': 'u', 'to': 'o'}],
        'settings': {},
    }
    data = client.post('/api/workflow/validate', json=body).get_json()
    assert data['messages'] == []
    assert data['perNode'] == {}
