"""``POST /api/workflow/diagnostics`` carries the analysis step contract's answers.

The badge is painted from this payload, so the RULE travels from the step's own contract
(``services/analysis/step_checks``) rather than being re-typed in JavaScript. The route keeps
the same effective-graph rule as the rest of the diagnostics: a switched-off node is not on
the canvas and gets no problem.
"""


def _post(client, nodes, connections=None):
    response = client.post(
        '/api/workflow/diagnostics',
        json={'nodes': {node['id']: node for node in nodes}, 'connections': connections or []},
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_a_blank_required_column_is_reported_as_data(client):
    body = _post(
        client,
        [
            {'id': 'u', 'type': 'upload', 'params': {'dataset_id': 'd1'}},
            {'id': 'a', 'type': 'analysis', 'params': {'operation': 'dedupe_similar', 'column': '  '}},
        ],
        [{'from': 'u', 'to': 'a'}],
    )
    assert body['problems']['a'] == [
        {'code': 'need_param', 'op': 'dedupe_similar', 'param': 'column', 'field': 'settings.column'}
    ]


def test_a_disabled_analysis_node_is_not_judged(client):
    body = _post(
        client,
        [
            {
                'id': 'a',
                'type': 'analysis',
                'params': {'operation': 'dedupe_similar', 'column': '', 'enabled': False},
            }
        ],
    )
    assert body['problems'] == {}


def test_a_complete_node_answers_nothing(client):
    body = _post(
        client,
        [{'id': 'a', 'type': 'analysis', 'params': {'operation': 'dedupe_similar', 'column': '正文'}}],
    )
    assert body['problems'] == {'a': []}
