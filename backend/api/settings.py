"""Runtime settings Blueprint — ``GET``/``POST /api/settings``.

Machine-local values that used to be hardcoded (chromedriver path, browser window, timeouts,
Ollama address), persisted to ``data/settings.json`` by the settings store; crawlers and LLM
calls read them per run, so a save applies on the next execution without restarting the server.
Depends only on ``api.http`` (body parsing) and ``settings_store`` — neither touches run state,
so this cluster splits out cleanly. Paths unchanged; app-level ``before_request`` / CORS still wrap.
"""

from flask import Blueprint, jsonify

from api.http import _bad_body, _json_body
from settings_store import all_settings, save_settings

bp = Blueprint('settings', __name__)


@bp.route('/api/settings', methods=['GET'])
def get_runtime_settings():
    return jsonify({'ok': True, 'settings': all_settings()})


@bp.route('/api/settings', methods=['POST'])
def set_runtime_settings():
    data = _json_body()
    if data is None:
        return _bad_body()
    patch = data.get('settings') if isinstance(data.get('settings'), dict) else data
    values, warnings = save_settings(patch or {})
    return jsonify({'ok': True, 'settings': values, 'warnings': warnings})
