"""Account management: the signed-in user's own view, and the admin's registry operations.

The service (``services.accounts.service``) owns every rule; this module only reads the request,
translates an :class:`AccountError` into its catalogue sentence and a status, and never serialises
a password or a hash. Content endpoints stay per-account through ``runtime/paths.py``: an admin
manages accounts, not other people's datasets.
"""

from flask import Blueprint, jsonify, request
from runtime import stores
from runtime.state import _RUN_QUEUE, execution_state

from api.auth import current_sid, current_user
from api.http import _bad_body, _json_body
from i18n import t
from services.accounts.errors import AccountError
from services.accounts.service import get_account_service

bp = Blueprint('accounts', __name__)

_STATUS = {
    'accounts.adminRequired': 403,
    'accounts.notFound': 404,
    'accounts.lastAdmin': 409,
    'accounts.cannotDisableSelf': 409,
    'accounts.cannotDeleteSelf': 409,
    'accounts.accountBusy': 409,
    'accounts.usernameTaken': 409,
    'accounts.tooManyAttempts': 429,
}
_DEFAULT_STATUS = 400


def _fail(exc: AccountError):
    return jsonify({'ok': False, 'error': t(exc.key, **exc.params)}), _STATUS.get(exc.key, _DEFAULT_STATUS)


def _busy_run(user_id: str) -> str:
    """The run id this account owns right now (in flight or parked), or ``''``.

    A run's worker writes through the account's stores; deleting or disabling that account while
    it is alive would pull the database out from under it.
    """
    if execution_state.get('running') and str(execution_state.get('user_id') or '') == str(user_id):
        return str(execution_state.get('run_id') or 'current')
    for entry in list(_RUN_QUEUE):
        if str(entry.get('user_id') or '') == str(user_id):
            return str(entry.get('run_id') or 'queued')
    return ''


def _guard_idle(user_id: str) -> None:
    busy = _busy_run(user_id)
    if busy:
        raise AccountError('accounts.accountBusy', run=busy)


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
    return jsonify({'ok': True, 'user': user})


@bp.route('/api/accounts/<user_id>/status', methods=['POST'])
def accounts_set_status(user_id: str):
    payload = _json_body()
    if payload is None:
        return _bad_body()
    status = str(payload.get('status') or '')
    try:
        if status == 'disabled':
            _guard_idle(user_id)
        user = get_account_service().set_status(current_user(), user_id, status)
    except AccountError as exc:
        return _fail(exc)
    if status == 'disabled':
        stores.release_user(user_id)
    return jsonify({'ok': True, 'user': user})


@bp.route('/api/accounts/<user_id>/logout', methods=['POST'])
def accounts_force_logout(user_id: str):
    if _json_body() is None:
        return _bad_body()
    try:
        user = get_account_service().force_logout(current_user(), user_id)
    except AccountError as exc:
        return _fail(exc)
    return jsonify({'ok': True, 'user': user})


@bp.route('/api/accounts/<user_id>', methods=['DELETE'])
def accounts_delete(user_id: str):
    payload = _json_body()
    if payload is None:
        return _bad_body()
    try:
        _guard_idle(user_id)
        user = get_account_service().delete_user(
            current_user(),
            user_id,
            str(payload.get('confirm_username') or ''),
        )
    except AccountError as exc:
        return _fail(exc)
    stores.release_user(user_id)
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
