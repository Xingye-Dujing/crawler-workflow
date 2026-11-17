"""AI workspace HTTP surface: providers, conversations, SSE, agent runs and the studio.

Thin by design. The provider catalog, context budget, agent loop and plugin host live under
``backend/ai`` and ``backend/extensions``; this module only turns HTTP into their calls and their
canonical events into SSE frames. An API key is read from the request body and handed to the
provider for that one call; it is never written to SQLite or to a log line.
"""

import contextlib
import json
import logging
import os
import time

from ai import agent, context, environment, files, monitors, plugins, references, skills, store, tools
from ai.errors import AIError
from ai.providers import get_provider, list_models, public_catalog
from flask import Blueprint, Response, jsonify, request, stream_with_context
from runtime import account_context
from runtime.settings import get_setting

from api.auth import accounts_mode, is_admin
from api.http import _bad_body, _json_body, _safe_int
from i18n import get_lang, set_lang, t
from services import python_runtime, python_scripts

logger = logging.getLogger('api.ai')

bp = Blueprint('ai', __name__)

plugins.register_builtin()
monitors.start()


def _error(exc: AIError, status: int = 400):
    return jsonify(exc.as_dict()), status


@bp.before_request
def _refuse_python_on_cloud():
    """One rule for the whole Python surface: a cloud host refuses it by name.

    The tools and the canvas node already refuse; without this, a shared host created the
    account's ``ai_python`` directory and echoed its absolute path for a capability it never has.
    """
    from core.config import Config

    if Config.CLOUD_MODE and request.path.startswith('/api/ai/python'):
        return _error(AIError('ai.pythonCloud', kind='capability'))
    return None


def _public_attachment(row: dict) -> dict:
    keys = ('id', 'conversation_id', 'name', 'mime', 'size', 'purpose', 'file_id', 'created_at')
    return {key: row.get(key) for key in keys if key in row}


def _sse(payload: dict) -> str:
    return 'data: ' + json.dumps(payload, ensure_ascii=False, default=str) + '\n\n'


def _workspace_state() -> dict:
    """The working-folder state the page renders; a broken pref must not take bootstrap down."""
    from ai import workspace

    try:
        return workspace.describe()
    except Exception:  # a store that cannot open is reported as "not chosen"
        return {'folder': '', 'folder_exists': False, 'cloud': bool(environment.capabilities()['cloud'])}


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
    # The key travels in a HEADER, never the query string: a documented deployment puts a
    # reverse proxy in front of this server, and an access log writes `$request` (query and
    # all) — a `?key=sk-…` line would put the user's credential in the operator's log file.
    key = str(request.headers.get('X-Provider-Key') or '')
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
            'tools': [
                {**spec.schema(), 'control': spec.control, 'permission': spec.permission}
                for spec in tools.TOOLS.values()
                if plugins.visible_tool(spec.name)
            ],
            'context_sources': sorted(skills.CONTEXT_SOURCES),
            'runtime': environment.capabilities(),
            'workspace': _workspace_state(),
            'monitors': store.list_monitors(active_only=True),
            'monitor_pending': store.pending_monitor_count(),
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
    # A provider pack, a tool pack and a code plugin register into PROCESS-WIDE tables —
    # ``PROVIDERS``/``tools.TOOLS``/``skills.BUILTIN`` — which every account's turn reads.
    # Installing one is therefore a machine-level write, guarded the same way as /api/settings
    # and /api/components; a skill pack only writes this account's own skill library.
    if str(data.get('kind') or '') != 'skill-pack' and accounts_mode() and not is_admin():
        return jsonify({'ok': False, 'error': t('accounts.adminRequired')}), 403
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


