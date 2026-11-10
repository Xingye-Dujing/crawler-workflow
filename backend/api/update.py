"""Self-update routes: check the feed, download the app payload, stage and restart."""

from __future__ import annotations

import os
import signal
import threading

from flask import Blueprint, jsonify
from runtime.state import execution_state

from i18n import t
from services import update

bp = Blueprint('update', __name__)


def _running() -> bool:
    return bool(execution_state.get('running'))


@bp.get('/api/update/check')
def update_check():
    return jsonify(update.check())


@bp.post('/api/update/download')
def update_download():
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
        return jsonify({'ok': False, 'error': 'unknown update job'}), 404
    return jsonify({'ok': True, 'job': current})


def _restart_now() -> None:
    """Let the HTTP response leave, then end this process so the swap script can run."""
    os.kill(os.getpid(), signal.SIGTERM)


@bp.post('/api/update/apply')
def update_apply():
    if _running():
        return jsonify({'ok': False, 'error': t('api.updateRunning')}), 409
    result = update.apply_update()
    if not result.get('ok'):
        return jsonify({'ok': False, 'error': t('api.updateApplyFailed', err=result.get('error', ''))}), 400
    threading.Timer(1.5, _restart_now).start()
    return jsonify(result)
