"""AI (LLM) Blueprint — the transport picker endpoints.

The settings panel chooses a transport (local Ollama daemon or OpenRouter ``:free``); the API key
never touches disk here — the browser keeps it in localStorage and posts it per request. Three
endpoints: the OpenRouter catalog, the local daemon's tags, and a tiny round-trip test. Depends on
``analyzers.llm_client`` + ``transport`` + ``api.http`` + ``settings_store``; no run state, no
stores. ``LLMClient`` is the same class ``app.py`` imports, so tests that stub
``app_module.LLMClient.chat`` still reach this route. Paths unchanged.
"""

import logging
import time

import requests
from flask import Blueprint, jsonify
from transport import _local_transport_refusal

from analyzers.llm_client import LLMClient, LLMError, list_free_models, list_ollama_models
from api.http import _bad_body, _json_body
from config import Config
from i18n import t
from settings_store import get_setting

logger = logging.getLogger('api.llm')

bp = Blueprint('llm', __name__)


@bp.route('/api/llm/models', methods=['GET'])
def llm_models():
    """Current OpenRouter catalog filtered to zero-cost models, so the
    dropdown never goes stale the way a hardcoded list would."""
    try:
        models = list_free_models(timeout=15)
        return jsonify({'ok': True, 'models': models})
    except (requests.RequestException, ValueError, KeyError) as e:
        # Offline / catalog changed shape: the panel just shows no models.
        logger.warning(t('api.llmModelsFailed', err=e))
        return jsonify({'ok': False, 'error': t('api.llmModelsFailed', err=e), 'models': []}), 502


@bp.route('/api/llm/ollama/models', methods=['GET'])
def llm_ollama_models():
    """Tags the local daemon has pulled, so the AI panel can offer a picker
    instead of demanding a hand-typed model name.

    Kept apart from /api/llm/models (the OpenRouter catalog) on purpose: the
    two providers no longer share a model setting, so they must not share a
    dropdown either.
    """
    host = str(get_setting('ollama_host') or '')
    shown = host or 'http://localhost:11434'
    if Config.CLOUD_MODE:
        # Named, not empty: a 502 saying "connection refused on 11434" reads as a broken
        # button, and this deployment has no button to break — the panel is told not to
        # offer one, and a saved workflow or a stale tab that asks anyway gets the reason.
        return jsonify({'ok': False, 'error': _local_transport_refusal('ollama'), 'models': []}), 400
    try:
        models = list_ollama_models(host, timeout=8)
        return jsonify({'ok': True, 'models': models, 'host': shown})
    except (requests.RequestException, ValueError) as e:
        # Daemon not running / wrong address / something else answering on the
        # port: the panel shows the reason *and* the address it tried, which is
        # the whole point of the button.
        logger.warning(t('api.ollamaModelsFailed', host=shown, err=e))
        return jsonify({'ok': False, 'error': t('api.ollamaModelsFailed', host=shown, err=e), 'models': []}), 502


@bp.route('/api/llm/test', methods=['POST'])
def llm_test():
    """Tiny round-trip so the user can validate provider/model/key before
    committing to a long row-by-row run."""
    data = _json_body()
    if data is None:
        return _bad_body()
    provider = data.get('provider') or 'ollama'
    refusal = _local_transport_refusal(provider)
    if refusal:
        # Refused before a client is built: the point of this route is to tell the user
        # whether a transport answers, and on a cloud host the answer to a local-daemon
        # request is known before the request — nothing is listening on this machine.
        return jsonify({'ok': False, 'error': refusal}), 400
    client = LLMClient(
        provider=provider,
        model=data.get('model') or '',
        api_key=data.get('api_key') or '',
        max_tokens=16,
        max_chars=0,
        timeout=60 if provider == 'ollama' else 45,
        host=str(get_setting('ollama_host') or '') if provider == 'ollama' else '',
    )
    started = time.time()
    try:
        reply = client.chat('Reply with exactly: OK', max_retries=1)
        latency = int((time.time() - started) * 1000)
        return jsonify(
            {
                'ok': True,
                'latency_ms': latency,
                'reply': reply.strip()[:80],
                'provider': client.label,
                'model': client.model,
                # Which daemon answered — with the local transport the address
                # is half of "why did this fail", so the panel can show it.
                'host': client.host if provider == 'ollama' else '',
            }
        )
    except LLMError as e:
        return jsonify({'ok': False, 'error': str(e), 'kind': e.kind})
    except Exception as e:
        # The test endpoint reports the failure; it never raises.
        return jsonify({'ok': False, 'error': str(e), 'kind': 'error'})
