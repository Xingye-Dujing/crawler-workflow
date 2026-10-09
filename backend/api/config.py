"""Config / registry Blueprint — read-only ``GET /api/config`` and ``GET /api/models``.

Server facts the browser must be told rather than guess (default model, headless, worker cap, and
whether this is a cloud host), plus the friendly-name view of the fine-tuned model registry. Both
depend only on ``config.Config`` and the standard library — no run state, no stores — so this
cluster splits out cleanly. ``/api/capabilities`` deliberately stays in ``app.py`` for now: it
extends the crawl matrix with ``cookie_manager``'s live account list. Paths unchanged.
"""

import json
import os

from flask import Blueprint, jsonify

from config import Config

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
        },
    )


@bp.route('/api/models', methods=['GET'])
def list_models():
    """Registered fine-tuned models by friendly NAME, so the bert-mode picker can show 「网暴模型」
    instead of a bare path. The registry is a runtime file (data/model_registry.json); a missing or
    malformed one is an empty list, never an error — a node with no named models still accepts a path."""
    path = os.path.join(Config.DATA_DIR, 'model_registry.json')
    models = []
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, list):
            models = [
                {'name': str(m.get('name') or ''), 'path': str(m.get('path') or ''), 'desc': str(m.get('desc') or '')}
                for m in data
                if isinstance(m, dict) and str(m.get('path') or '').strip()
            ]
    except (OSError, ValueError):
        models = []
    return jsonify({'ok': True, 'models': models})
