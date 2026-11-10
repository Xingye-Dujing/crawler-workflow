"""Self-update routes: check the feed, download the app payload, stage and restart."""

from __future__ import annotations

import os
import signal
import threading

from flask import Blueprint, jsonify
from runtime.state import execution_state

from api.auth import is_admin
from i18n import t
from services import update
from services.accounts.service import accounts_mode

bp = Blueprint('update', __name__)


def _admin_refusal():
    """Why this caller may not replace the program on this machine.

    ``apply_update`` spawns the swap script and restarts this process; ``start_download`` stages a
    new payload beside the install. Both are host-level acts — the same door ``/api/settings``,
    ``/api/lexicon`` and ``/api/components`` guard — so on an accounts host only the administrator
    may press them. The panel hides the banner for other accounts; hiding is cosmetic, the 403 is
    the permission.
    """
    if accounts_mode() and not is_admin():
        return jsonify({'ok': False, 'error': t('accounts.adminRequired')}), 403
    return None


def _running() -> bool:
    return bool(execution_state.get('running'))


@bp.get('/api/update/check')
def update_check():
    """Who may ask. The answer leaves the machine (two HTTPS feeds) and, when a package is
    already staged, ``check()`` prunes ``data/updates`` — both are host-level acts, the same door
    ``download``/``apply`` guard. The panel hides the banner for other accounts; hiding is
    cosmetic, the 403 is the permission."""
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    return jsonify(update.check())


@bp.post('/api/update/download')
def update_download():
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    if _running():
        return jsonify({'ok': False, 'error': t('api.updateRunning')}), 409
    result = update.start_download()
    if not result.get('ok'):
        result = {'ok': False, 'error': t('api.updateDownloadFailed', err=result.get('error', ''))}
        return jsonify(result), 400
    return jsonify(result)


@bp.get('/api/update/job/<job_id>')
def update_job(job_id: str):
    current = update.job(job_id)
    if not current:
        return jsonify({'ok': False, 'error': t('api.updateJobMissing')}), 404
    return jsonify({'ok': True, 'job': current})


def _restart_now() -> None:
    """Let the HTTP response leave, then end this process so the swap script can run."""
    os.kill(os.getpid(), signal.SIGTERM)


@bp.post('/api/update/apply')
def update_apply():
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    if _running():
        return jsonify({'ok': False, 'error': t('api.updateRunning')}), 409
    result = update.apply_update()
    if not result.get('ok'):
        return jsonify({'ok': False, 'error': t('api.updateApplyFailed', err=result.get('error', ''))}), 400
    threading.Timer(1.5, _restart_now).start()
    return jsonify(result)