@bp.route('/api/ai/files', methods=['POST'])
def ai_file_upload():
    upload = request.files.get('file')
    if upload is None:
        return _error(AIError('ai.fileUnsupported', kind='bad_request'))
    conversation_id = str(request.form.get('conversation_id') or '')
    if not conversation_id or store.get_conversation(conversation_id) is None:
        return _error(AIError('ai.apiNoConversation', kind='not_found', conversation=conversation_id), 404)
    provider = str(request.form.get('provider') or 'deepseek')
    if provider != 'deepseek':
        return _error(AIError('ai.fileUnsupported', kind='capability'))
    data = upload.read()
    name = upload.filename or 'file'
    # Token budget: a big table becomes a dataset the assistant reads in slices, and an oversized
    # document is refused by name instead of spending the whole context window on it.
    dataset = files.tabular_dataset(name, data)
    if dataset:
        return jsonify({'ok': True, 'dataset': dataset})
    if len(data) > files.ATTACH_MAX_BYTES:
        return _error(
            AIError(
                'ai.attachTooLarge',
                kind='bad_request',
                name=name,
                mb=len(data) / (1024 * 1024),
                limit=files.ATTACH_MAX_BYTES // (1024 * 1024),
            )
        )
    try:
        row = files.upload_file(
            conversation_id,
            name,
            upload.mimetype or '',
            data,
            str(request.form.get('api_key') or ''),
            purpose=str(request.form.get('purpose') or ''),
            provider=provider,
        )
    except AIError as exc:
        return _error(exc)
    return jsonify({'ok': True, 'attachment': _public_attachment(row)})


@bp.route('/api/ai/monitors', methods=['GET'])
def ai_monitors():
    conversation_id = str(request.args.get('conversation_id') or '')
    return jsonify({'ok': True, 'monitors': store.list_monitors(conversation_id)})


@bp.route('/api/ai/monitors', methods=['POST'])
def ai_monitor_create():
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        monitor = monitors.create(
            str(data.get('conversation_id') or ''),
            data.get('spec') if isinstance(data.get('spec'), dict) else data,
            bool(data.get('auto_analyze')),
        )
    except AIError as exc:
        return _error(exc)
    return jsonify({'ok': True, 'monitor': monitor})


@bp.route('/api/ai/monitors/<monitor_id>', methods=['DELETE'])
def ai_monitor_delete(monitor_id: str):
    if store.get_monitor(monitor_id) is None:
        return _error(AIError('ai.monitorMissing', kind='not_found', monitor=monitor_id), 404)
    return jsonify({'ok': True, 'deleted': monitors.cancel(monitor_id)})


@bp.route('/api/ai/monitors/events', methods=['GET'])
def ai_monitor_events():
    conversation_id = str(request.args.get('conversation_id') or '')
    pending_only = str(request.args.get('pending') or '1') not in ('0', 'false', '')
    limit = _safe_int(request.args.get('limit'), 20, 1, 100)
    return jsonify(
        {
            'ok': True,
            'events': store.list_monitor_events(conversation_id, pending_only=pending_only, limit=limit),
        }
    )


@bp.route('/api/ai/monitors/events/<event_id>/ack', methods=['POST'])
def ai_monitor_event_ack(event_id: str):
    return jsonify({'ok': True, 'acked': store.ack_monitor_event(event_id)})


@bp.route('/api/ai/python/status', methods=['GET'])
def ai_python_status():
    runtime = environment.capabilities()
    report = python_runtime.interpreter(refresh=str(request.args.get('refresh') or '') in ('1', 'true'))
    report = {key: value for key, value in report.items() if key != 'command'}
    plan = python_runtime.install_plan()
    plan.pop('target', None)
    return jsonify(
        {
            'ok': True,
            'enabled': bool(get_setting('ai_allow_python')),
            'allowed': bool(runtime['code_plugins']),
            'report': report,
            'install': plan,
        }
    )


@bp.route('/api/ai/python/install', methods=['POST'])
def ai_python_install():
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        return jsonify({'ok': True, 'result': python_runtime.install_interpreter(bool(data.get('allow_download')))})
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/python/scripts', methods=['GET'])
def ai_python_scripts():
    return jsonify({'ok': True, 'scripts': python_scripts.all_scripts()})


@bp.route('/api/ai/python/scripts', methods=['POST'])
def ai_python_script_save():
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        return jsonify({'ok': True, 'script': python_scripts.save_script(data)})
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/python/scripts/<script_id>', methods=['GET'])
def ai_python_script(script_id: str):
    script = python_scripts.get_script(script_id)
    if script is None:
        return _error(AIError('ai.pythonUnknown', kind='not_found', script=script_id), 404)
    return jsonify({'ok': True, 'script': script})


