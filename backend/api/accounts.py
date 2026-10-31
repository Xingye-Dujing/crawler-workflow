"""Account management: the signed-in user's own view, and the admin's registry operations.

The service (``services.accounts.service``) owns every rule; this module only reads the request,
translates an :class:`AccountError` into its catalogue sentence and a status, and never serialises
a password or a hash. Content endpoints stay per-account through ``runtime/paths.py``: an admin
manages accounts, not other people's datasets.
"""

import logging
import sqlite3

from flask import Blueprint, jsonify, request
from runtime import stores
from runtime.state import _RUN_QUEUE, execute_lock, execution_state
from sessions.routes import _COOKIE_JOB

from api.auth import current_sid, current_user
from api.http import _bad_body, _json_body
from i18n import t
from services.accounts.errors import AccountError
from services.accounts.service import get_account_service

logger = logging.getLogger(__name__)

bp = Blueprint('accounts', __name__)

_STATUS = {
    'accounts.adminRequired': 403,
    'accounts.notFound': 404,
    'accounts.lastAdmin': 409,
    'accounts.cannotDisableSelf': 409,
    'accounts.cannotDeleteSelf': 409,
    'accounts.accountBusy': 409,
    'accounts.cookieJobBusy': 409,
    'accounts.usernameTaken': 409,
    'accounts.tooManyAttempts': 429,
}
_DEFAULT_STATUS = 400


def _fail(exc: AccountError):
    return jsonify({'ok': False, 'error': t(exc.key, **exc.params)}), _STATUS.get(exc.key, _DEFAULT_STATUS)


def _fail_storage(exc: Exception):
    """A filesystem or database failure, named in the envelope every caller here parses.

    ``shutil.move`` refuses a profile directory a browser still holds, a full disk fails a write,
    SQLite times out: those are operator facts, and an HTML 500 in front of a JSON panel reads as
    a broken button. The traceback goes to the file, and its line is the same catalogue sentence
    the response carries — the buffer handler forwards ``logger.*`` into the console, so an
    English literal here would be an untranslated line nobody asked for."""
    logger.exception(t('accounts.storageFailed', err=type(exc).__name__))
    return jsonify({'ok': False, 'error': t('accounts.storageFailed', err=type(exc).__name__)}), 500


def _busy_run(user_id: str) -> str:
    """The run id this account owns right now (in flight, settling or parked), or ``''``.

    A run's worker writes through the account's stores; deleting or disabling that account while
    it is alive would pull the database out from under it. ``running`` goes false the moment Stop
    is pressed, but the worker keeps settling for tens of seconds — the thread is therefore part
    of the liveness test, exactly as ``begin_run`` asks it.
    """
    thread = execution_state.get('thread')
    live = bool(execution_state.get('running') or (thread is not None and thread.is_alive()))
    if live and str(execution_state.get('user_id') or '') == str(user_id):
        return str(execution_state.get('run_id') or 'current')
    for entry in list(_RUN_QUEUE):
        if str(entry.get('user_id') or '') == str(user_id):
            return str(entry.get('run_id') or 'queued')
    return ''


def _guard_idle(user_id: str, *, cookie_job: bool = False) -> None:
    busy = _busy_run(user_id)
    if busy:
        raise AccountError('accounts.accountBusy', run=busy)
    # A login/verify window holds that account's Chrome profile. Moving the tree under a live
    # browser fails on Windows (the profile files are open) and strands the capture.
    if cookie_job and _COOKIE_JOB.get('active') and str(_COOKIE_JOB.get('owner') or '') == str(user_id):
        raise AccountError('accounts.cookieJobBusy')


@bp.route('/api/account/me', methods=['GET'])
def account_me():
    account = current_user()
    if account is None:
        # The gate would have refused a real request, so this is the local owner's caller.
        return jsonify({'ok': True, 'auth_required': False, 'user': None})
    return jsonify(
        {
            'ok': True,
            'auth_required': True,
            'user': {
                'user_id': account.user_id,
                'username': account.username,
                'role': account.role,
                'must_change_password': bool(account.must_change_password),
            },
        }
    )


@bp.route('/api/account/password', methods=['POST'])
def account_password():
    payload = _json_body()
    if payload is None:
        return _bad_body()
    account = current_user()
    if account is None:
        return jsonify({'ok': False, 'error': t('auth.required')}), 401
    try:
        user = get_account_service().change_password(
            account,
            payload.get('current_password'),
            payload.get('new_password'),
            current_sid(),
        )
    except AccountError as exc:
        return _fail(exc)
    except (OSError, sqlite3.Error) as exc:
        return _fail_storage(exc)
    return jsonify({'ok': True, 'user': user})


