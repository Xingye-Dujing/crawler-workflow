"""执行历史 Blueprint — the ``/api/history/*`` cluster, split out of ``app.py``.

Paths are unchanged, so the test client and the frontend hit the same URLs; ``app.py``'s
module-level ``before_request`` / error handlers / CORS still apply (they are registered on the
app, not the route). It reads the shared ``history_service`` from ``state`` and the request
helpers from ``api.http`` rather than importing ``app`` (a cycle).
"""

from flask import Blueprint, jsonify, request
from state import history_service

from api.http import _bad_body, _json_body, _safe_int
from i18n import t

bp = Blueprint('history', __name__)


@bp.route('/api/history/runs', methods=['GET'])
def history_runs():
    limit = _safe_int(request.args.get('limit'), 50, minimum=1, maximum=1000)
    df = history_service.list_runs(limit=limit)
    return jsonify({'ok': True, 'runs': df.to_dict('records'), 'workflow_names': history_service.list_workflow_names()})


@bp.route('/api/history/series', methods=['GET'])
def history_series():
    workflow_name = request.args.get('workflow_name') or None
    metric = request.args.get('metric') or None
    node_id = request.args.get('node_id') or None
    limit = _safe_int(request.args.get('limit'), 2000, minimum=1, maximum=20000)
    df = history_service.series(workflow_name=workflow_name, metric=metric, node_id=node_id, limit=limit)
    return jsonify({'ok': True, 'rows': df.to_dict('records')})


@bp.route('/api/history/clear', methods=['POST'])
def history_clear():
    history_service.clear()
    return jsonify({'ok': True, 'message': t('history.cleared')})


@bp.route('/api/history/delete', methods=['POST'])
def history_delete():
    """Forget one run's recorded metrics, leaving the rest of the history alone.

    «清空历史» was the only door out, so one bad run meant losing the whole
    comparison chart to get rid of it. The answer carries the deleted row count
    because an id that matched nothing is a different truth from a deletion:
    the panel is looking at a list it loaded a moment ago, and a run can have
    been aged out by the retention policy in between.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    run_id = str(data.get('run_id') or '').strip()
    if not run_id:
        return jsonify({'ok': False, 'error': t('api.historyNoRunId')}), 400
    deleted = history_service.delete_run(run_id)
    return jsonify({'ok': True, 'deleted': deleted, 'run_id': run_id})
