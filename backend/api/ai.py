"""AI workspace HTTP surface: providers, conversations, SSE, agent runs and the studio.

Thin by design. The provider catalog, context budget, agent loop and plugin host live under
``backend/ai`` and ``backend/extensions``; this module only turns HTTP into their calls and their
canonical events into SSE frames. An API key is read from the request body and handed to the
provider for that one call; it is never written to SQLite or to a log line.
"""

import json
import logging
import time

from ai import agent, context, plugins, skills, store, tools
from ai.errors import AIError
from ai.providers import get_provider, list_models, public_catalog
from flask import Blueprint, Response, jsonify, request, stream_with_context
from runtime import account_context
from runtime.settings import get_setting

from api.http import _bad_body, _json_body
from i18n import get_lang, set_lang, t

logger = logging.getLogger('api.ai')

bp = Blueprint('ai', __name__)

plugins.register_builtin()


def _error(exc: AIError, status: int = 400):
    return jsonify(exc.as_dict()), status


def _sse(payload: dict) -> str:
    return 'data: ' + json.dumps(payload, ensure_ascii=False, default=str) + '\n\n'


def _stream(generator, account, lang: str):
    def body():
        with account_context.use(account):
            set_lang(lang)
            try:
                for event in generator:
                    yield _sse(event)
            except AIError as exc:
                yield _sse({'type': 'error', 'kind': exc.kind, 'error': exc.localized(), 'key': exc.key})
                yield _sse({'type': 'done', 'stop_reason': 'error'})
            except Exception as exc:  # a provider bug must not kill the whole page
                logger.warning(t('ai.streamFailed', kind=type(exc).__name__))
                yield _sse({'type': 'error', 'kind': 'error', 'error': str(exc)[:500]})
                yield _sse({'type': 'done', 'stop_reason': 'error'})

    return Response(
        stream_with_context(body()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-store',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@bp.route('/api/ai/providers', methods=['GET'])
def ai_providers():
    return jsonify({'ok': True, 'providers': public_catalog()})


@bp.route('/api/ai/providers/<provider_id>/models', methods=['GET'])
def ai_models(provider_id: str):
    try:
        provider = get_provider(provider_id)
    except AIError as exc:
        return _error(exc)
    key = str(request.args.get('key') or '')
    host = str(get_setting('ollama_host') or '') if provider.spec.id == 'ollama' else ''
    try:
        return jsonify({'ok': True, 'models': provider.list_models(key, host), 'provider': provider.spec.id})
    except AIError as exc:
        return _error(exc, 502)


@bp.route('/api/ai/providers/<provider_id>/test', methods=['POST'])
def ai_provider_test(provider_id: str):
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        provider = get_provider(provider_id)
    except AIError as exc:
        return _error(exc)
    model = str(data.get('model') or (provider.spec.models[0].id if provider.spec.models else ''))
    key = str(data.get('api_key') or '')
    if provider.spec.requires_key and not key:
        return _error(AIError('ai.noKey', kind='auth'))
    start = time.time()
    pieces = []
    try:
        for event in provider.stream(
            {
                'model': model,
                'api_key': key,
                'system': 'You are a connection test.',
                'messages': [{'role': 'user', 'content': 'Reply with exactly: OK'}],
                'tools': [],
                'thinking': False,
                'web_search': False,
                'max_tokens': 24,
                'timeout': 45,
                'cancel_event': None,
                'host': str(get_setting('ollama_host') or ''),
            }
        ):
            if event.get('type') == 'text_delta':
                pieces.append(str(event.get('text') or ''))
            if event.get('type') == 'done':
                break
    except AIError as exc:
        return jsonify({**exc.as_dict(), 'kind': exc.kind}), 200
    return jsonify(
        {
            'ok': True,
            'latency_ms': int((time.time() - start) * 1000),
            'reply': ''.join(pieces).strip()[:80],
            'provider': provider.spec.id,
            'model': model,
        }
    )


@bp.route('/api/ai/bootstrap', methods=['GET'])
def ai_bootstrap():
    plugins.register_builtin()
    plugins.register_stored_plugins()
    if not agent.ACTIVE_STREAMS:
        store.mark_interrupted()
    provider_id = str(request.args.get('provider') or 'deepseek')
    model = str(request.args.get('model') or '')
    provider = None
    try:
        provider = get_provider(provider_id)
    except AIError:
        provider = None
    return jsonify(
        {
            'ok': True,
            'providers': public_catalog(),
            'skills': skills.public_skills(provider, model),
            'conversations': store.list_conversations(),
            'usage': store.usage_summary(),
            'settings': {
                'context_scope': get_setting('ai_context_scope'),
                'web_search_default': bool(get_setting('ai_web_search_default')),
                'safety_level': get_setting('ai_safety_level'),
                'max_tool_rounds': int(get_setting('ai_max_tool_rounds') or 0),
                'allow_code_context': bool(get_setting('ai_allow_code_context')),
            },
            'plugins': plugins.public_plugins(),
            'tools': [spec.schema() for spec in tools.TOOLS.values()],
        }
    )


@bp.route('/api/ai/skills', methods=['GET'])
def ai_skills():
    provider_id = str(request.args.get('provider') or '')
    model = str(request.args.get('model') or '')
    provider = None
    if provider_id:
        try:
            provider = get_provider(provider_id)
        except AIError as exc:
            return _error(exc)
    return jsonify({'ok': True, 'skills': skills.public_skills(provider, model)})


@bp.route('/api/ai/skills/<skill_id>', methods=['GET'])
def ai_skill(skill_id: str):
    try:
        skill = skills.get_skill(skill_id)
    except AIError as exc:
        return _error(exc)
    payload = skill.to_manifest()
    payload['builtin'] = skill.builtin
    return jsonify({'ok': True, 'skill': payload})


@bp.route('/api/ai/skills', methods=['POST'])
def ai_skill_save():
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        return jsonify({'ok': True, 'skill': skills.save_user_skill(data)})
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/skills/<skill_id>/fork', methods=['POST'])
def ai_skill_fork(skill_id: str):
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        return jsonify({'ok': True, 'skill': skills.fork_skill(skill_id, str(data.get('id') or ''))})
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/skills/<skill_id>', methods=['DELETE'])
def ai_skill_delete(skill_id: str):
    try:
        return jsonify({'ok': True, 'deleted': skills.delete_user_skill(skill_id)})
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/plugins', methods=['GET'])
def ai_plugins():
    return jsonify({'ok': True, 'plugins': plugins.public_plugins()})


@bp.route('/api/ai/plugins/install', methods=['POST'])
def ai_plugin_install():
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        return jsonify({'ok': True, 'plugin': plugins.install(data)})
    except (AIError, ValueError) as exc:
        if isinstance(exc, AIError):
            return _error(exc)
        return jsonify({'ok': False, 'error': t('ai.pluginBadManifest', reason=str(exc))}), 400


@bp.route('/api/ai/plugins/<plugin_id>/enable', methods=['POST'])
def ai_plugin_enable(plugin_id: str):
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        plugins.set_enabled(plugin_id, bool(data.get('enabled', True)))
        return jsonify({'ok': True})
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/plugins/<plugin_id>', methods=['DELETE'])
def ai_plugin_delete(plugin_id: str):
    try:
        return jsonify({'ok': True, 'deleted': plugins.uninstall(plugin_id)})
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/memories', methods=['GET'])
def ai_memories():
    return jsonify({'ok': True, 'memories': store.list_memories()})


@bp.route('/api/ai/memories', methods=['POST'])
def ai_memory_save():
    data = _json_body()
    if data is None:
        return _bad_body()
    text = str(data.get('text') or '').strip()
    if not text:
        return _error(AIError('ai.apiNoText', kind='bad_request'))
    return jsonify({'ok': True, 'memory': store.save_memory(text[:2000])})


@bp.route('/api/ai/memories/<memory_id>', methods=['DELETE'])
def ai_memory_delete(memory_id: str):
    return jsonify({'ok': True, 'deleted': store.delete_memory(memory_id)})


@bp.route('/api/ai/conversations', methods=['GET'])
def ai_conversations():
    return jsonify({'ok': True, 'conversations': store.list_conversations()})


@bp.route('/api/ai/conversations', methods=['POST'])
def ai_conversation_create():
    data = _json_body()
    if data is None:
        return _bad_body()
    conversation = store.create_conversation(
        str(data.get('provider') or ''), str(data.get('model') or ''), str(data.get('skill') or 'auto')
    )
    return jsonify({'ok': True, 'conversation': conversation})


@bp.route('/api/ai/conversations/<conversation_id>', methods=['GET'])
def ai_conversation(conversation_id: str):
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        return _error(AIError('ai.apiNoConversation', kind='not_found', conversation=conversation_id), 404)
    return jsonify(
        {
            'ok': True,
            'conversation': conversation,
            'messages': store.list_messages(conversation_id),
            'pending_questions': store.pending_questions(conversation_id),
        }
    )


@bp.route('/api/ai/conversations/<conversation_id>', methods=['PATCH'])
def ai_conversation_update(conversation_id: str):
    data = _json_body()
    if data is None:
        return _bad_body()
    if store.get_conversation(conversation_id) is None:
        return _error(AIError('ai.apiNoConversation', kind='not_found', conversation=conversation_id), 404)
    title = str(data.get('title') or '').strip()
    if title:
        store.touch_conversation(conversation_id, title=title[:120], title_source='manual')
    if 'pinned' in data:
        store.touch_conversation(conversation_id, pinned=1 if data.get('pinned') else 0)
    return jsonify({'ok': True, 'conversation': store.get_conversation(conversation_id)})


@bp.route('/api/ai/conversations/<conversation_id>', methods=['DELETE'])
def ai_conversation_delete(conversation_id: str):
    return jsonify({'ok': True, 'deleted': store.delete_conversation(conversation_id)})


@bp.route('/api/ai/context', methods=['POST'])
def ai_context():
    data = _json_body()
    if data is None:
        return _bad_body()
    return jsonify(context.context_preview(str(data.get('query') or ''), data.get('context') or {}))


@bp.route('/api/ai/conversations/<conversation_id>/context', methods=['POST'])
def ai_context_preview(conversation_id: str):
    data = _json_body()
    if data is None:
        return _bad_body()
    if store.get_conversation(conversation_id) is None:
        return _error(AIError('ai.apiNoConversation', kind='not_found', conversation=conversation_id), 404)
    query = str(data.get('query') or '')
    return jsonify(context.context_preview(query, data.get('context') or {}))


@bp.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    data = _json_body()
    if data is None:
        return _bad_body()
    conversation_id = str(data.get('conversation_id') or '')
    account = account_context.current()
    lang = get_lang()
    try:
        generator = agent.AgentService().send(conversation_id, data)
    except AIError as exc:
        return _error(exc)
    if request.args.get('stream') == '0':
        events = []
        try:
            with account_context.use(account):
                set_lang(lang)
                for event in generator:
                    events.append(event)
        except AIError as exc:
            return _error(exc)
        return jsonify({'ok': True, 'events': events})
    return _stream(generator, account, lang)


@bp.route('/api/ai/answer', methods=['POST'])
def ai_answer():
    data = _json_body()
    if data is None:
        return _bad_body()
    conversation_id = str(data.get('conversation_id') or '')
    message_id = str(data.get('message_id') or '')
    question_id = str(data.get('question_id') or '')
    answers = data.get('answers') if isinstance(data.get('answers'), list) else []
    account = account_context.current()
    lang = get_lang()
    assistant = store.get_message(message_id)
    if assistant is None:
        return _error(AIError('ai.apiNoMessage', kind='not_found', message=message_id), 404)
    try:
        generator = agent.AgentService().answer(
            conversation_id,
            message_id,
            question_id,
            answers,
            str(data.get('api_key') or ''),
        )
    except AIError as exc:
        return _error(exc)
    if request.args.get('stream') == '0':
        events = []
        try:
            with account_context.use(account):
                set_lang(lang)
                for event in generator:
                    events.append(event)
        except AIError as exc:
            return _error(exc)
        return jsonify({'ok': True, 'events': events})
    return _stream(generator, account, lang)


@bp.route('/api/ai/stop', methods=['POST'])
def ai_stop():
    data = _json_body()
    if data is None:
        return _bad_body()
    conversation_id = str(data.get('conversation_id') or '')
    return jsonify({'ok': True, 'stopped': agent.stop(conversation_id)})


@bp.route('/api/ai/usage', methods=['GET'])
def ai_usage():
    return jsonify({'ok': True, 'usage': store.usage_summary()})


@bp.route('/api/ai/health', methods=['GET'])
def ai_health():
    return jsonify({'ok': True, 'providers': len(public_catalog()), 'models': len(list_models('deepseek'))})
