"""Scheduled tasks Blueprint — ``/api/schedules*``.

The panel's whole surface for the timer: read the tasks, create/update one, delete one, switch one
on or off, and run one now. Time arithmetic and the record live in ``scheduling/store``;
the clock lives in ``scheduling.clock``; this module only moves JSON and turns a refusal into a status
code. Depends on ``api.http`` (body parsing), the store, and the scheduler's two seams — never on
``app`` (a cycle), which is why the canvas verdict is asked for through ``scheduling.clock.load_canvas``.
"""

from flask import Blueprint, jsonify
from scheduling import store
from scheduling.clock import fire_now, load_canvas
from scheduling.clock import status as scheduler_status

from api.http import _bad_body, _json_body
from i18n import t
from services.workflow_manager import WorkflowManager

bp = Blueprint('schedules', __name__)


def _canvases() -> list:
    """Every saved canvas, with the verdict that decides whether a timer may run it.

    The picker shows that verdict beside the name, so a canvas whose steps need a model is refused
    while the user is still choosing — rather than at 03:00, in a history line nobody is reading.
    """
    out = []
    for entry in WorkflowManager().describe():
        if entry.get('broken'):
            continue
        loaded = load_canvas(entry.get('name'))
        out.append(
            {
                'name': entry.get('name'),
                'runnable': loaded.get('workflow') is not None,
                'why_not': loaded.get('error', ''),
            }
        )
    return sorted(out, key=lambda item: item.get('name') or '')


def _payload() -> dict:
    """Everything the panel paints from, so no answer leaves it showing a half-updated page."""
    return {'ok': True, 'tasks': store.public_all(), 'canvases': _canvases(), 'status': scheduler_status()}


@bp.route('/api/schedules', methods=['GET'])
def list_schedules():
    return jsonify(_payload())


@bp.route('/api/schedules/save', methods=['POST'])
def save_schedule():
    """Create a task, or update the one whose id came back with the form."""
    data = _json_body()
    if data is None:
        return _bad_body()
    raw = data.get('task') if isinstance(data.get('task'), dict) else data
    workflow = str((raw or {}).get('workflow') or '').strip()
    if workflow:
        loaded = load_canvas(workflow)
        if loaded.get('error'):
            return jsonify(dict(_payload(), ok=False, error=loaded['error'])), 400
    task, error = store.save_task(raw)
    if error:
        return jsonify(dict(_payload(), ok=False, error=error)), 400
    return jsonify(dict(_payload(), task=store.public(task)))


@bp.route('/api/schedules/delete', methods=['POST'])
def delete_schedule():
    data = _json_body()
    if data is None:
        return _bad_body()
    task_id = str((data or {}).get('id') or '')
    if not store.delete_task(task_id):
        return jsonify(dict(_payload(), ok=False, error=t('sched.taskMissing', id=task_id))), 404
    return jsonify(_payload())


@bp.route('/api/schedules/toggle', methods=['POST'])
def toggle_schedule():
    """Switch one task on or off. Off keeps the record; it stops the clock for that one task."""
    data = _json_body()
    if data is None:
        return _bad_body()
    task, error = store.set_enabled((data or {}).get('id'), (data or {}).get('enabled'))
    if error:
        return jsonify(dict(_payload(), ok=False, error=error)), 404
    return jsonify(dict(_payload(), task=store.public(task)))


@bp.route('/api/schedules/run', methods=['POST'])
def run_schedule():
    """Run one task right now, whatever its clock says (and even while it is switched off).

    The run itself goes through ``_begin_run`` like any other, so a busy server QUEUES this fire as
    well — the answer says which of the two happened instead of the panel guessing from a toast.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    task_id = str((data or {}).get('id') or '')
    if store.get_task(task_id) is None:
        return jsonify(dict(_payload(), ok=False, error=t('sched.taskMissing', id=task_id))), 404
    answer = fire_now(task_id)
    if not answer.get('ok'):
        return jsonify(
            dict(_payload(), ok=False, error=answer.get('error') or '', result=answer.get('result') or {})
        ), 400
    return jsonify(dict(_payload(), result=answer.get('result') or {}))
