"""执行历史 Blueprint — the ``/api/history/*`` cluster, split out of ``app.py``.

Paths are unchanged, so the test client and the frontend hit the same URLs; ``app.py``'s
module-level ``before_request`` / error handlers / CORS still apply (they are registered on the
app, not the route). It reads the shared ``history_service`` from ``state`` and the request
helpers from ``api.http`` rather than importing ``app`` (a cycle).
"""

from flask import Blueprint, jsonify, request
from runtime.state import history_service

from api.http import _bad_body, _json_body, _safe_int
from i18n import t

bp = Blueprint('history', __name__)


@bp.route('/api/history/series', methods=['GET'])
def history_series():
    """Chart data plus the filter's workflow names — one request, no run listing.

    The panel used to fetch ``/api/history/runs`` just to build its workflow
    filter, which duplicated 运行记录's listing of the same executions. The list
    belongs to the ledger; this endpoint only answers what the trend chart needs.
    """
    workflow_name = request.args.get('workflow_name') or None
    metric = request.args.get('metric') or None
    node_id = request.args.get('node_id') or None
    limit = _safe_int(request.args.get('limit'), 2000, minimum=1, maximum=20000)
    df = history_service.series(workflow_name=workflow_name, metric=metric, node_id=node_id, limit=limit)
    return jsonify(
        {
            'ok': True,
            'rows': df.to_dict('records'),
            'workflow_names': history_service.list_workflow_names(),
        }
    )


@bp.route('/api/history/clear', methods=['POST'])
def history_clear():
    """Forget every recorded run metric — a bulk destructive write, so it asks first.

    ``runs_clear``, ``exports_clear`` and both smart-clears all answer a body without
    ``confirm: true`` with a 400, and this route was the lone bulk door that read no body at
    all: an unauthenticated cross-origin request (or a stray call) wiped the whole comparison
    chart with no gate. It now holds the same line as its siblings.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    if data.get('confirm') is not True:
        return jsonify({'ok': False, 'error': t('api.needConfirm')}), 400
    history_service.clear()
    return jsonify({'ok': True, 'message': t('history.cleared')})
