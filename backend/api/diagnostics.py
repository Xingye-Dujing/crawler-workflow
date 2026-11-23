"""``POST /api/workflow/diagnostics`` — the edit-time schema truth for the canvas.

Returns, per node, the columns it will emit (``None`` = unknown without a run) and the
parameter problems its plugin can answer without a table. The frontend paints badges, the
output-column line and the validation messages from this; the *schema* lives here, beside the
executors and the analysis step table, so the canvas never holds a second opinion about what a
node produces. The missing-column verdict is the server's too: ``services.validation.contracts``
supplies each node's table shape and ``WorkflowEngine`` compares it with the declared reads.
No prose is localised here — wording is the engine's ``i18n`` catalogue's job.
"""

import logging

from flask import Blueprint, jsonify
from nodes.schema import param_errors

from api.http import _bad_body, _json_body
from engine.workflow import WorkflowEngine, effective_workflow
from i18n import t
from services.validation import contracts

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


def _samples(workflow: dict) -> dict:
    """The stored upstream rows a preflight may judge — never a reason for the route to fail.

    ``services.validation.samples`` resolves the account's run store and pins a sample to the
    node fingerprint; a missing store, a locked DB or an unreadable row is answered as "no
    sample" so the canvas keeps the static verdicts it already had.
    """
    try:
        from services.validation.samples import samples_for

        return samples_for(workflow)
    except Exception:  # a sample is decoration; it must never 500 the route
        logger.exception(t('run.preflightSamplesFailed'))
        return {}


def _contract_columns(workflow: dict) -> dict:
    """Each node's table shape for the run gate — never a reason for the gate to fail.

    The shape comes from the account's run store (recorded schemas) plus the producers' declared
    contracts. A store or plugin failure answers "no shape", which silences the missing-column
    check; it must not refuse a run that the static rules accepted.
    """
    try:
        return contracts.columns_for(workflow)
    except Exception:  # evidence is advisory; the run gate keeps its static verdicts
        logger.exception(t('run.schemaReadFailed'))
        return {}


def validation_payload(workflow: dict, columns: dict | None = None) -> dict:
    """The run gate's answer for one canvas: per-node messages plus the flat list.

    ``engine.workflow.WorkflowEngine`` is the ONE rule body (manifest rules, validators, the
    source matrix, cycles, the column contract, and the preflight when a sample exists); the
    console and the canvas badges word it from the same entries. ``messages`` is the run gate's
    list (errors only); ``perNode``/``entries`` also carry warnings, which badge but never refuse.
    ``columns`` is passed by the diagnostics route (it needs the same mapping for the output-column
    line); the run gate lets this function read it, guarded.
    """
    entries = WorkflowEngine(workflow).validate_detailed(
        samples=_samples(workflow),
        columns=_contract_columns(workflow) if columns is None else columns,
    )
    per_node: dict[str, list[str]] = {}
    for entry in entries:
        if entry['id'] is None:
            continue
        per_node.setdefault(str(entry['id']), []).append(entry['message'])
    # ``messages`` is what the browser's run gate shows and counts, so a warning must not appear
    # there: it is a badge, not a refusal. ``perNode`` carries every entry, warnings included.
    return {
        'messages': [entry['message'] for entry in entries if entry['severity'] == 'error'],
        'perNode': per_node,
        'entries': entries,
    }


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
    try:
        # The shape a node's table will have: the recorded schema of a settled run under the
        # current fingerprint, else the producer's declared contract. The same mapping feeds the
        # panel's output-column line and the engine's read check — one answer, two surfaces.
        columns = contracts.columns_for(effective)
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
                'problems': {},
                'validation': {'messages': [], 'perNode': {}, 'entries': []},
            }
        )
    for nid, rows in broken.items():
        problems[nid] = rows + list(problems.get(nid) or [])
    validation = validation_payload(effective, columns=columns)
    return jsonify({'ok': True, 'columns': columns, 'problems': problems, 'validation': validation})


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
