"""Run-to-run comparison: two recorded runs, one server-computed diff."""

from flask import Blueprint, jsonify, request
from runtime.stores import get_run_store

from i18n import t
from services.runs.compare import compare_runs

bp = Blueprint('run_compare', __name__)


@bp.route('/api/runs/compare', methods=['GET'])
def runs_compare():
    """The diff between two recorded runs.

    The refusals go through ``t()`` because the panel prints ``body.error`` in a toast: English
    literals here showed a Chinese UI an English sentence for a bad query string. The row ceiling is
    the service's (``compare.compare_runs`` clamps to its own maximum), so a huge or negative ``limit``
    cannot make this route build an unbounded diff.
    """
    run_a = str(request.args.get('a') or '').strip()
    run_b = str(request.args.get('b') or '').strip()
    if not run_a or not run_b:
        return jsonify({'ok': False, 'error': t('api.compareNeedsBothRuns')}), 400
    raw_limit = str(request.args.get('limit') or '50').strip()
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': t('api.compareLimitInteger')}), 400
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
