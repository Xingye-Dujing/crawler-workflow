"""The capability tree over the Model Context Protocol — one registry, three tools.

An MCP client (an editor, another agent) must see exactly what this product declares: the same L1
catalogue ``skill_catalog`` reads, the same L2 body ``skill_load`` renders, and the same pre-run
validation ``/api/workflow/validate`` answers. Nothing here rewords a capability: the tools call
``ai.knowledge`` and ``engine.workflow``, so a manifest change reaches MCP in the same commit.

The module is transport-free: :func:`handle` answers one JSON-RPC request, and :func:`serve` reads
line-delimited JSON from a stream pair. ``tools/mcp_server.py`` is the stdio entry point, so the
protocol stays testable without a subprocess.
"""

from __future__ import annotations

import json

PROTOCOL_VERSION = '2024-11-05'
SERVER_INFO = {'name': 'caixihui', 'version': '1.0.0'}

#: The tools this server offers, declared once. ``inputSchema`` is a JSON Schema subset; the names
#: are stable addresses a client stores, so they change only with a protocol decision.
TOOLS = (
    {
        'name': 'capabilities_list',
        'description': 'List the capability catalogue (nodes, analysis operators, chart types and crawl platforms).',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'kind': {
                    'type': 'string',
                    'enum': ['node', 'operator', 'chart', 'platform'],
                    'description': 'Only this kind; omit for all four.',
                },
                'query': {'type': 'string', 'description': 'Keyword filter over the summary and triggers.'},
            },
            'additionalProperties': False,
        },
    },
    {
        'name': 'capabilities_show',
        'description': 'Read one capability skill: prerequisites, steps, template, parameters/fields, failures.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'id': {
                    'type': 'string',
                    'description': 'The skill address, e.g. node.tokenize, operator.topic_model, chart.bar.',
                }
            },
            'required': ['id'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'workflow_validate',
        'description': 'Validate a workflow document with the same engine a run uses; returns named refusals.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'workflow': {'type': 'object', 'additionalProperties': True},
            },
            'required': ['workflow'],
            'additionalProperties': False,
        },
    },
)


def capabilities_list(kind: str = '', query: str = '') -> dict:
    """The L1 catalogue for one kind (or all kinds), exactly as the AI tools read it.

    ``MAX_LIMIT`` rather than the tool default's short page: this surface exists to show the whole
    tree, and a silent truncation would make a capability look undeclared.
    """
    from ai import knowledge

    return knowledge.catalog(kind=str(kind or ''), query=str(query or ''), limit=knowledge.MAX_LIMIT)


def capabilities_show(identifier: str) -> dict:
    """The L2 body for one skill address; an unknown address is refused by name."""
    from ai import knowledge

    return knowledge.load(str(identifier or ''))


def workflow_validate(workflow) -> dict:
    """The engine's own verdict on a workflow document, as data."""
    from engine.workflow import WorkflowEngine

    document = workflow if isinstance(workflow, dict) else {}
    problems = WorkflowEngine(document).validate_detailed()
    return {'ok': not problems, 'problems': problems}


def _tool_result(payload) -> dict:
    return {'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}]}


def _tool_error(message: str) -> dict:
    """A tool-level refusal is a result the client can read (MCP ``isError``), not a transport error."""
    return {'content': [{'type': 'text', 'text': message}], 'isError': True}


def _error(identifier, code: int, message: str) -> dict:
    return {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': code, 'message': message}}


def call_tool(name: str, arguments: dict | None) -> dict:
    """Run one tool by name. An unknown tool is refused by name, never silently answered."""
    args = arguments if isinstance(arguments, dict) else {}
    tools = {tool['name']: tool for tool in TOOLS}
    if name not in tools:
        raise KeyError(f'unknown tool {name!r}; known tools: {", ".join(sorted(tools))}')
    if name == 'capabilities_list':
        return _tool_result(capabilities_list(str(args.get('kind') or ''), str(args.get('query') or '')))
    if name == 'capabilities_show':
        try:
            return _tool_result(capabilities_show(str(args.get('id') or '')))
        except Exception as exc:  # an unknown address is the caller's mistake, said in words
            return _tool_error(f'{type(exc).__name__}: {exc}')
    return _tool_result(workflow_validate(args.get('workflow')))


def handle(request) -> dict | None:
    """Answer one JSON-RPC request; a notification (no ``id``) answers ``None``."""
    if not isinstance(request, dict):
        return _error(None, -32600, 'a JSON-RPC request is an object')
    identifier = request.get('id')
    method = str(request.get('method') or '')
    params = request.get('params') if isinstance(request.get('params'), dict) else {}
    if identifier is None:
        # JSON-RPC: a request without an id is a notification, and a notification is never answered —
        # not even to report an unknown method.
        return None
    if method == 'initialize':
        result = {
            'protocolVersion': str(params.get('protocolVersion') or PROTOCOL_VERSION),
            'capabilities': {'tools': {}},
            'serverInfo': dict(SERVER_INFO),
        }
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': [dict(tool) for tool in TOOLS]}
    elif method == 'tools/call':
        try:
            result = call_tool(str(params.get('name') or ''), params.get('arguments'))
        except KeyError as exc:
            message = exc.args[0] if exc.args else 'unknown tool'
            return _error(identifier, -32602, str(message))
        except Exception as exc:  # a refusal is data the client can read, never a dropped line
            return _error(identifier, -32603, f'{type(exc).__name__}: {exc}')
    else:
        return _error(identifier, -32601, f'unknown method {method!r}')
    return {'jsonrpc': '2.0', 'id': identifier, 'result': result}


def serve(instream, outstream) -> None:
    """Line-delimited JSON over a stream pair (the stdio transport); one malformed line is answered."""
    for line in instream:
        text = str(line).strip()
        if not text:
            continue
        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f'parse error: {exc.msg}')
        else:
            response = handle(request)
        if response is None:
            continue
        outstream.write(json.dumps(response, ensure_ascii=False) + '\n')
        outstream.flush()
