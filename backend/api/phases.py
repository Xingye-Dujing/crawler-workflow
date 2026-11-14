"""``/api/run/phases`` — the Console's phase-timing strip.

The data is :mod:`runtime.phases` (a ring of launch/crawl/walk timings). This module is the
HTTP shape only: the caller's own account and the run it is looking at decide what comes
back, so the panel cannot read another account's timings. An entry recorded outside a run
(a cookie probe's browser) is filed under the empty run id and is returned for "any run"
requests, which is what the panel asks between runs.
"""

from flask import Blueprint, jsonify
from runtime import account_context, phases
from runtime.state import execution_state

bp = Blueprint('phases', __name__)


@bp.route('/api/run/phases', methods=['GET'])
def run_phases():
    owner = account_context.current()
    user_id = owner.user_id if owner is not None else ''
    # A rolling tail of THIS account's last phases, across runs: the panel is a log, and
    # blanking it the moment a run finishes would hide exactly the timings the user opened
    # it to read. Each entry carries its run id, so the strip can mark a new run's start.
    entries = phases.snapshot(run_id=None, user_id=user_id, limit=60)
    return jsonify(
        {
            'ok': True,
            'run_id': str(execution_state.get('run_id') or ''),
            'running': bool(execution_state.get('running')),
            'phases': entries,
        }
    )
