"""Run-to-run comparison: two recorded runs, one server-computed diff."""

from flask import Blueprint, jsonify, request
from stores import get_run_store

from services.run_compare import compare_runs

bp = Blueprint('run_compare', __name__)


@bp.route('/api/runs/compare', methods=['GET'])
def runs_compare():
    run_a = str(request.args.get('a') or '').strip()
    run_b = str(request.args.get('b') or '').strip()
    if not run_a or not run_b:
        return jsonify({'ok': False, 'error': 'a and b are required'}), 400
    raw_limit = str(request.args.get('limit') or '50').strip()
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'limit must be an integer'}), 400
    try:
        diff = compare_runs(
            get_run_store(),
            run_a,
            run_b,
            node_id=str(request.args.get('node') or '').strip(),
            key=str(request.args.get('key') or '').strip(),
            limit=limit,
        )
    except LookupError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'diff': diff})
