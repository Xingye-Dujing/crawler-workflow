"""Biblio Blueprint — the read side of the Bibliometrics Workspace panel.

``GET /api/biblio/runs`` and ``GET /api/biblio/table`` answer two questions the browser cannot
be allowed to guess: which recorded runs actually hold a bibliometrics node, and what one of
those nodes left behind. The answers come from the durable ledger (``run_store``), so a workspace
opened after a restart, a page reload or a rewired canvas still shows the paid-for graph — and a
node that stored nothing says so by name instead of painting an empty table.

Nothing here re-runs an analysis: the panel reads what a run already proved.
"""

from flask import Blueprint, jsonify, request

from i18n import t
from services.biblio_schema import classify_shape

bp = Blueprint('biblio', __name__)

#: One page of a node table. A bibliometric node is one row per entity, so a real corpus is
#: thousands of rows deep and must not be materialised into a single response.
PAGE = 200
MAX_PAGE = 1000


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
    from app import get_run_store

    limit = _int(request.args.get('limit'), 50, 1, 200)
    return jsonify({'ok': True, 'runs': get_run_store().list_biblio_runs(limit=limit)})


@bp.route('/api/biblio/table', methods=['GET'])
def biblio_table():
    """One page of a stored bibliometrics table, labelled with the shape it was emitted as."""
    from app import get_run_store

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