@bp.route('/api/ai/python/scripts/<script_id>', methods=['DELETE'])
def ai_python_script_delete(script_id: str):
    try:
        return jsonify({'ok': True, 'deleted': python_scripts.delete_script(script_id)})
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/python/scripts/<script_id>/fork', methods=['POST'])
def ai_python_script_fork(script_id: str):
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        return jsonify(
            {
                'ok': True,
                'script': python_scripts.fork_script(script_id, str(data.get('id') or ''), bool(data.get('overwrite'))),
            }
        )
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/python/run', methods=['POST'])
def ai_python_run():
    data = _json_body()
    if data is None:
        return _bad_body()
    script = python_scripts.get_script(str(data.get('script_id') or '')) if data.get('script_id') else None
    code = str(data.get('code') or (script or {}).get('code') or '')
    if not code:
        return _error(AIError('ai.pythonUnknown', kind='bad_request', script=str(data.get('script_id') or '')))
    rows = data.get('rows') if isinstance(data.get('rows'), list) else []
    try:
        result = python_runtime.run_code(
            code,
            rows,
            data.get('args') if isinstance(data.get('args'), dict) else {},
            timeout=_safe_int(data.get('timeout'), 120, 1, 3600),
            max_rows=_safe_int(data.get('max_rows'), 1000, 1, python_runtime.MAX_OUTPUT_ROWS),
            label=str((script or {}).get('name') or 'inline'),
        )
    except AIError as exc:
        return _error(exc)
    if not result['wrote_output']:
        return _error(
            AIError(
                'ai.pythonNoOutput',
                kind='error',
                script=str((script or {}).get('id') or data.get('script_id') or 'inline'),
            )
        )
    return jsonify(
        {
            'ok': True,
            'rows': len(result['rows']),
            'sample': result['rows'][:20],
            'stdout': result['stdout'],
            'stderr': result['stderr'],
            'duration_ms': result['duration_ms'],
            'interpreter': result['interpreter'],
            'truncated': result['truncated'],
        }
    )


@bp.route('/api/ai/python/files', methods=['GET'])
def ai_python_files():
    return jsonify({'ok': True, 'files': python_runtime.list_files()})


@bp.route('/api/ai/python/files', methods=['POST'])
def ai_python_file_write():
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        return jsonify(
            {'ok': True, 'file': python_runtime.write_file(str(data.get('path') or ''), str(data.get('content') or ''))}
        )
    except AIError as exc:
        return _error(exc)


@bp.route('/api/ai/workspace', methods=['GET'])
def ai_workspace_get():
    from ai import workspace

    return jsonify({'ok': True, 'workspace': workspace.describe()})


@bp.route('/api/ai/workspace', methods=['POST'])
def ai_workspace_set():
    from ai import workspace

    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        state = workspace.set_folder(str(data.get('path') or ''))
    except AIError as exc:
        return _error(exc)
    return jsonify({'ok': True, 'workspace': state})


@bp.route('/api/ai/workspace/browse', methods=['GET'])
def ai_workspace_browse():
    from ai import workspace

    try:
        listing = workspace.browse(str(request.args.get('path') or ''))
    except AIError as exc:
        return _error(exc)
    return jsonify({'ok': True, **listing})


@bp.route('/api/ai/workflow/validate', methods=['POST'])
def ai_workflow_validate():
    from ai import workflow_draft

    data = _json_body()
    if data is None:
        return _bad_body()
    payload = data.get('workflow') if isinstance(data.get('workflow'), dict) else data
    if not isinstance(payload, dict):
        return _error(AIError('ai.workflowDraftInvalid', kind='bad_request', detail='workflow is missing'))
    return jsonify({'ok': True, 'report': workflow_draft.validate(payload)})


