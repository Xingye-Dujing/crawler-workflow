"""``POST /api/workflow/diagnostics`` — the edit-time schema truth for the canvas.

Returns, per node, the columns it will emit (``None`` = unknown without a run), the
columns it will read from its input, and the parameter problems its plugin can answer
without a table. The frontend paints badges, the output-column line and the
missing-column flags from this; the *schema* lives here, beside the executors and
the analysis step table, so the canvas never holds a second opinion about what a node
produces. No prose is localised here — wording is the frontend's catalogue's job.
"""

import logging

from flask import Blueprint, jsonify
from nodes.schema import compute_columns, param_errors, referenced_columns

from api.http import _bad_body, _json_body
from engine.workflow import WorkflowEngine, effective_workflow
from i18n import t

logger = logging.getLogger(__name__)

bp = Blueprint('diagnostics', __name__)


def _workflow_from_body(body: dict) -> dict:
    """The workflow a diagnostics/validate request describes, with every shape guarded."""
    nodes = body.get('nodes')
    if not isinstance(nodes, dict):
        nodes = {}
    connections = body.get('connections')
    if not isinstance(connections, list):
        connections = []
    settings = body.get('settings')
    if not isinstance(settings, dict):
        # ``effective_workflow`` reads ``settings.get(...)`` before this route's guarded block, so
        # a string here used to kill the very route that exists to survive a malformed canvas.
        settings = {}
    return {'nodes': list(nodes.values()), 'connections': connections, 'settings': settings}


def validation_payload(workflow: dict) -> dict:
    """The run gate's answer for one canvas: per-node messages plus the flat list.

    ``engine.workflow.WorkflowEngine`` is the ONE rule body (manifest rules, validators, the
    source matrix, cycles); the console and the canvas badges word it from the same entries.
    """
    entries = WorkflowEngine(workflow).validate_detailed()
    per_node: dict[str, list[str]] = {}
    for entry in entries:
        if entry['id'] is None:
            continue
        per_node.setdefault(str(entry['id']), []).append(entry['message'])
    return {'messages': [entry['message'] for entry in entries], 'perNode': per_node, 'entries': entries}


def _readable_params(nodes: dict) -> tuple[dict, dict]:
    """The nodes this route can read, plus the ones whose ``params`` is not an object.

    An AI-written or hand-edited workflow can carry ``"params": "去重，按评论内容"``. Every
    plugin hook then answered ``AttributeError: 'str' object has no attribute 'get'`` and this
    route died with an HTML 500 the canvas cannot parse, so every column badge vanished. The
    shape is a REFUSAL the run path already names (``services/runs/payload.workflow_shape_error``);
    here it becomes a per-node problem the badge shows, and the route keeps answering for the
    nodes it CAN see.
    """
    clean: dict = {}
    broken: dict = {}
    for nid, node in nodes.items():
        if not isinstance(node, dict):
            continue
        params = node.get('params')
        if 'params' in node and not isinstance(params, dict):
            clean[str(nid)] = {**node, 'params': {}}
            broken[str(nid)] = [{'code': 'params_shape'}]
            continue
        clean[str(nid)] = node
    return clean, broken


@bp.route('/api/workflow/diagnostics', methods=['POST'])
def workflow_diagnostics():
    body = _json_body()
    if body is None:
        return _bad_body()
    workflow = _workflow_from_body(body)
    # Validate on the SAME effective graph a run would use: a disabled node (or one
    # starved by a disabled upstream) is not on the canvas, so it must not be judged.
    effective = effective_workflow(workflow)
    # ``n['id']`` used to be assumed: a node object the browser sends without an id survives
    # ``effective_workflow`` (which only reads it with ``.get``) and then crashed this route
    # with a bare ``KeyError: 'id'`` — an HTML 500 the frontend cannot parse, so the whole
    # column badge silently disappeared. The run path already refuses such a node by name
    # (``services/runs/payload.workflow_shape_error``); the diagnostics route only reads, and a
    # node it cannot address is one it cannot diagnose, so it is left out rather than fatal.
    eff_nodes = {str(n['id']): n for n in effective.get('nodes', []) if isinstance(n, dict) and n.get('id')}
    eff_nodes, broken = _readable_params(eff_nodes)
    eff_connections = effective.get('connections', [])
    try:
        columns = compute_columns(eff_nodes, eff_connections)
        reads = referenced_columns(eff_nodes)
        # Parameter problems travel the same route as the column model: the RULE lives beside the
        # step's contract, the wording in the browser catalogue. A blank required column therefore
        # reaches the node's badge while the canvas is being drawn, not after the run paid for the
        # crawl above it.
        problems = param_errors(eff_nodes)
    except Exception as exc:  # a plugin hook that cannot read a node must not kill the canvas
        # ``logger.exception`` already attaches exc_info. Passing ``exc`` as a positional
        # format argument to a message with no placeholder made logging raise
        # "not all arguments converted" on every hit: the traceback was discarded and a
        # "--- Logging error ---" block landed on stderr.
        logger.exception(t('api.diagnosticsFailed'))
        return jsonify(
            {
                'ok': False,
                'error': str(exc)[:300],
                'columns': {},
                'reads': {},
                'problems': {},
                'validation': {'messages': [], 'perNode': {}, 'entries': []},
            }
        )
    for nid, rows in broken.items():
        problems[nid] = rows + list(problems.get(nid) or [])
    validation = validation_payload(effective)
    return jsonify({'ok': True, 'columns': columns, 'reads': reads, 'problems': problems, 'validation': validation})


@bp.route('/api/workflow/validate', methods=['POST'])
def workflow_validate():
    """The run gate before the browser POSTs a run — one rule body, on the server.

    The canvas used to keep a JavaScript copy of every node's pre-run rule (``runs.js``); the
    two drifted, and a stored option the server refused could still pass the panel. The answer
    here is ``engine.workflow``'s own entries, worded by the request's language.
    """
    body = _json_body()
    if body is None:
        return _bad_body()
    return jsonify({'ok': True, **validation_payload(effective_workflow(_workflow_from_body(body)))})
