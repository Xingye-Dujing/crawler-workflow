"""执行统计 Blueprint — the ``/api/stats/*`` cluster, split out of ``app.py``.

These are read-only GET endpoints that poll the *in-memory* results of the run in flight, so they
take a stable snapshot of ``execution_state['results']`` via ``state._results_snapshot`` (guarded
by ``_completed_lock``) rather than iterating the live dict the publishing worker mutates. Paths
are unchanged; the app-level ``before_request`` / CORS still wrap them.
"""

from flask import Blueprint, jsonify
from state import _results_snapshot

from services import StatsService

bp = Blueprint('stats', __name__)


@bp.route('/api/stats/emotion', methods=['GET'])
def emotion_stats():
    all_data = []
    # The snapshot is the point: these routes can be polled *during* a run, and iterating
    # the live results dict while the worker publishes the next node aborted the request.
    for _nid, data in _results_snapshot().items():
        if isinstance(data, list):
            for item in data:
                if 'emotion' in item:
                    all_data.append(item)
    return jsonify({'ok': True, 'stats': StatsService.emotion_distribution(all_data)})


@bp.route('/api/stats/tendency', methods=['GET'])
def tendency_stats():
    all_data = []
    for _nid, data in _results_snapshot().items():
        if isinstance(data, list):
            for item in data:
                if 'tendency' in item:
                    all_data.append(item)
    return jsonify({'ok': True, 'stats': StatsService.tendency_distribution(all_data)})


@bp.route('/api/stats/summary', methods=['GET'])
def platform_summary():
    summary = {}
    for nid, data in _results_snapshot().items():
        if isinstance(data, list) and data:
            summary[nid] = {'count': len(data), 'sample_keys': list(data[0].keys()) if data else []}
    return jsonify({'ok': True, 'summary': summary})
