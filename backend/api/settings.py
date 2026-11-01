"""Runtime settings Blueprint — ``GET``/``POST /api/settings``.

Machine-local values that used to be hardcoded (chromedriver path, browser window, timeouts,
Ollama address), persisted to ``data/settings.json`` by the settings store; crawlers and LLM
calls read them per run, so a save applies on the next execution without restarting the server.
Depends only on ``api.http`` (body parsing) and ``runtime.settings`` — neither touches run state,
so this cluster splits out cleanly. Paths unchanged; app-level ``before_request`` / CORS still wrap.

Who may do what:

* an administrator may read everything and may write;
* any other signed-in account may READ the values its own runs live under, but not change
  them — one account must not be able to move every other account's chromedriver, browser
  or proxy. The write has been gated that way since accounts existed; what was missing is
  the read side (it handed every account the machine's absolute paths) and the panel's
  ability to SAY the fields are read-only instead of letting a user type into one and be
  refused by a 403 at save time.
"""

from flask import Blueprint, jsonify
from runtime.settings import all_settings, save_settings

from api.auth import is_admin
from api.http import _bad_body, _json_body
from i18n import t
from services.accounts.service import accounts_mode

bp = Blueprint('settings', __name__)

#: The keys naming a FILE ON THIS MACHINE — a driver, a browser binary, a proxy, a profile
#: directory. They are not secret in the cryptographic sense, but they are a fingerprint of
#: the host and a map of what to aim at, and no other account has any use for them: the
#: values a non-administrator needs in order to understand its own runs are the timeouts,
#: the switches and the Ollama address it will be calling.
_MACHINE_PATH_KEYS = (
    'driver_path',
    'browser_binary',
    'latex_binary',
    'catbus_cli',
    'catbus_node',
    'browser_profile_dir',
    'hongguo_player_path',
    'mitmdump_path',
)


def _visible(values: dict, admin: bool) -> dict:
    """The settings as this caller may see them: everything for an admin, no host paths otherwise."""
    if admin or not isinstance(values, dict):
        return dict(values)
    return {key: ('' if key in _MACHINE_PATH_KEYS else value) for key, value in values.items()}


@bp.route('/api/settings', methods=['GET'])
def get_runtime_settings():
    admin = not accounts_mode() or is_admin()
    return jsonify(
        {
            'ok': True,
            'settings': _visible(all_settings(), admin),
            # Told, not inferred: the panel disables its fields rather than letting the user
            # fill one in and meet a 403 at save time.
            'read_only': not admin,
        }
    )


@bp.route('/api/settings', methods=['POST'])
def set_runtime_settings():
    if accounts_mode() and not is_admin():
        # ``settings.json`` is machine-level (driver/browser paths, timeouts, Ollama address), so
        # on an accounts host only the administrator may rewrite what every account runs against.
        return jsonify({'ok': False, 'error': t('accounts.adminRequired')}), 403
    data = _json_body()
    if data is None:
        return _bad_body()
    patch = data.get('settings') if isinstance(data.get('settings'), dict) else data
    values, warnings = save_settings(patch or {})
    return jsonify({'ok': True, 'settings': values, 'warnings': warnings})
