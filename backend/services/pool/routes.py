"""``/api/pool/*`` — the account/exit pool's read side and its four levers.

The panel is deliberately given *facts*, never a rule: which logins exist, which are cooling
and until when, which exit each one leaves through, and what the last attempts did. The
cooldown itself is decided in :mod:`services.pool.health` from a measured failure, so a
browser whose clock is off by a few minutes cannot talk the server into trying a login the
server has already benched.

Writes are the operator's: with accounts on the machine, the exit inventory and the
disable/unfreeze levers answer to the administrator, exactly like the other machine-wide
settings. Reads stay open to the signed-in account, because the panel that shows "1 usable,
2 cooling" is the account's own.

Every refusal names itself and is a JSON envelope the panel already parses (``{ok, error}``),
never an HTML error page.
"""

import logging
import time

from api.auth import is_admin
from api.http import _bad_body, _json_body
from flask import Blueprint, jsonify
from runtime.state import cookie_manager
from sessions import preflight
from sessions.cookies import CookieManager

from i18n import t
from services.accounts.service import accounts_mode
from services.pool import enabled as pool_enabled
from services.pool import health as pool_health
from services.pool import store

logger = logging.getLogger(__name__)

bp = Blueprint('pool', __name__)


def _admin_ok() -> bool:
    """Whether this caller may change the pool. A single-user install is its own operator."""
    return not accounts_mode() or is_admin()


def _deny():
    return jsonify({'ok': False, 'error': t('pool.adminOnly')}), 403


def _platform(value) -> str:
    return str(value or '').strip()


def _stamp(value) -> str:
    """An epoch as the server's own local wall-clock string, or '' — never the browser's zone."""
    try:
        stamp = float(value or 0)
    except (TypeError, ValueError):
        return ''
    if stamp <= 0:
        return ''
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(stamp))


def _account_rows() -> list:
    """Every saved login with its health, its binding and the words the panel needs.

    One row per ``(platform, account)`` — the same grain as the Cookie manager's table, so
    the pool tab is an extension of that list rather than a second inventory that can
    disagree with it about which logins exist.
    """
    rows = []
    for platform in CookieManager.PLATFORMS:
        accounts = cookie_manager.accounts_in_order(platform)
        if not accounts:
            continue
        for account in accounts:
            health = store.get_health('account', platform, account)
            state = pool_health.effective_state(health)
            exit_id = store.binding_exit_id(platform, account)
            exit_row = store.get_exit(exit_id) if exit_id else {}
            label_key, label_args = cookie_manager.account_label_key(account)
            rows.append(
                {
                    'platform': platform,
                    'account': account,
                    'label_key': label_key or '',
                    'label_args': label_args,
                    'state': state,
                    'reason': str(health.get('reason') or ''),
                    'cool_until_local': str(health.get('cool_until_local') or ''),
                    'strikes': int(health.get('strikes') or 0),
                    'last_attempt_local': _stamp(health.get('last_attempt_at')),
                    'last_ok_local': _stamp(health.get('last_ok_at')),
                    'exit_id': exit_id,
                    'exit_name': str(exit_row.get('name') or ''),
                    'has_session': bool(cookie_manager.exists(platform, account)),
                }
            )
    return rows


def _exit_rows() -> list:
    """The exit inventory with, for each one, its per-platform health.

    Per PLATFORM on purpose: the same proxy can be banned by zhihu and serve YouTube, so a
    single "is this exit alive" badge would be the wrong answer for both sites.
    """
    rows = []
    # One read of the health table for the whole list: a query per exit would make the
    # panel's refresh cost grow with the inventory it is meant to summarise.
    health_rows = store.health_rows()
    for row in store.list_exits():
        states = []
        for item in health_rows:
            if item.get('kind') == 'exit' and item.get('subject') == row['id']:
                states.append(
                    {
                        'platform': item.get('platform') or '',
                        'state': pool_health.effective_state(item),
                        'reason': str(item.get('reason') or ''),
                        'cool_until_local': str(item.get('cool_until_local') or ''),
                    }
                )
        out = dict(row)
        out['states'] = states
        rows.append(out)
    return rows


@bp.route('/api/pool/state', methods=['GET'])
def pool_state():
    """Everything the pool panel renders, in one read.

    ``summary`` counts accounts per platform, and the state comes from the same store the
    rotation reads. The panel prints the server's numbers; it never re-derives "cooling"
    from the timestamp.
    """
    accounts = _account_rows()
    by_platform = {}
    for row in accounts:
        bucket = by_platform.setdefault(row['platform'], {'usable': 0, 'cooling': 0, 'disabled': 0})
        if row['state'] == 'ok':
            bucket['usable'] += 1
        elif row['state'] == 'disabled':
            bucket['disabled'] += 1
        else:
            bucket['cooling'] += 1
    return jsonify(
        {
            'ok': True,
            'enabled': bool(pool_enabled()),
            'platforms': sorted(by_platform),
            'summary': by_platform,
            'accounts': accounts,
            'exits': _exit_rows(),
            'events': store.recent_events(200),
        }
    )


@bp.route('/api/pool/account/reset', methods=['POST'])
def pool_account_reset():
    """The human override: a timed-out cooldown is cleared now, not when the clock says so."""
    if not _admin_ok():
        return _deny()
    body = _json_body()
    if body is None:
        return _bad_body()
    platform = _platform(body.get('platform'))
    account = str(body.get('account') or '').strip()
    count = store.reset('account', platform, account)
    if platform:
        # A verdict cached before the unfreeze describes a file the user has just declared
        # healthy; keeping it would refuse a run over a measurement that was overruled.
        preflight.invalidate(platform)
    message = (
        t('pool.account.reset', platform=platform, account=account) if account else t('pool.account.resetAll', n=count)
    )
    return jsonify({'ok': True, 'count': count, 'message': message})


