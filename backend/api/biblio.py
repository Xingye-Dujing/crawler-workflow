"""Biblio Blueprint — the Bibliometrics Workspace's whole server side.

``GET /api/biblio/runs`` and ``GET /api/biblio/table`` answer two questions the browser cannot
be allowed to guess: which recorded runs actually hold a bibliometrics node, and what one of
those nodes left behind. The answers come from the durable ledger (``run_store``), so a workspace
opened after a restart, a page reload or a rewired canvas still shows the paid-for graph — and a
node that stored nothing says so by name instead of painting an empty table.

``/api/biblio/project*`` / ``/api/biblio/snapshot*`` / ``/api/biblio/compare`` add the kept
half: a named capture of one node's result under a project, and the diff between two captures.
The comparison is computed on the server (``biblio_store.compare_snapshots``) — a browser that
assembled a diff would be a second implementation of "what changed".

Nothing here re-runs an analysis: the panel reads what a run already proved.
"""

from flask import Blueprint, jsonify, request
from state import add_log
from stores import get_biblio_store, get_run_store

from api.http import _bad_body, _json_body
from i18n import t
from services.biblio.formats import accepted_extensions
from services.biblio.metrics import snapshot_capture
from services.biblio.schema import classify_shape
from services.biblio.sources import all_sources
from services.biblio.store import snapshot_header

bp = Blueprint('biblio', __name__)

#: One page of a node table. A bibliometric node is one row per entity, so a real corpus is
#: thousands of rows deep and must not be materialised into a single response.
PAGE = 200
MAX_PAGE = 1000
#: How many captured rows a snapshot detail echoes back. The stored copy is complete; the
#: response is a preview, and it says so.
PREVIEW = 100


def _int(value, default: int, low: int, high: int) -> int:
    """A clamped integer query parameter — a panel typo is a smaller view, never a 500."""
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


@bp.route('/api/biblio/runs', methods=['GET'])
def biblio_runs():
    """Runs that contain a ``biblio`` node, newest first, with those nodes and their files."""
    limit = _int(request.args.get('limit'), 50, 1, 200)
    return jsonify({'ok': True, 'runs': get_run_store().list_biblio_runs(limit=limit)})


@bp.route('/api/biblio/sources', methods=['GET'])
def export_guide():
    """The export guide: one entry per source the importer can read, in detection order.

    Sentences are built here (``services.biblio.sources``) from the thread's language, exactly
    like the cookie guide, so the browser draws what the server knows instead of keeping its
    own copy of which site exports what. Extension and capability lists come from the format
    registry, which is the only thing that can say what a parser accepts.
    """
    return jsonify({'ok': True, 'sources': all_sources(), 'extensions': list(accepted_extensions())})


@bp.route('/api/biblio/table', methods=['GET'])
def biblio_table():
    """One page of a stored bibliometrics table, labelled with the shape it was emitted as."""
    run_id = str(request.args.get('run_id') or '').strip()
    node_id = str(request.args.get('node_id') or '').strip()
    store = get_run_store()
    run = store.get_run(run_id) if run_id else None
    if run is None:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid=run_id or '(empty)')}), 404
    node = next((n for n in run.get('nodes') or [] if str(n.get('node_id')) == node_id), None)
    if node is None:
        return jsonify({'ok': False, 'error': t('biblio.workspace_no_node', nid=node_id or '(empty)', rid=run_id)}), 404
    if str(node.get('node_type') or '') != 'biblio':
        return jsonify({'ok': False, 'error': t('biblio.workspace_not_biblio', nid=node_id)}), 400

    offset = _int(request.args.get('offset'), 0, 0, 10**9)
    limit = _int(request.args.get('limit'), PAGE, 1, MAX_PAGE)
    total, rows = store.load_rows_page(run_id, node_id, offset=offset, limit=limit)
    columns = list(rows[0].keys()) if rows else []
    payload = {
        'ok': True,
        'run_id': run_id,
        'node_id': node_id,
        'title': node.get('title') or '',
        'status': node.get('status') or '',
        'shape': classify_shape(columns),
        'columns': columns,
        'rows': rows,
        'total': total,
        'offset': offset,
        'limit': limit,
        'files': [
            entry
            for entry in store.files_for_run(run_id, node_id=node_id)
            if str(entry.get('kind') or '').startswith('biblio_') or str(entry.get('kind') or '') == 'latex'
        ],
    }
    if not rows:
        # An empty table is a state to name, not a failure: the node may have been stopped,
        # or its rows cleared by the retention policy while its record stayed.
        payload['note'] = t('biblio.workspace_empty_table', nid=node_id)
    return jsonify(payload)


