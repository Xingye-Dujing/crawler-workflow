"""The capability tree outside the browser: the MCP server and the terminal CLI.

Both are thin: every answer comes from ``ai.knowledge`` (the skill catalogue) or ``engine.workflow``
(the same validation a run uses), so a terminal or an editor cannot see a capability the product does
not have. The cases below drive the real protocol handler, the real stdio transport and the real CLI.
"""

import io
import json

import pytest
from capabilities_kernel import registry

from services import capability_cli, mcp

pytestmark = pytest.mark.unit


def _call(name, arguments=None):
    response = mcp.handle(
        {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments or {}}}
    )
    return response['result']


def _payload(result):
    return json.loads(result['content'][0]['text'])


class TestTheProtocolHandler:
    def test_initialize_answers_the_protocol_and_the_server(self):
        response = mcp.handle(
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}}
        )
        assert response['result']['protocolVersion'] == '2024-11-05'
        assert response['result']['serverInfo']['name'] == 'caixihui'
        assert response['result']['capabilities'] == {'tools': {}}

    def test_tools_list_names_three_tools_with_schemas(self):
        response = mcp.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        tools = {tool['name']: tool for tool in response['result']['tools']}
        assert set(tools) == {'capabilities_list', 'capabilities_show', 'workflow_validate'}
        for tool in tools.values():
            assert tool['inputSchema']['type'] == 'object'

    def test_a_notification_answers_nothing(self):
        assert mcp.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) is None

    def test_an_unknown_method_is_refused_by_name(self):
        response = mcp.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'resources/list'})
        assert response['error']['code'] == -32601
        assert 'resources/list' in response['error']['message']

    def test_an_unknown_tool_is_refused_by_name(self):
        response = mcp.handle(
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'nope', 'arguments': {}}}
        )
        assert response['error']['code'] == -32602
        assert 'nope' in response['error']['message']


class TestTheToolsAnswerFromTheOneRegistry:
    def test_list_covers_every_kind_and_filters(self):
        rows = _payload(_call('capabilities_list'))['skills']
        assert {row['id'] for row in rows} == {
            f'{manifest.identity.kind}.{manifest.identity.id}'
            for kind in ('node', 'operator', 'chart', 'platform')
            for manifest in registry.manifests(kind)
        }
        charts = _payload(_call('capabilities_list', {'kind': 'chart'}))['skills']
        assert charts and all(row['kind'] == 'chart' for row in charts)

    def test_show_renders_the_same_body_as_skill_load(self):
        from ai import knowledge

        body = _payload(_call('capabilities_show', {'id': 'chart.bar'}))
        assert body['markdown'] == knowledge.load('chart.bar')['markdown']
        assert '## Fields' in body['markdown']

    def test_an_unknown_address_is_a_tool_error_not_a_transport_error(self):
        result = _call('capabilities_show', {'id': 'chart.nope'})
        assert result.get('isError') is True
        assert 'chart.nope' in result['content'][0]['text']

    def test_validate_answers_with_the_engines_own_codes(self):
        good = _payload(
            _call(
                'workflow_validate',
                {
                    'workflow': {
                        'nodes': [{'id': 'n1', 'type': 'name', 'params': {'workflow_name': 'x'}}],
                        'connections': [],
                    }
                },
            )
        )
        assert good['ok'] == (not good['problems']), 'the tool must report the engine verdict as it is'
        bad = _payload(
            _call(
                'workflow_validate',
                {
                    'workflow': {
                        'nodes': [{'id': 'n1', 'type': 'visualize', 'params': {'chart_type': 'nope'}}],
                        'connections': [],
                    }
                },
            )
        )
        assert bad['ok'] is False
        assert any('chart_unknown' in str(problem.get('code')) for problem in bad['problems'])


class TestTheStdioTransport:
    def test_two_lines_get_two_responses_and_a_garbage_line_gets_one(self):
        source = io.StringIO(
            json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
            + '\n'
            + 'not json\n'
            + json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
            + '\n'
        )
        sink = io.StringIO()
        mcp.serve(source, sink)
        responses = [json.loads(line) for line in sink.getvalue().splitlines()]
        assert [row.get('id') for row in responses] == [1, None, 2]
        assert responses[1]['error']['code'] == -32700


class TestTheTerminalCli:
    def test_list_prints_the_declared_ids(self, capsys):
        assert capability_cli.main(['list', '--kind', 'platform']) == 0
        printed = [line.split()[0] for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert set(printed) == {f'platform.{manifest.identity.id}' for manifest in registry.manifests('platform')}

    def test_show_prints_the_skill_body(self, capsys):
        assert capability_cli.main(['show', 'operator.drop_null']) == 0
        assert '# operator.drop_null' in capsys.readouterr().out

    def test_an_unknown_id_exits_nonzero(self, capsys):
        assert capability_cli.main(['show', 'chart.nope']) == 2
        assert 'chart.nope' in capsys.readouterr().err

    def test_validate_reads_a_file_and_reports_the_codes(self, tmp_path, capsys):
        path = tmp_path / 'wf.json'
        path.write_text(
            json.dumps(
                {'nodes': [{'id': 'n1', 'type': 'visualize', 'params': {'chart_type': 'nope'}}], 'connections': []}
            ),
            encoding='utf-8',
        )
        assert capability_cli.main(['validate', str(path)]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload['ok'] is False
