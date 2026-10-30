"""Config / registry Blueprint — read-only ``GET /api/config`` and ``GET /api/models``.

Server facts the browser must be told rather than guess (default model, headless, worker cap, and
whether this is a cloud host), plus the friendly-name view of the fine-tuned model registry. Both
depend only on ``config.Config`` and the standard library — no run state, no stores — so this
cluster splits out cleanly. ``/api/capabilities`` deliberately stays in ``app.py`` for now: it
extends the crawl matrix with ``sessions.cookies``'s live account list. Paths unchanged.
"""

import json
import os

from core.config import Config
from flask import Blueprint, jsonify

bp = Blueprint('config', __name__)


@bp.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(
        {
            'ollama_model': Config.OLLAMA_MODEL,
            'default_headless': Config.DEFAULT_HEADLESS,
            'max_workers': Config.DEFAULT_MAX_WORKERS,
            # The browser hides what cannot work here (the whole Ollama UI, the headless switch,
            # the cookie-generating button) and shows what a stranger on a shared server has to be
            # told once: where its own data lands. It is a fact about the server, so the server
            # says it — a frontend guess would be a second opinion about the deployment.
            'cloud_mode': Config.CLOUD_MODE,
            # Whether this host asks for a login. The page shows 退出登录 only when it does, and
            # keeps the button out of a desktop session that has no session to end.
            'auth_required': bool(str(Config.AUTH_PASSWORD or '').strip()),
        },
    )


@bp.route('/api/models', methods=['GET'])
def list_models():
    """Registered fine-tuned models by friendly NAME, so the bert-mode picker can show 「网暴模型」
    instead of a bare path. A missing or malformed registry is an empty list, never an error — a
    node with no named models still accepts a path."""
    return jsonify({'ok': True, 'models': read_model_registry()})


def read_model_registry() -> list:
    """The registry as a list of ``{name, path, desc, operation}``, from ``data/model_registry.json``.

    One reader shared by the picker and the executor (``default_model_path_for``), so the friendly
    name the panel shows and the model a default bert run actually loads can never disagree. A
    missing/malformed file is an empty list, never an error.
    """
    path = os.path.join(Config.DATA_DIR, 'model_registry.json')
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        {
            'name': str(m.get('name') or ''),
            'path': str(m.get('path') or ''),
            'desc': str(m.get('desc') or ''),
            'operation': str(m.get('operation') or ''),
        }
        for m in data
        if isinstance(m, dict) and str(m.get('path') or '').strip()
    ]


def default_model_path_for(operation: str) -> str:
    """The registry path of the FIRST model tagged ``operation``, or ``''`` when none is registered.

    This is what makes a default ``bert`` node actually mean bert: when a node names no model, the
    executor resolves the operation's registered default here (registry order is the operator's
    preference — e.g. the 「推荐」 tendency model is listed first). ``''`` means "nothing to load",
    which the executor treats as bert-unavailable and degrades to the general mode with a printed line.
    """
    want = str(operation or '').strip()
    for model in read_model_registry():
        if model['operation'] == want:
            return model['path']
    return ''