# ─── Projects and snapshots ────────────────────────────────────


@bp.route('/api/biblio/projects', methods=['GET'])
def biblio_projects_list():
    """Every project with its snapshot headers — one call is all the panel needs to draw both."""
    store = get_biblio_store()
    projects = store.list_projects()
    for project in projects:
        project['snapshots'] = store.list_snapshots(project['project_id'])
    return jsonify({'ok': True, 'projects': projects})


@bp.route('/api/biblio/project', methods=['POST'])
def biblio_project_create():
    data = _json_body()
    if data is None:
        return _bad_body()
    name = str(data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': t('biblio.project_needs_name')}), 400
    project = get_biblio_store().create_project(name, str(data.get('note') or ''))
    return jsonify({'ok': True, 'project': project})


@bp.route('/api/biblio/project/rename', methods=['POST'])
def biblio_project_rename():
    data = _json_body()
    if data is None:
        return _bad_body()
    project_id = str(data.get('project_id') or '').strip()
    name = str(data.get('name') or '').strip()
    store = get_biblio_store()
    if store.get_project(project_id) is None:
        return jsonify({'ok': False, 'error': t('biblio.project_not_found', pid=project_id or '(empty)')}), 404
    if not name:
        return jsonify({'ok': False, 'error': t('biblio.project_needs_name')}), 400
    note = None if 'note' not in data else str(data.get('note') or '')
    store.rename_project(project_id, name, note)
    return jsonify({'ok': True, 'project': store.get_project(project_id)})


@bp.route('/api/biblio/project/delete', methods=['POST'])
def biblio_project_delete():
    data = _json_body()
    if data is None:
        return _bad_body()
    project_id = str(data.get('project_id') or '').strip()
    store = get_biblio_store()
    if store.get_project(project_id) is None:
        return jsonify({'ok': False, 'error': t('biblio.project_not_found', pid=project_id or '(empty)')}), 404
    removed = store.delete_project(project_id)
    return jsonify({'ok': True, 'removed_snapshots': removed})


@bp.route('/api/biblio/snapshot', methods=['POST'])
def biblio_snapshot_create():
    """Capture one stored node table into a project, with the parameters that produced it.

    The rows are read from the run ledger in full (not one page): a snapshot that silently held
    the first 200 rows would make every later comparison a comparison of two arbitrary prefixes.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    project_id = str(data.get('project_id') or '').strip()
    run_id = str(data.get('run_id') or '').strip()
    node_id = str(data.get('node_id') or '').strip()
    store = get_biblio_store()
    project = store.get_project(project_id)
    if project is None:
        return jsonify({'ok': False, 'error': t('biblio.project_not_found', pid=project_id or '(empty)')}), 404
    run_store = get_run_store()
    run = run_store.get_run(run_id) if run_id else None
    if run is None:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid=run_id or '(empty)')}), 404
    node = next((n for n in run.get('nodes') or [] if str(n.get('node_id')) == node_id), None)
    if node is None:
        return jsonify({'ok': False, 'error': t('biblio.workspace_no_node', nid=node_id or '(empty)', rid=run_id)}), 404
    if str(node.get('node_type') or '') != 'biblio':
        return jsonify({'ok': False, 'error': t('biblio.workspace_not_biblio', nid=node_id)}), 400
    rows = run_store.load_rows(run_id, node_id)
    if not rows:
        return jsonify({'ok': False, 'error': t('biblio.workspace_empty_table', nid=node_id)}), 400

    captured = snapshot_capture(rows)
    shape = classify_shape(list(rows[0].keys()))
    label = str(data.get('label') or '').strip() or str(node.get('title') or node_id)
    # The parameters come from the SAVED canvas, verified against the fingerprint the run
    # recorded — never from whatever the panel happens to hold, which may have been edited
    # since the run and would then be filed as the settings that produced these rows.
    params, verified = _captured_params(
        str(run.get('workflow_name') or ''), node_id, str(node.get('fingerprint') or '')
    )
    snapshot = get_biblio_store().add_snapshot(
        project_id=project_id,
        label=label,
        run_id=run_id,
        node_id=node_id,
        workflow_name=str(run.get('workflow_name') or ''),
        workflow_fingerprint=str(node.get('fingerprint') or ''),
        entity_type=str(rows[0].get('类型') or ''),
        shape=shape,
        params=params,
        params_verified=verified,
        nodes=captured['nodes'],
        edges=captured['edges'],
    )
    add_log(
        t(
            'biblio.snapshot_done',
            label=label,
            nodes=len(captured['nodes']),
            edges=len(captured['edges']),
            verified='yes' if verified else 'no',
        )
    )
    return jsonify({'ok': True, 'snapshot': _header_of(snapshot)})


def _captured_params(workflow_name: str, node_id: str, fingerprint: str) -> tuple[dict, bool]:
    """The node's own parameters, and whether they are provably the ones that ran.

    Lives on ``WorkflowManager`` because the LaTeX report asks the same question of the same files;
    a second reader of the canvas would be a second opinion about what produced these rows.
    """
    from services.workflow_manager import WorkflowManager

    return WorkflowManager().captured_params(workflow_name, node_id, fingerprint)


@bp.route('/api/biblio/snapshots/<snapshot_id>', methods=['GET'])
def biblio_snapshot_detail(snapshot_id: str):
    snapshot = get_biblio_store().get_snapshot(snapshot_id)
    if snapshot is None:
        return jsonify({'ok': False, 'error': t('biblio.snapshot_not_found', sid=snapshot_id)}), 404
    nodes = snapshot.get('nodes') or []
    edges = snapshot.get('edges') or []
    return jsonify(
        {
            'ok': True,
            'snapshot': _header_of(snapshot),
            'params': snapshot.get('params') or {},
            'summary': snapshot.get('summary') or {},
            'columns': list(nodes[0].keys()) if nodes else [],
            'nodes': nodes[:PREVIEW],
            'edges': edges[:PREVIEW],
            'node_total': len(nodes),
            'edge_total': len(edges),
            'preview_limit': PREVIEW,
        }
    )


@bp.route('/api/biblio/snapshot/delete', methods=['POST'])
def biblio_snapshot_delete():
    data = _json_body()
    if data is None:
        return _bad_body()
    snapshot_id = str(data.get('snapshot_id') or '').strip()
    if not get_biblio_store().delete_snapshot(snapshot_id):
        return jsonify({'ok': False, 'error': t('biblio.snapshot_not_found', sid=snapshot_id or '(empty)')}), 404
    return jsonify({'ok': True, 'removed': snapshot_id})


@bp.route('/api/biblio/compare', methods=['GET'])
def biblio_compare():
    """The diff between two captures, computed here from the stored rows."""
    left = str(request.args.get('a') or '').strip()
    right = str(request.args.get('b') or '').strip()
    if not left or not right or left == right:
        return jsonify({'ok': False, 'error': t('biblio.compare_needs_two')}), 400
    diff = get_biblio_store().compare(left, right)
    if diff is None:
        missing = left if get_biblio_store().get_snapshot(left) is None else right
        return jsonify({'ok': False, 'error': t('biblio.snapshot_not_found', sid=missing)}), 404
    return jsonify({'ok': True, 'diff': diff})


def _header_of(snapshot: dict) -> dict:
    """The describing half of a snapshot — the same projection the diff header uses."""
    return snapshot_header(snapshot)