@bp.route('/api/accounts', methods=['GET'])
def accounts_list():
    try:
        rows = get_account_service().list_users(current_user())
    except AccountError as exc:
        return _fail(exc)
    return jsonify({'ok': True, 'accounts': rows})


@bp.route('/api/accounts', methods=['POST'])
def accounts_create():
    payload = _json_body()
    if payload is None:
        return _bad_body()
    try:
        user = get_account_service().create_user(
            current_user(),
            payload.get('username'),
            payload.get('password'),
            str(payload.get('role') or 'user'),
        )
    except AccountError as exc:
        return _fail(exc)
    except (OSError, sqlite3.Error) as exc:
        # Creating an account also CREATES its tree (and chmods it on POSIX): that can fail.
        return _fail_storage(exc)
    return jsonify({'ok': True, 'user': user}), 201


@bp.route('/api/accounts/<user_id>/password', methods=['POST'])
def accounts_reset_password(user_id: str):
    payload = _json_body()
    if payload is None:
        return _bad_body()
    try:
        user = get_account_service().reset_password(
            current_user(),
            user_id,
            payload.get('password'),
            bool(payload.get('must_change', True)),
        )
    except AccountError as exc:
        return _fail(exc)
    except (OSError, sqlite3.Error) as exc:
        return _fail_storage(exc)
    return jsonify({'ok': True, 'user': user})


@bp.route('/api/accounts/<user_id>/status', methods=['POST'])
def accounts_set_status(user_id: str):
    payload = _json_body()
    if payload is None:
        return _bad_body()
    status = str(payload.get('status') or '')
    try:
        service = get_account_service()
        actor = current_user()
        if status == 'disabled':
            # Authorize BEFORE probing the target: the busy answer names a run id, and that is
            # another account's fact to hand a caller who is not an administrator at all.
            service.assert_admin(actor)
            with execute_lock:
                # Held across the guard and the release: ``begin_run`` claims under this same
                # lock, so no run can start between "no run is live" and the stores closing.
                _guard_idle(user_id)
                user = service.set_status(actor, user_id, status)
                stores.release_user(user_id)
        else:
            user = service.set_status(actor, user_id, status)
    except AccountError as exc:
        return _fail(exc)
    except (OSError, sqlite3.Error) as exc:
        return _fail_storage(exc)
    return jsonify({'ok': True, 'user': user})


@bp.route('/api/accounts/<user_id>/logout', methods=['POST'])
def accounts_force_logout(user_id: str):
    if _json_body() is None:
        return _bad_body()
    try:
        user = get_account_service().force_logout(current_user(), user_id)
    except AccountError as exc:
        return _fail(exc)
    # "Cut this account off now" also means drop what it holds open — unless a run of its own is
    # still writing through those stores, in which case releasing them would break the run.
    if not _busy_run(user_id):
        stores.release_user(user_id)
    return jsonify({'ok': True, 'user': user})


@bp.route('/api/accounts/<user_id>', methods=['DELETE'])
def accounts_delete(user_id: str):
    payload = _json_body()
    if payload is None:
        return _bad_body()
    confirm = str(payload.get('confirm_username') or '')
    service = get_account_service()
    actor = current_user()
    try:
        with execute_lock:
            # Everything that touches the target happens under the claim lock: a run cannot start
            # between "this account is idle" and its stores closing.
            # Authorize FIRST. A refusal that arrives after ``release_user`` would have closed a
            # live writer's database — and a refusal can arrive (wrong confirmation, a caller who
            # is not an administrator, the last active admin).
            service.check_deletable(actor, user_id, confirm)
            _guard_idle(user_id, cookie_job=True)
            # Close this account's SQLite handles BEFORE the tree is moved. Windows refuses to
            # rename a directory that still holds an open database (and its -wal/-shm), so a
            # delete that released them afterwards could fail on exactly the platform this tool
            # is developed on.
            stores.release_user(user_id)
            user = service.delete_user(actor, user_id, confirm)
    except AccountError as exc:
        return _fail(exc)
    except (OSError, sqlite3.Error) as exc:
        # ``shutil.move`` fails on a profile a browser still holds, a full disk, a locked file:
        # every caller here parses JSON, so an HTML 500 would read as a broken panel.
        return _fail_storage(exc)
    return jsonify({'ok': True, 'user': user})


@bp.route('/api/accounts/audit', methods=['GET'])
def accounts_audit():
    try:
        limit = int(request.args.get('limit') or 200)
    except (TypeError, ValueError):
        limit = 200
    try:
        rows = get_account_service().list_audit(current_user(), limit)
    except AccountError as exc:
        return _fail(exc)
    return jsonify({'ok': True, 'entries': rows})