@bp.route('/api/pool/account/disable', methods=['POST'])
def pool_account_disable():
    """Manual stop/resume. A disabled subject never expires on a clock, by design."""
    if not _admin_ok():
        return _deny()
    body = _json_body()
    if body is None:
        return _bad_body()
    platform = _platform(body.get('platform'))
    account = str(body.get('account') or '').strip()
    if not platform or not account:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_account(account):
        return jsonify({'ok': False, 'error': t('pool.badAccount', account=account)}), 400
    disabled = bool(body.get('disabled'))
    store.set_disabled('account', platform, account, disabled)
    preflight.invalidate(platform)
    key = 'pool.account.disabled' if disabled else 'pool.account.enabled'
    return jsonify({'ok': True, 'message': t(key, platform=platform, account=account)})


@bp.route('/api/pool/exit/save', methods=['POST'])
def pool_exit_save():
    """Create or edit one exit. A blank password keeps the stored one (the panel never sees it)."""
    if not _admin_ok():
        return _deny()
    body = _json_body()
    if body is None:
        return _bad_body()
    try:
        row = store.save_exit(body)
    except ValueError as e:
        text = str(e).lower()
        if 'scheme' in text:
            return jsonify({'ok': False, 'error': t('pool.exit.badScheme', scheme=body.get('scheme') or '')}), 400
        if 'port' in text:
            return jsonify({'ok': False, 'error': t('pool.exit.badPort', port=body.get('port') or '')}), 400
        return jsonify({'ok': False, 'error': t('pool.exit.badHost')}), 400
    return jsonify(
        {
            'ok': True,
            'exit': row,
            'message': t('pool.exit.saved', name=row.get('name') or row.get('id')),
        }
    )


@bp.route('/api/pool/exit/delete', methods=['POST'])
def pool_exit_delete():
    if not _admin_ok():
        return _deny()
    body = _json_body()
    if body is None:
        return _bad_body()
    exit_id = str(body.get('id') or '').strip()
    row = store.get_exit(exit_id)
    if not row:
        return jsonify({'ok': False, 'error': t('pool.exit.notFound', id=exit_id)}), 404
    store.delete_exit(exit_id)
    return jsonify({'ok': True, 'message': t('pool.exit.deleted', name=row.get('name') or exit_id)})


@bp.route('/api/pool/exit/import', methods=['POST'])
def pool_exit_import():
    """Bulk paste, one proxy per line.

    Each line is validated by the same :func:`store.save_exit` the single form uses, and a
    bad line is counted rather than aborting the batch — a list of forty proxies with one
    typo should not cost the other thirty-nine.
    """
    if not _admin_ok():
        return _deny()
    body = _json_body()
    if body is None:
        return _bad_body()
    raw = body.get('text') or ''
    if not isinstance(raw, str):
        return jsonify({'ok': False, 'error': t('api.paramInvalid', name='text')}), 400
    kept = 0
    skipped = 0
    errors = []
    for line_no, line in enumerate(raw.splitlines(), 1):
        parts = line.strip().split()
        if not parts:
            continue
        try:
            store.save_exit(_parse_import_line(parts))
            kept += 1
        except ValueError as e:
            skipped += 1
            if len(errors) < 5:
                errors.append(f'{line_no}: {e}')
    return jsonify(
        {
            'ok': True,
            'saved': kept,
            'skipped': skipped,
            'errors': errors,
            'message': t('pool.exit.imported', n=kept, skipped=skipped),
        }
    )


def _parse_import_line(parts: list) -> dict:
    """One pasted line → the same payload the form posts.

    ``host:port`` is required, either first or after the name; tokens after it are the
    username and password. Both orders are accepted because proxy providers export them
    both ways, and refusing a common shape costs a manual retype per line.
    """
    index = next((i for i, token in enumerate(parts) if _is_address(token)), -1)
    if index < 0:
        raise ValueError(f'expected host:port, got {" ".join(parts)!r}')
    address = parts[index]
    host, _, port = address.rpartition(':')
    payload = {'host': host, 'port': port, 'scheme': 'http'}
    if index > 0:
        payload['name'] = ' '.join(parts[:index])
    rest = list(parts[index + 1 :])
    if rest:
        payload['username'] = rest.pop(0)
    if rest:
        payload['password'] = rest.pop(0)
    return payload


def _is_address(token: str) -> bool:
    """``host:port`` with a numeric port — the one token whose position is unambiguous."""
    host, _, port = str(token or '').partition(':')
    return bool(host) and port.isdigit()


@bp.route('/api/pool/bind', methods=['POST'])
def pool_bind():
    """Pin an account to one exit, or clear the pin so assignment is automatic again."""
    if not _admin_ok():
        return _deny()
    body = _json_body()
    if body is None:
        return _bad_body()
    platform = _platform(body.get('platform'))
    account = str(body.get('account') or '').strip()
    if not platform or not account:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_account(account):
        return jsonify({'ok': False, 'error': t('pool.badAccount', account=account)}), 400
    exit_id = str(body.get('exit_id') or '').strip()
    if exit_id:
        row = store.get_exit(exit_id)
        if not row:
            return jsonify({'ok': False, 'error': t('pool.exit.notFound', id=exit_id)}), 404
        store.bind(platform, account, exit_id)
        message = t('pool.bind.done', platform=platform, account=account, exit=row.get('name') or exit_id)
    else:
        store.bind(platform, account, '')
        message = t('pool.bind.cleared', platform=platform, account=account)
    return jsonify({'ok': True, 'message': message})
