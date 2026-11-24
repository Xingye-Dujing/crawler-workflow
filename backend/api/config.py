"""Config / registry Blueprint — read-only ``GET /api/config`` and ``GET /api/models``.

Server facts the browser must be told rather than guess (default model, headless, worker cap, and
whether this is a cloud host), plus the friendly-name view of the fine-tuned model registry. Both
depend only on ``config.Config`` and the standard library — no run state, no stores — so this
cluster splits out cleanly. ``/api/capabilities`` is its own Blueprint (``api/capabilities.py``): it
extends the crawl matrix with ``sessions.cookies``'s live account list. Paths unchanged.
"""

from core.config import Config
from flask import Blueprint, jsonify
from runtime.account_context import current as current_account

from services.accounts.service import accounts_mode
from services.components import source as component_source

bp = Blueprint('config', __name__)


@bp.route('/api/config', methods=['GET'])
def get_config():
    account = current_account()
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
            # A `?autorun=1` link starts a real run (and can spend accounts/tokens). Only the demo
            # recorder's isolated servers opt in; the page loads a linked canvas but never starts it
            # on a host that did not explicitly allow it.
            'demo_autorun': Config.DEMO_AUTORUN,
            # The installer's component tree exists on this host. A source checkout and a
            # cloud/portable deploy have none: offering “安装器安装的” there names a copy
            # that cannot exist, so the page hides that choice and the installer list.
            'installer_available': component_source.installer_available(),
            # Whether this host asks for a login. The page shows 退出登录 only when it does, and
            # keeps the button out of a desktop session that has no session to end.
            'auth_required': accounts_mode(),
            # The signed-in account's own view: identity for the top bar, the one CSRF token every
            # mutating fetch must echo, and whether the change-password dialog is mandatory. A
            # password or a hash never appears here.
            'auth': {
                'enabled': accounts_mode(),
                'must_change_password': bool(account.must_change_password) if account is not None else False,
                'csrf_token': str(account.csrf_token or '') if account is not None else '',
                'user': ({'username': account.username, 'role': account.role} if account is not None else None),
            },
        },
    )


@bp.route('/api/models', methods=['GET'])
def list_models():
    """Registered fine-tuned models by friendly NAME, so the bert-mode picker can show “网暴模型”
    instead of a bare path. A missing or malformed registry is an empty list, never an error — a
    node with no named models still accepts a path."""
    from services.models import catalog

    return jsonify({'ok': True, 'models': catalog.legacy_rows()})


@bp.route('/api/models/catalog', methods=['GET'])
def list_model_catalog():
    """The rich model catalogue: task, output columns, licence, metrics, and this host's verdict.

    The AI workspace and the model picker read the SAME catalogue the executor resolves from; a
    second list in the browser would be a second opinion about which model produced a column.
    """
    from services.models import catalog, probe

    return jsonify(
        {
            'ok': True,
            'models': catalog.public_rows(),
            'runtime': probe.runtime_state(include_cuda=True),
        }
    )
