"""Self-update routes: check the feed, stage the payload, restart, cancel.

The server owns every decision (is there a release, is it verifiable, can this install replace
itself) and the browser owns none of them: it paints what these four routes say. The job itself
lives on disk (``services.update_job``) so a page reload, a second window or a closed window all
continue the same download instead of starting a new opinion about it.
"""

from __future__ import annotations

import os
import signal
import threading

from flask import Blueprint, jsonify
from runtime import state as runtime_state
from runtime.state import execution_state

from api.auth import is_admin
from i18n import t
from services import update, update_job
from services.accounts.service import accounts_mode

bp = Blueprint('update', __name__)


def _admin_refusal():
    """Why this caller may not replace the program on this machine.

    ``restart`` ends this process and the swapper replaces the program on disk; ``download``
    stages a new payload beside the install. Both are host-level acts — the same door
    ``/api/settings``, ``/api/lexicon`` and ``/api/components`` guard — so on an accounts host only
    the administrator may press them. The panel hides the card for other accounts; hiding is
    cosmetic, the 403 is the permission.
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
    ``download``/``restart`` guard. The panel hides the card for other accounts; hiding is
    cosmetic, the 403 is the permission."""
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    return jsonify(update.check())


@bp.post('/api/update/download')
def update_download():
    """Start (or resume) the download in a detached worker.

    No run guard here on purpose: the download is a separate process, so a crawl in flight no
    longer costs the user an update — only the *restart* has to wait for the crawl.
    """
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    result = update.prepare()
    if not result.get('ok'):
        result = {'ok': False, 'error': t('api.updateDownloadFailed', err=result.get('error', ''))}
        return jsonify(result), 400
    return jsonify(result)


@bp.get('/api/update/status')
def update_status():
    """The job as it stands, plus the tail of the updater's log.

    Reads straight from disk, which is what makes a refresh (or a window closed mid-download)
    reattach to the same job. It may settle a job whose worker died — a stale ``downloading``
    state would otherwise keep the panel spinning forever.
    """
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    return jsonify({'ok': True, 'job': update.status(), 'log': update_job.log_tail()})


@bp.post('/api/update/cancel')
def update_cancel():
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    result = update.cancel()
    if not result.get('ok'):
        return jsonify({'ok': False, 'error': t('api.updateCancelFailed', err=result.get('error', ''))}), 400
    return jsonify(result)


def _quit_soon() -> None:
    """Let the HTTP response leave, then end this process so the swap script can run.

    Through the launcher's own shutdown hook when there is one: that path closes the window and
    runs the same cleanup a user close does (server shutdown, instance file, swept litter), which
    is also what releases the executable before the swapper touches it. A hard signal remains the
    fallback for a host that registered nothing — it is never the first choice.
    """
    if runtime_state.request_shutdown():
        return
    os.kill(os.getpid(), signal.SIGTERM)


@bp.post('/api/update/restart')
def update_restart():
    refusal = _admin_refusal()
    if refusal is not None:
        return refusal
    if _running():
        return jsonify({'ok': False, 'error': t('api.updateRunning')}), 409
    result = update.request_restart()
    if not result.get('ok'):
        return jsonify({'ok': False, 'error': t('api.updateRestartFailed', err=result.get('error', ''))}), 400
    threading.Timer(1.5, _quit_soon).start()
    return jsonify(result)
