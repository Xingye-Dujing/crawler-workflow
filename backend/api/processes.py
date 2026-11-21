"""The children this server started: list them, stop one.

A command the assistant ran, a Python script, the CatBus adapter — each is a real process on the
user's machine, so it answers to the account that asked for it and to nobody else. The list is the
truth about what is RUNNING (an exited child is pruned), and stopping a child goes through
``runtime.processes.stop`` → ``core.procs.reap_process`` so the tree goes with it.
"""

from flask import Blueprint, jsonify
from runtime import account_context, processes

from i18n import t

bp = Blueprint('processes', __name__)


def _owner() -> str:
    return account_context.scope_key()


@bp.route('/api/processes', methods=['GET'])
def list_children():
    return jsonify({'ok': True, 'children': processes.rows(_owner()), 'can_control': True})


@bp.route('/api/processes/<ident>/stop', methods=['POST'])
def stop_child(ident: str):
    status, reason = processes.stop(ident, _owner())
    if status == 'refused':
        # Another account's child: naming it would be enough to try stopping it.
        return jsonify({'ok': False, 'error': t('api.processNotYours')}), 403
    if status == 'failed':
        # The child is still alive; the panel must keep its row and show the OS's own sentence.
        return jsonify({'ok': False, 'error': reason or t('api.processStopFailed'), 'reason': reason}), 409
    # 'gone' (already exited) is not an error: the panel just repaints without it.
    return jsonify({'ok': True, 'stopped': status == 'stopped', 'reason': reason if status == 'stopped' else ''})