@bp.route('/api/ai/rerun', methods=['POST'])
def ai_rerun():
    """Rerun ONE failed node (and its downstream) from the monitor card.

    The user pressed a button and confirmed, so this is not a tool call: it reads the SAVED workflow
    file and goes through the same ``rerun_node`` decision as the canvas's own 重跑节点. It never
    loads the workflow onto the canvas — the page keeps whatever the user is drawing.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    conversation_id = str(data.get('conversation_id') or '')
    if store.get_conversation(conversation_id) is None:
        return _error(AIError('ai.apiNoConversation', kind='not_found', conversation=conversation_id), 404)
    run_id = str(data.get('run_id') or '').strip()
    workflow_name = str(data.get('workflow_name') or '').strip()
    node_id = str(data.get('node_id') or '').strip()
    if not run_id or not node_id:
        return _error(AIError('ai.rerunArgs', kind='bad_request'))
    if not workflow_name:
        return _error(AIError('ai.rerunUnsaved', kind='bad_request'), 400)
    from runtime.stores import get_workflow_manager

    try:
        workflow = get_workflow_manager().load(workflow_name)
    except OSError:
        return _error(AIError('ai.rerunNoWorkflow', kind='not_found', name=workflow_name), 404)
    if not workflow:
        return _error(AIError('ai.rerunNoWorkflow', kind='not_found', name=workflow_name), 404)
    from engine.workflow_rerun import RerunRefusalError, rerun_node

    try:
        answer = rerun_node(workflow, node_id, run_id, workflow_name=workflow_name, lang=get_lang())
    except RerunRefusalError as exc:
        return jsonify({'ok': False, 'key': exc.key, 'error': tools.rerun_refusal_message(exc)}), exc.status
    body = answer.get('body') or {}
    if not body.get('ok'):
        return jsonify({'ok': False, 'error': body.get('error') or t('ai.rerunNoRun')}), answer.get('status') or 409
    return jsonify(
        {
            'ok': True,
            'run_id': run_id,
            'node_id': node_id,
            'workflow_name': workflow_name,
            'invalidated': list(body.get('invalidated') or []),
            'queued': bool(body.get('queued')),
            'message': t('ai.rerunStarted', node=node_id),
        }
    )


@bp.route('/api/ai/conversations/<conversation_id>/files', methods=['GET'])
def ai_file_list(conversation_id: str):
    if store.get_conversation(conversation_id) is None:
        return _error(AIError('ai.apiNoConversation', kind='not_found', conversation=conversation_id), 404)
    return jsonify(
        {'ok': True, 'attachments': [_public_attachment(row) for row in store.list_attachments(conversation_id)]}
    )


@bp.route('/api/ai/files/<attachment_id>', methods=['DELETE'])
def ai_file_delete(attachment_id: str):
    data = _json_body()
    if data is None:
        return _bad_body()
    row = store.get_attachment(attachment_id)
    if row is None:
        return _error(AIError('ai.fileNotFound', kind='not_found', file=attachment_id), 404)
    if row.get('file_id'):
        try:
            files.delete_file(str(row['file_id']), str(data.get('api_key') or ''))
        except AIError as exc:
            return _error(exc)
    path = str(row.get('path') or '')
    if path:
        with contextlib.suppress(OSError):
            os.remove(path)
    store.delete_attachment(attachment_id)
    return jsonify({'ok': True, 'deleted': True})


@bp.route('/api/ai/search', methods=['POST'])
def ai_search():
    data = _json_body()
    if data is None:
        return _bad_body()
    if str(data.get('provider') or 'deepseek') != 'deepseek':
        return _error(AIError('ai.fileUnsupported', kind='capability'))
    try:
        result = files.search(
            str(data.get('api_key') or ''),
            str(data.get('query') or ''),
            count=int(data.get('count') or 10),
            need_content=bool(data.get('need_content')),
            ori_question=str(data.get('ori_question') or ''),
            localization=str(data.get('localization') or ''),
        )
    except AIError as exc:
        return _error(exc)
    return jsonify({'ok': True, **result})


@bp.route('/api/ai/fetch', methods=['POST'])
def ai_fetch():
    data = _json_body()
    if data is None:
        return _bad_body()
    if str(data.get('provider') or 'deepseek') != 'deepseek':
        return _error(AIError('ai.fileUnsupported', kind='capability'))
    try:
        result = files.fetch(str(data.get('api_key') or ''), str(data.get('url') or ''))
    except AIError as exc:
        return _error(exc)
    return jsonify({'ok': True, **result})


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
            'attachments': [_public_attachment(row) for row in store.list_attachments(conversation_id)],
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
    deleted = store.delete_conversation(conversation_id)
    # Its monitors and deliveries went with the row; the armed list must not keep serving them.
    monitors.invalidate()
    return jsonify({'ok': True, 'deleted': deleted})


@bp.route('/api/ai/references', methods=['GET'])
def ai_references():
    """The composer's @ picker: this account's datasets, exports, workflows and earlier uploads."""
    try:
        rows = references.options(str(request.args.get('q') or ''))
    except AIError as exc:
        return _error(exc)
    return jsonify({'ok': True, 'references': rows})


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


@bp.route('/api/ai/retry', methods=['POST'])
def ai_retry():
    data = _json_body()
    if data is None:
        return _bad_body()
    conversation_id = str(data.get('conversation_id') or '')
    account = account_context.current()
    lang = get_lang()
    try:
        generator = agent.AgentService().retry(conversation_id, str(data.get('api_key') or ''))
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
