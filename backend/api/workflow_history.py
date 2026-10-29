"""Canvas history: save, list, restore and delete whole-canvas snapshots.

The browser sends the same ``canvas.toWorkflowJSON()`` body the file-save route takes, so a
snapshot is not a second serialization of the canvas. Restoring is a read here and a rebuild
in the browser; the server never draws a canvas. The layout endpoints keep the second
auto-layout strategy's baseline per workflow, because "which arrangement was right" is part
of a workflow's state, not a global preference.

Named refusals rather than silent behaviour:
  * a payload without a node list is refused by name;
  * a full history is a 409 with the limit, never an oldest-entry eviction;
  * a missing snapshot is a 404, and a corrupt one is a 409 naming its id.
"""

from flask import Blueprint, jsonify, request
from runtime.stores import get_workflow_history_store

from api.http import _bad_body, _bad_param, _json_body
from i18n import t
from services.workflows.history import HistoryFullError, SnapshotCorruptError

bp = Blueprint('workflow_history', __name__)


@bp.route('/api/workflow/history', methods=['GET'])
def list_history():
    store = get_workflow_history_store()
    return jsonify({'ok': True, 'snapshots': store.list_snapshots(), 'max': store.MAX_SNAPSHOTS})


@bp.route('/api/workflow/history/save', methods=['POST'])
def save_history():
    data = _json_body()
    if data is None:
        return _bad_body()
    for field in ('label', 'workflow_name'):
        if not isinstance(data.get(field, ''), str):
            return _bad_param(field)
    try:
        snapshot = get_workflow_history_store().save_snapshot(
            data.get('workflow'), data.get('label', ''), data.get('workflow_name', '')
        )
    except HistoryFullError as e:
        return jsonify({'ok': False, 'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'snapshot': snapshot})


@bp.route('/api/workflow/history/get', methods=['GET'])
def get_history():
    snapshot_id = str(request.args.get('id') or '')
    try:
        snapshot = get_workflow_history_store().get_snapshot(snapshot_id)
    except SnapshotCorruptError as e:
        return jsonify({'ok': False, 'error': str(e)}), 409
    if snapshot is None:
        return jsonify({'ok': False, 'error': t('wfHistory.missing', id=snapshot_id or '(empty)')}), 404
    return jsonify({'ok': True, 'snapshot': snapshot})


@bp.route('/api/workflow/history/rename', methods=['POST'])
def rename_history():
    data = _json_body()
    if data is None:
        return _bad_body()
    snapshot_id = data.get('id')
    label = data.get('label', '')
    if not isinstance(snapshot_id, str):
        return _bad_param('id')
    if not isinstance(label, str):
        return _bad_param('label')
    try:
        snapshot = get_workflow_history_store().rename_snapshot(snapshot_id, label)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    if snapshot is None:
        return jsonify({'ok': False, 'error': t('wfHistory.missing', id=snapshot_id or '(empty)')}), 404
    return jsonify({'ok': True, 'snapshot': snapshot})


@bp.route('/api/workflow/history/delete', methods=['POST'])
def delete_history():
    data = _json_body()
    if data is None:
        return _bad_body()
    snapshot_id = data.get('id')
    if not isinstance(snapshot_id, str):
        return _bad_param('id')
    deleted, cleared = get_workflow_history_store().delete_snapshot(snapshot_id)
    return jsonify({'ok': True, 'deleted': deleted, 'baselines_cleared': cleared})


@bp.route('/api/workflow/history/layout', methods=['GET'])
def get_layout():
    name = str(request.args.get('workflow') or '').strip()
    return jsonify({'ok': True, 'layout': get_workflow_history_store().get_layout(name)})


@bp.route('/api/workflow/history/layout', methods=['POST'])
def set_layout():
    data = _json_body()
    if data is None:
        return _bad_body()
    name = data.get('workflow_name')
    strategy = data.get('strategy')
    snapshot_id = data.get('snapshot_id', '')
    if not isinstance(name, str):
        return _bad_param('workflow_name')
    if not isinstance(strategy, str):
        return _bad_param('strategy')
    if not isinstance(snapshot_id, str):
        return _bad_param('snapshot_id')
    try:
        layout = get_workflow_history_store().set_layout(name, strategy, snapshot_id)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'layout': layout})
