"""``POST /api/workflow/diagnostics`` — the edit-time schema truth for the canvas.

Returns, per node, the columns it will emit (``None`` = unknown without a run) and the
columns it will read from its input. The frontend paints badges, the output-column line
and the missing-column flags from this; the *schema* lives here, beside the executors and
the analysis step table, so the canvas never holds a second opinion about what a node
produces. No prose is localised here — wording is the frontend's catalogue's job.
"""

import logging

from flask import Blueprint, jsonify
from nodes.schema import compute_columns, referenced_columns

from api.http import _bad_body, _json_body
from engine.workflow import effective_workflow

logger = logging.getLogger(__name__)

bp = Blueprint('diagnostics', __name__)


@bp.route('/api/workflow/diagnostics', methods=['POST'])
def workflow_diagnostics():
    body = _json_body()
    if body is None:
        return _bad_body()
    nodes = body.get('nodes')
    if not isinstance(nodes, dict):
        nodes = {}
    connections = body.get('connections')
    if not isinstance(connections, list):
        connections = []
    workflow = {'nodes': list(nodes.values()), 'connections': connections, 'settings': body.get('settings') or {}}
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
    eff_connections = effective.get('connections', [])
    columns = compute_columns(eff_nodes, eff_connections)
    reads = referenced_columns(eff_nodes)
    return jsonify({'ok': True, 'columns': columns, 'reads': reads})
