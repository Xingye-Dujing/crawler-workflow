"""The framework-backed AI surface: ``/api/ai/ws``.

This is the migration surface. The old ``/api/ai`` routes stay untouched until parity is green; this
blueprint talks only to ``AgentWorkspace`` (one per account), so a turn is durable, reattachable and
keeps running when the browser closes. The browser owns the provider key: it travels in
``X-Provider-Key`` for the one request that needs it and is never stored.
"""

from __future__ import annotations

import base64
import json

from agent_workspace import AIError as AgentError
from agent_workspace import ChatRequest
from agent_workspace import config as workspace_config
from agent_workspace.errors import WorkspaceError
from flask import Blueprint, Response, abort, jsonify, request
from runtime import account_context

from i18n import get_lang


def _sse(events):
    for item in events:
        yield f'data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n'


def _attachments(raw, workspace=None, account: str = '') -> list[dict]:
    """Host-side extraction: the browser sends bytes, the framework only ever sees text/images.

    ``[{'name': 'a.pdf', 'data': '<base64>'}]`` is extracted here with ``ai.file_text``; an entry with
    ``text`` or ``image`` is passed through unchanged; a bare file id is resolved from the stored file
    row (the panel uploads first, then names the ids). Every failure becomes a named refusal, never
    an empty document.
    """
    from ai import file_text
    from ai.errors import AIError as LegacyError

    found = []
    for item in raw or []:
        if isinstance(item, str) and item:
            if workspace is None:
                raise AgentError('attachment.unknownFile', kind='not_found', key='attachment.unknownFile', reason=item)
            row = workspace.store.get_file(item)
            if not row or row.get('account') != account:
                raise AgentError('attachment.unknownFile', kind='not_found', key='attachment.unknownFile', reason=item)
            meta = row.get('meta') or {}
            found.append(
                {
                    'name': str(row.get('name') or ''),
                    'text': str(meta.get('text') or ''),
                    'image': str(meta.get('image') or ''),
                    'file_id': str(row.get('id') or ''),
                }
            )
            continue
        if not isinstance(item, dict):
            raise AgentError('attachment.badShape', kind='bad_request', key='attachment.badShape')
        entry = {'name': str(item.get('name') or '')}
        if item.get('file_id'):
            entry['file_id'] = str(item['file_id'])
        if item.get('text'):
            entry['text'] = str(item['text'])
        elif item.get('data'):
            try:
                data = base64.b64decode(str(item['data']), validate=False)
            except Exception as exc:
                raise AgentError(
                    'attachment.badData',
                    kind='bad_request',
                    key='attachment.badData',
                    reason=str(item.get('name') or ''),
                ) from exc
            try:
                extracted = file_text.extract(str(item.get('name') or ''), data)
            except LegacyError as exc:
                raise AgentError(str(exc), kind='bad_request', key=str(exc.key or 'ai.attachExtract')) from exc
            entry['text'] = str(extracted.get('text') or '')
        if item.get('image'):
            entry['image'] = str(item['image'])
        found.append(entry)
    return found


def _error(exc: WorkspaceError):
    payload = exc.to_dict()
    payload['ok'] = False
    return jsonify(payload), 400


def _legacy_events(events):
    """The frontend's wire names, mapped once at the host edge (the engine stays canonical).

    ``text_delta``/``thinking_delta`` were ``text``/``thinking`` on the old stream; tool rows were
    ``tool_start``/``tool_result`` with ``id`` and ``ok``. Mapping here keeps the engine's event
    catalog untouched and can be deleted with the old panel.
    """
    for event in events:
        kind = event.get('type')
        if kind == 'text_delta':
            yield {**event, 'type': 'text'}
        elif kind == 'thinking_delta':
            yield {**event, 'type': 'thinking'}
        elif kind == 'tool_start':
            yield {
                **event,
                'type': 'tool_start',
                'id': event.get('call_id') or '',
                'name': event.get('tool') or '',
                'arguments': event.get('arguments') or {},
            }
        elif kind == 'tool_result':
            ok = not event.get('is_error')
            payload = {**event, 'type': 'tool_result', 'id': event.get('call_id') or '', 'ok': ok}
            if ok:
                payload['result'] = event.get('content')
            else:
                payload['error'] = event.get('content')
            yield payload
        elif kind == 'error':
            yield {**event, 'error': event.get('message') or event.get('error') or ''}
        elif kind == 'citation':
            yield {**event, 'type': 'citation', 'citation': event.get('payload') or {}}
        elif kind == 'server_tool':
            yield {**event, 'type': 'server_tool', 'block': event.get('payload') or {}}
        else:
            yield event


def _not_found(kind: str, reason: str):
    return jsonify({'ok': False, 'error': kind, 'key': kind, 'reason': reason}), 404


def _host_refusal(exc, status: int = 400):
    """The host's own AIError as the envelope the panel parses."""
    payload = exc.as_dict() if hasattr(exc, 'as_dict') else {'ok': False, 'error': str(exc)}
    payload['ok'] = False
    return jsonify(payload), status


def _machine_refusal():
    """The Python extension is one machine-level library; a non-admin account may only run stored scripts."""
    from runtime import policy

    if not policy.may_administer_machine():
        return jsonify({'ok': False, 'error': policy.machine_refusal_key(), 'key': policy.machine_refusal_key()}), 403
    return None


def _int_arg(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def create_blueprint(manager):
    blueprint = Blueprint('ai_workspace', __name__, url_prefix='/api/ai/ws')

    def account() -> str:
        current = account_context.current()
        return str(current.user_id) if current is not None else 'default'

    def body() -> dict:
        """The JSON object, or a 400 for a body that is not one; an ABSENT body reads as {}.

        The panel sends no body for a few actions, so "empty" is not malformed. A body that exists
        and is not a JSON object (``null``, a list, a string, a number) is refused before any
        handler can act on a half-read request.
        """
        payload = request.get_json(silent=True)
        if payload is None:
            if (request.get_data(cache=True) or b'').strip():
                abort(400, description='a JSON object body is required')
            return {}
        if not isinstance(payload, dict):
            abort(400, description='a JSON object body is required')
        return payload

    def context_payload(raw) -> dict:
        """The optional context object; a list or scalar is a bad parameter, never a crash."""
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            abort(400, description='context must be a JSON object')
        return dict(raw)

    def provider_key() -> str:
        return str(request.headers.get('X-Provider-Key') or body().get('api_key') or '')

    # ── chat / turns ──────────────────────────────────────────────────────────

    @blueprint.post('/chat')
    def chat():
        payload = body()
        context = context_payload(payload.get('context'))
        for key in ('attachments', 'references', 'agent_mode', 'locale'):
            if key in payload:
                context[key] = payload[key]
        req = ChatRequest(
            text=str(payload.get('text') or ''),
            conversation_id=str(payload.get('conversation_id') or ''),
            account=account(),
            host=request.host_url.rstrip('/'),
            lang=get_lang(),
            # The old panel's "auto" is not a skill id; the framework's default (general) is.
            skill='' if str(payload.get('skill') or '') in ('', 'auto') else str(payload.get('skill')),
            provider=str(payload.get('provider') or ''),
            model=str(payload.get('model') or ''),
            api_key=provider_key(),
            context_payload=context,
            thinking=payload.get('thinking'),
            web_search=payload.get('web_search'),
            max_tokens=int(payload.get('max_tokens') or 0),
            timeout=int(payload.get('timeout') or 120),
            recipe_id=str(payload.get('recipe_id') or ''),
        )
        workspace = manager.workspace(account())
        try:
            if payload.get('attachments'):
                req.context_payload['attachments'] = _attachments(
                    payload.get('attachments'), workspace=workspace, account=account()
                )
            if payload.get('stream') is False:
                events = list(_legacy_events(workspace.ask(req)))
                text = ''.join(str(item.get('text') or '') for item in events if item.get('type') == 'text')
                return jsonify({'ok': True, 'events': events, 'text': text})
            return Response(_sse(_legacy_events(workspace.ask(req))), mimetype='text/event-stream')
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.get('/turns/<turn_id>')
    def turn(turn_id):
        found = manager.workspace(account()).turn(turn_id, account())
        if not found:
            return _not_found('turn.unknown', turn_id)
        return jsonify({'ok': True, 'turn': found})

    @blueprint.get('/turns/<turn_id>/events')
    def turn_events(turn_id):
        workspace = manager.workspace(account())
        if not workspace.turn(turn_id, account()):
            return _not_found('turn.unknown', turn_id)
        try:
            after = int(request.args.get('after') or request.headers.get('Last-Event-ID') or 0)
        except ValueError:
            return jsonify({'ok': False, 'error': 'after.invalid', 'key': 'after.invalid'}), 400
        if request.args.get('stream') == '0':
            return jsonify({'ok': True, 'events': workspace.turn_events(turn_id, after)})

        def replay():
            try:
                yield from workspace.subscribe(turn_id, after)
            except WorkspaceError:
                return

        return Response(_sse(replay()), mimetype='text/event-stream')

    @blueprint.get('/turns/<turn_id>/steps')
    def turn_steps(turn_id):
        steps = manager.workspace(account()).steps(turn_id, account())
        return jsonify({'ok': True, 'steps': steps})

    @blueprint.get('/turns/<turn_id>/trace')
    def turn_trace(turn_id):
        return jsonify({'ok': True, 'trace': manager.workspace(account()).trace_tree(turn_id, account())})

    @blueprint.get('/pending')
    def pending():
        conversation_id = str(request.args.get('conversation_id') or '')
        return jsonify({'ok': True, 'pending': manager.workspace(account()).pending(conversation_id, account())})

    @blueprint.get('/inbox')
    def inbox():
        conversation_id = str(request.args.get('conversation_id') or '')
        return jsonify({'ok': True, 'inbox': manager.workspace(account()).inbox(conversation_id, account())})

    # ── catalogue / conversations / memories / artifacts / settings ───────────

    @blueprint.get('/bootstrap')
    def bootstrap():
        workspace = manager.workspace(account())
        return jsonify(workspace.bootstrap(account(), request.args.get('provider', '')))

    @blueprint.get('/providers')
    def providers():
        return jsonify({'ok': True, 'providers': manager.workspace(account()).providers(account())})

    @blueprint.get('/providers/<provider_id>/models')
    def provider_models(provider_id):
        try:
            models = manager.workspace(account()).models(provider_id, provider_key(), account())
            return jsonify({'ok': True, 'models': models, 'provider': provider_id})
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.get('/providers/<provider_id>/balance')
    def provider_balance(provider_id):
        try:
            return jsonify(manager.workspace(account()).balance(provider_id, provider_key(), account()))
        except WorkspaceError as exc:
            if exc.key == 'provider.noBalance':
                # The panel hides the block instead of showing a zero balance.
                return jsonify({'ok': True, 'supported': False, 'provider': provider_id})
            return _error(exc)

    @blueprint.post('/providers/<provider_id>/test')
    def provider_test(provider_id):
        payload = body()
        try:
            return jsonify(
                manager.workspace(account()).test_provider(
                    provider_id, str(payload.get('model') or ''), provider_key(), account()
                )
            )
        except WorkspaceError as exc:
            return jsonify({'ok': False, 'error': exc.message, 'kind': exc.kind, 'key': exc.key}), 200

    @blueprint.get('/conversations')
    def conversations():
        rows = manager.workspace(account()).store.list_conversations(
            account(),
            query=str(request.args.get('q') or ''),
            archived=str(request.args.get('archived') or '') in ('1', 'true'),
            limit=int(request.args.get('limit') or 50),
            offset=int(request.args.get('offset') or 0),
        )
        return jsonify({'ok': True, 'conversations': rows})

    @blueprint.get('/conversations/<conversation_id>')
    def conversation(conversation_id):
        workspace = manager.workspace(account())
        row = workspace.store.get_conversation(conversation_id, account())
        if not row:
            return _not_found('conversation.unknown', conversation_id)
        messages = workspace.store.list_messages(conversation_id)
        skill = next((item['meta'].get('skill') for item in messages if (item.get('meta') or {}).get('skill')), '')
        from ai import dataset_access

        return jsonify(
            {
                'ok': True,
                'conversation': {**row, 'skill': skill},
                'messages': messages,
                'dataset_grants': dataset_access.active(conversation_id),
            }
        )

    @blueprint.delete('/conversations/<conversation_id>/dataset-grants/<dataset_id>')
    def revoke_dataset_grant(conversation_id, dataset_id):
        from ai import dataset_access

        if not manager.workspace(account()).store.get_conversation(conversation_id, account()):
            return _not_found('conversation.unknown', conversation_id)
        dataset_access.revoke(conversation_id, dataset_id)
        return jsonify({'ok': True, 'dataset_grants': dataset_access.active(conversation_id)})

    @blueprint.patch('/conversations/<conversation_id>')
    def patch_conversation(conversation_id):
        payload = body()
        fields = {key: payload[key] for key in ('title', 'pinned', 'archived') if key in payload}
        row = manager.workspace(account()).store.patch_conversation(conversation_id, account(), **fields)
        return jsonify({'ok': True, 'conversation': row})

    @blueprint.post('/conversations/<conversation_id>/context')
    def conversation_context(conversation_id):
        payload = body()
        if not manager.workspace(account()).store.get_conversation(conversation_id, account()):
            return _not_found('conversation.unknown', conversation_id)
        return jsonify(
            manager.workspace(account()).context_preview(
                str(payload.get('query') or ''), account(), context_payload(payload.get('context'))
            )
        )

    @blueprint.post('/conversations')
    def create_conversation():
        payload = body()
        row = manager.workspace(account()).store.create_conversation(account(), title=str(payload.get('title') or ''))
        return jsonify({'ok': True, 'conversation': row})

    @blueprint.delete('/conversations/<conversation_id>')
    def delete_conversation(conversation_id):
        from ai import dataset_access
        from runtime import processes

        manager.workspace(account()).store.delete_conversation(conversation_id, account())
        dataset_access.revoke(conversation_id)
        stopped = processes.stop_scope(conversation_id)
        return jsonify({'ok': True, 'stopped_processes': stopped})

    @blueprint.get('/memories')
    def memories():
        return jsonify({'ok': True, 'memories': manager.workspace(account()).store.list_memories(account())})

    @blueprint.post('/memories')
    def add_memory():
        try:
            memory = manager.workspace(account()).add_memory(account(), str(body().get('text') or ''))
            return jsonify({'ok': True, 'memory': memory})
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.delete('/memories/<memory_id>')
    def delete_memory(memory_id):
        return jsonify({'ok': manager.workspace(account()).delete_memory(account(), memory_id)})

    @blueprint.get('/artifacts')
    def artifacts():
        conversation_id = str(request.args.get('conversation_id') or '')
        return jsonify({'ok': True, 'artifacts': manager.workspace(account()).artifacts(account(), conversation_id)})

    @blueprint.post('/artifacts/<artifact_id>/apply')
    def apply_artifact(artifact_id):
        try:
            return jsonify(manager.workspace(account()).apply_artifact(account(), artifact_id))
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.get('/settings')
    def settings():
        workspace = manager.workspace(account())
        return jsonify({'ok': True, 'settings': workspace.settings.all(), 'schema': workspace_config.schema()})

    @blueprint.post('/settings')
    def set_setting():
        payload = body()
        try:
            return jsonify(
                manager.workspace(account()).set_setting(str(payload.get('key') or ''), payload.get('value'))
            )
        except (KeyError, WorkspaceError) as exc:
            return jsonify({'ok': False, 'error': str(exc), 'key': 'settings.unknown'}), 400

    @blueprint.get('/usage')
    def usage():
        conversation_id = str(request.args.get('conversation_id') or '')
        return jsonify({'ok': True, 'usage': manager.workspace(account()).usage(conversation_id)})

    # ── retry / context / references / health ────────────────────────────────

    @blueprint.post('/retry')
    def retry():
        payload = body()
        try:
            events = manager.workspace(account()).retry(
                str(payload.get('conversation_id') or ''), account(), provider_key()
            )
            if payload.get('stream') is False:
                return jsonify({'ok': True, 'events': list(_legacy_events(events))})
            return Response(_sse(_legacy_events(events)), mimetype='text/event-stream')
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.get('/conversations/<conversation_id>/export')
    def export_conversation(conversation_id):
        fmt = str(request.args.get('format') or 'json')
        data = manager.workspace(account()).store.export_conversation(conversation_id, account(), fmt)
        if fmt == 'md':
            return Response(data, mimetype='text/markdown')
        return jsonify({'ok': True, 'data': data})

    @blueprint.post('/context')
    def context():
        payload = body()
        return jsonify(
            manager.workspace(account()).context_preview(
                str(payload.get('query') or ''), account(), context_payload(payload.get('context'))
            )
        )

    @blueprint.get('/references')
    def references():
        """The composer's ``@`` picker: the wire key is ``references`` (what the browser reads)."""
        return jsonify(
            {
                'ok': True,
                'references': manager.workspace(account()).reference_candidates(account(), request.args.get('q', '')),
            }
        )

    # ── recipes ──────────────────────────────────────────────────────────────

    @blueprint.get('/recipes')
    def recipes():
        """The declared recipes plus the conversation's live run, if any."""
        conversation_id = str(request.args.get('conversation_id') or '')
        workspace = manager.workspace(account())
        return jsonify(
            {
                'ok': True,
                'recipes': workspace.recipe_catalog(),
                'active': workspace.recipe_state(conversation_id, account()) if conversation_id else {},
            }
        )

    @blueprint.post('/recipes/start')
    def start_recipe():
        payload = body()
        try:
            state = manager.workspace(account()).start_recipe(
                str(payload.get('conversation_id') or ''),
                str(payload.get('recipe_id') or ''),
                account(),
            )
            return jsonify({'ok': True, 'recipe': state})
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.post('/recipes/skip')
    def skip_recipe_step():
        payload = body()
        try:
            state = manager.workspace(account()).skip_recipe_step(
                str(payload.get('conversation_id') or ''),
                str(payload.get('reason') or ''),
                account(),
            )
            return jsonify({'ok': True, 'recipe': state})
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.get('/health')
    def health():
        return jsonify({'ok': True, 'service': 'agent-workspace'})

    # ── skills / plugins / monitors / files / python ─────────────────────────

    @blueprint.route('/skills', methods=['GET', 'POST'])
    def skills():
        workspace = manager.workspace(account())
        if request.method == 'POST':
            try:
                return jsonify({'ok': True, 'skill': workspace.save_skill(account(), body())})
            except WorkspaceError as exc:
                return _error(exc)
        return jsonify({'ok': True, 'skills': workspace.skills.list(account())})

    @blueprint.delete('/skills/<skill_id>')
    def delete_skill(skill_id):
        return jsonify({'ok': manager.workspace(account()).delete_skill(account(), skill_id)})

    @blueprint.get('/skills/<skill_id>')
    def skill_detail(skill_id):
        found = manager.workspace(account()).skills.get(skill_id, account())
        if not found:
            return _not_found('skill.unknown', skill_id)
        return jsonify({'ok': True, 'skill': found.to_public()})

    @blueprint.post('/skills/<skill_id>/fork')
    def fork_skill(skill_id):
        try:
            return jsonify({'ok': True, 'skill': manager.workspace(account()).fork_skill(account(), skill_id)})
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.route('/plugins', methods=['GET', 'POST'])
    def plugins():
        workspace = manager.workspace(account())
        if request.method == 'POST':
            try:
                result = workspace.install_plugin(body(), account(), admin=bool(body().get('admin')))
                return jsonify({'ok': True, **result})
            except WorkspaceError as exc:
                return _error(exc)
        return jsonify({'ok': True, 'plugins': workspace.plugins_list()})

    @blueprint.post('/plugins/<plugin_id>/enable')
    def toggle_plugin(plugin_id):
        try:
            result = manager.workspace(account()).toggle_plugin(plugin_id, account(), bool(body().get('enabled')))
            return jsonify({'ok': True, **result})
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.delete('/plugins/<plugin_id>')
    def uninstall_plugin(plugin_id):
        try:
            return jsonify({'ok': manager.workspace(account()).uninstall_plugin(plugin_id, account())})
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.route('/monitors', methods=['GET', 'POST'])
    def monitors():
        from ai import monitors as host_monitors

        workspace = manager.workspace(account())
        if request.method == 'POST':
            payload = body()
            try:
                conditions = host_monitors.conditions(
                    payload.get('spec') or payload.get('conditions') or {}, bool(payload.get('auto_analyze'))
                )
                row = workspace.arm_monitor(account(), str(payload.get('conversation_id') or ''), conditions)
                return jsonify({'ok': True, 'monitor': host_monitors.public_monitor(row)})
            except WorkspaceError as exc:
                return _error(exc)
        return jsonify(
            {'ok': True, 'monitors': [host_monitors.public_monitor(row) for row in workspace.monitors_list(account())]}
        )

    @blueprint.delete('/monitors/<monitor_id>')
    def stop_monitor(monitor_id):
        return jsonify({'ok': manager.workspace(account()).stop_monitor(account(), monitor_id)})

    @blueprint.get('/monitors/events')
    def monitor_events():
        from ai import monitors as host_monitors

        workspace = manager.workspace(account())
        by_id = {row['id']: row for row in workspace.monitors_list(account())}
        return jsonify(
            {
                'ok': True,
                'events': [
                    host_monitors.public_delivery(row, by_id.get(row.get('monitor_id')))
                    for row in workspace.monitors.pending(account())
                ],
            }
        )

    @blueprint.post('/monitors/events/<delivery_id>/ack')
    def ack_delivery(delivery_id):
        return jsonify({'ok': manager.workspace(account()).monitors.ack(account(), delivery_id)})

    @blueprint.route('/files', methods=['GET', 'POST'])
    def files():
        workspace = manager.workspace(account())
        if request.method == 'POST':
            if request.files.get('file') is None:
                payload = body()
                return jsonify(
                    {
                        'ok': True,
                        'file': workspace.add_file(
                            account(),
                            str(payload.get('name') or ''),
                            str(payload.get('path') or ''),
                            int(payload.get('size') or 0),
                            str(payload.get('conversation_id') or ''),
                        ),
                    }
                )
            upload = request.files['file']
            data = upload.read()
            name = upload.filename or 'file'
            mime = upload.mimetype or ''
            conversation_id = str(request.form.get('conversation_id') or '')
            text = ''
            image = ''
            if mime.startswith('image/'):
                image = 'data:' + (mime or 'image/png') + ';base64,' + base64.b64encode(data).decode()
            else:
                from ai import file_text
                from ai.errors import AIError as HostError

                try:
                    extracted = file_text.extract(name, data)
                except HostError as exc:
                    return _host_refusal(exc)
                text = str(extracted.get('text') or '')
            row = workspace.add_file(
                account(), name, '', len(data), conversation_id, {'text': text, 'image': image, 'mime': mime}
            )
            return jsonify(
                {
                    'ok': True,
                    'attachment': {
                        'id': row['id'],
                        'name': name,
                        'size': len(data),
                        'kind': 'image' if image else 'text',
                    },
                }
            )
        return jsonify({'ok': True, 'files': workspace.files(account(), request.args.get('conversation_id', ''))})

    @blueprint.get('/conversations/<conversation_id>/files')
    def conversation_files(conversation_id):
        return jsonify({'ok': True, 'attachments': manager.workspace(account()).files(account(), conversation_id)})

    @blueprint.delete('/files/<file_id>')
    def delete_file(file_id):
        return jsonify({'ok': manager.workspace(account()).delete_file(account(), file_id)})

    @blueprint.get('/python/status')
    def python_status():
        from runtime.settings import get_setting

        from services import python_runtime as host_runtime

        report = host_runtime.interpreter(refresh=str(request.args.get('refresh') or '') in ('1', 'true'))
        report = {key: value for key, value in report.items() if key != 'command'}
        plan = host_runtime.install_plan()
        plan.pop('target', None)
        environment = manager.workspace(account()).host.environment().capabilities()
        return jsonify(
            {
                'ok': True,
                'enabled': bool(get_setting('ai_allow_python')),
                'allowed': bool(environment.get('code_plugins')),
                'report': report,
                'install': plan,
            }
        )

    @blueprint.route('/python/scripts', methods=['GET', 'POST'])
    def python_scripts():
        from services import python_scripts as host_scripts

        if request.method == 'POST':
            refusal = _machine_refusal()
            if refusal is not None:
                return refusal
            try:
                return jsonify({'ok': True, 'script': host_scripts.save_script(body())})
            except Exception as exc:
                return _host_refusal(exc)
        return jsonify({'ok': True, 'scripts': host_scripts.all_scripts()})

    @blueprint.get('/python/scripts/<script_id>')
    def python_script(script_id):
        from services import python_scripts as host_scripts

        row = host_scripts.get_script(script_id)
        if not row:
            return jsonify({'ok': False, 'error': 'not found', 'key': 'ai.pythonUnknown'}), 404
        return jsonify({'ok': True, 'script': row})

    @blueprint.post('/python/scripts/<script_id>/fork')
    def fork_script(script_id):
        from services import python_scripts as host_scripts

        refusal = _machine_refusal()
        if refusal is not None:
            return refusal
        payload = body()
        try:
            return jsonify(
                {
                    'ok': True,
                    'script': host_scripts.fork_script(
                        script_id, str(payload.get('id') or ''), bool(payload.get('overwrite'))
                    ),
                }
            )
        except Exception as exc:
            return _host_refusal(exc)

    @blueprint.delete('/python/scripts/<script_id>')
    def delete_script(script_id):
        from services import python_scripts as host_scripts

        refusal = _machine_refusal()
        if refusal is not None:
            return refusal
        try:
            return jsonify({'ok': True, 'deleted': host_scripts.delete_script(script_id)})
        except Exception as exc:
            return _host_refusal(exc)

    @blueprint.post('/python/run')
    def python_run():
        from services import python_runtime as host_runtime
        from services import python_scripts as host_scripts

        payload = body()
        script = host_scripts.get_script(str(payload.get('script_id') or '')) if payload.get('script_id') else None
        inline = str(payload.get('code') or '').strip()
        if inline:
            refusal = _machine_refusal()
            if refusal is not None:
                return refusal
        code = str(inline or (script or {}).get('code') or '')
        if not code:
            return jsonify({'ok': False, 'error': 'no script/code', 'key': 'ai.pythonUnknown'}), 400
        try:
            result = host_runtime.run_code(
                code,
                payload.get('rows') if isinstance(payload.get('rows'), list) else [],
                payload.get('args') if isinstance(payload.get('args'), dict) else {},
                timeout=_int_arg(payload.get('timeout'), 120, 1, 3600),
                max_rows=_int_arg(payload.get('max_rows'), 1000, 1, host_runtime.MAX_OUTPUT_ROWS),
                label=str((script or {}).get('name') or 'inline'),
            )
        except Exception as exc:
            return _host_refusal(exc)
        if not result['wrote_output']:
            return jsonify({'ok': False, 'error': 'script wrote no output', 'key': 'ai.pythonNoOutput'}), 400
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

    # ── host domain: workspace folder, previews, chart, rerun ─────────────────

    @blueprint.get('/workspace')
    def workspace_get():
        space = manager.workspace(account())
        return jsonify({'ok': True, 'workspace': space.workspace(account()).describe()})

    @blueprint.post('/workspace')
    def workspace_set():
        from runtime import policy

        if not policy.may_administer_machine():
            return jsonify({'ok': False, 'error': policy.machine_refusal_key(), 'key': 'machine.refused'}), 403
        space = manager.workspace(account()).workspace(account())
        try:
            path = str(body().get('path') or '').strip()
            state = space.clear_root() if not path else space.set_root(path)
        except WorkspaceError as exc:
            return _error(exc)
        return jsonify({'ok': True, 'workspace': state})

    @blueprint.get('/workspace/browse')
    def workspace_browse():
        from ai import workspace as folders
        from ai.errors import AIError as HostError

        space = manager.workspace(account()).workspace(account())
        try:
            listing = folders.browse(str(request.args.get('path') or ''), start_folder=space.root())
        except HostError as exc:
            return _host_refusal(exc)
        return jsonify({'ok': True, **listing})

    @blueprint.post('/workspace/pick')
    def workspace_pick():
        from ai import workspace as folders
        from ai.errors import AIError as HostError

        space = manager.workspace(account()).workspace(account())
        try:
            picked = folders.pick_folder(str(body().get('start') or ''), start_folder=space.root())
        except HostError as exc:
            return _host_refusal(exc)
        return jsonify({'ok': True, **picked})

    @blueprint.post('/artifacts/preview')
    def artifact_preview():
        from ai import previews, validators
        from ai.errors import AIError as HostError

        payload = body()
        kind = str(payload.get('kind') or '').strip()
        artifact = payload.get('payload') if isinstance(payload.get('payload'), dict) else {}
        current = payload.get('current') if isinstance(payload.get('current'), dict) else None
        try:
            validation = validators.check(kind, artifact)
            if validation is not None and not validation.ok:
                raise HostError('ai.preview.refused', kind='bad_request', detail=validation.message)
            effective = validation.payload if validation is not None and validation.payload is not None else artifact
            result = previews.preview(kind, effective, current)
            if result is None:
                raise HostError('ai.preview.unknown', kind='bad_request', kind_name=kind)
        except HostError as exc:
            return _host_refusal(exc)
        return jsonify({'ok': True, 'preview': result.to_dict()})

    @blueprint.post('/chart/preview')
    def chart_preview():
        from ai.errors import AIError as HostError
        from runtime.stores import get_dataset_store

        from services.charts.registry import spec_for

        payload = body()
        spec = payload.get('spec') if isinstance(payload.get('spec'), dict) else None
        if not spec:
            return _host_refusal(HostError('ai.chartSpecRefused', kind='bad_request', reason='spec is missing'))
        chart_type = str(spec.get('chart_type') or spec.get('chart') or spec.get('key') or '').strip()
        definition = spec_for(chart_type)
        if definition is None:
            return _host_refusal(
                HostError(
                    'ai.chartSpecRefused', kind='bad_request', reason=f'unknown chart type {chart_type or "(empty)"}'
                )
            )
        dataset_id = str(spec.get('dataset_id') or '').strip()
        if not dataset_id:
            return _host_refusal(HostError('ai.chartSpecRefused', kind='bad_request', reason='dataset_id is missing'))
        try:
            frame = get_dataset_store().get(dataset_id)
        except Exception as exc:
            return _host_refusal(HostError('ai.chartSpecRefused', kind='error', reason=str(exc)[:160]))
        if frame is None:
            return _host_refusal(HostError('ai.chartSpecRefused', kind='not_found', reason=f'no dataset {dataset_id}'))
        columns = {str(column) for column in frame.columns}

        def field(*names, limit: int = 120) -> str:
            for name in names:
                value = spec.get(name)
                if value is not None and str(value).strip():
                    return str(value).strip()[:limit]
            return ''

        render_request = {
            'dataset_id': dataset_id,
            'chart_type': chart_type,
            'x_field': field('x_field', 'x'),
            'y_field': field('y_field', 'y'),
            'value_field': field('value_field', 'value'),
            'agg': field('agg') or 'sum',
            'y2_field': field('y2_field', 'y2'),
            'agg2': field('agg2', 'agg2_field'),
            'label_field': field('label_field', 'label'),
            'center_node': field('center_node'),
            'model_field': field('model_field'),
            'agreement_label_field': field('agreement_label_field'),
            'id_field': field('id_field'),
            'title': field('title', limit=200),
            'engine': field('engine') or 'echarts',
            'tokenize': bool(spec.get('tokenize')),
        }
        stack = spec.get('stack_fields') if spec.get('stack_fields') is not None else spec.get('series')
        if isinstance(stack, str):
            stack = [stack]
        if isinstance(stack, list):
            render_request['stack_fields'] = [str(item)[:120] for item in stack[:20]]
        annotations = spec.get('annotations')
        if isinstance(annotations, list):
            render_request['annotations'] = annotations[:20]
        wordcloud_style = spec.get('wordcloud_style')
        if isinstance(wordcloud_style, dict):
            render_request['wordcloud_style'] = {
                str(key)[:60]: str(value)[:200] for key, value in list(wordcloud_style.items())[:20]
            }
        missing = [name for name in definition.reads if name not in columns]
        chosen = [
            render_request[key]
            for key in (
                'x_field',
                'y_field',
                'value_field',
                'y2_field',
                'label_field',
                'center_node',
                'model_field',
                'agreement_label_field',
                'id_field',
            )
            if render_request.get(key)
        ]
        chosen += render_request.get('stack_fields') or []
        unknown = [name for name in chosen if name not in columns]
        if missing or unknown:
            reasons = []
            if missing:
                reasons.append('missing required columns: ' + ', '.join(missing))
            if unknown:
                reasons.append('no such columns: ' + ', '.join(unknown))
            return _host_refusal(HostError('ai.chartSpecRefused', kind='bad_request', reason='; '.join(reasons)))
        if (
            definition.family != 'biblio'
            and not definition.no_x
            and not (render_request['x_field'] or render_request['y_field'])
        ):
            return _host_refusal(
                HostError('ai.chartSpecRefused', kind='bad_request', reason='x and y encoding are missing')
            )
        return jsonify(
            {'ok': True, 'chart': chart_type, 'request': render_request, 'required_columns': list(definition.reads)}
        )

    @blueprint.post('/workflow/validate')
    def workflow_validate():
        from ai import workflow_draft
        from ai.errors import AIError as HostError

        payload = body()
        candidate = payload.get('workflow') if isinstance(payload.get('workflow'), dict) else payload
        if not isinstance(candidate, dict):
            return _host_refusal(HostError('ai.workflowDraftInvalid', kind='bad_request', detail='workflow is missing'))
        return jsonify({'ok': True, 'report': workflow_draft.validate(candidate)})

    @blueprint.post('/rerun')
    def rerun():
        from ai.errors import AIError as HostError
        from runtime.stores import get_workflow_manager

        from engine.workflow_rerun import RerunRefusalError, rerun_node
        from i18n import t

        payload = body()
        conversation_id = str(payload.get('conversation_id') or '')
        if not manager.workspace(account()).store.get_conversation(conversation_id, account()):
            return _not_found('conversation.unknown', conversation_id)
        run_id = str(payload.get('run_id') or '').strip()
        workflow_name = str(payload.get('workflow_name') or '').strip()
        node_id = str(payload.get('node_id') or '').strip()
        if not run_id or not node_id:
            return _host_refusal(HostError('ai.rerunArgs', kind='bad_request'))
        if not workflow_name:
            return _host_refusal(HostError('ai.rerunUnsaved', kind='bad_request'))
        try:
            workflow = get_workflow_manager().load(workflow_name)
        except OSError:
            return _host_refusal(HostError('ai.rerunNoWorkflow', kind='not_found', name=workflow_name), 404)
        if not workflow:
            return _host_refusal(HostError('ai.rerunNoWorkflow', kind='not_found', name=workflow_name), 404)
        try:
            answer = rerun_node(workflow, node_id, run_id, workflow_name=workflow_name, lang=get_lang())
        except RerunRefusalError as exc:
            return jsonify({'ok': False, 'key': exc.key, 'error': str(exc)}), getattr(exc, 'status', 400)
        result = answer.get('body') or {}
        if not result.get('ok'):
            return jsonify({'ok': False, 'error': result.get('error') or t('ai.rerunNoRun')}), answer.get(
                'status'
            ) or 409
        return jsonify(
            {
                'ok': True,
                'run_id': run_id,
                'node_id': node_id,
                'workflow_name': workflow_name,
                'invalidated': list(result.get('invalidated') or []),
                'queued': bool(result.get('queued')),
                'message': t('ai.rerunStarted', node=node_id),
            }
        )

    @blueprint.get('/monitors/catalog')
    def monitor_catalog():
        from ai.monitors import public_catalog

        return jsonify({'ok': True, 'catalog': public_catalog()})

    @blueprint.post('/python/install')
    def python_install():
        from runtime import policy

        from services import python_runtime as host_python_runtime

        if not policy.may_administer_machine():
            return jsonify(
                {'ok': False, 'error': 'this machine is administered elsewhere', 'key': 'machine.refused'}
            ), 403
        try:
            result = host_python_runtime.install_interpreter(bool(body().get('allow_download')))
        except Exception as exc:
            return _host_refusal(exc)
        return jsonify({'ok': True, 'result': result})

    @blueprint.post('/plugins/install')
    def plugin_install():
        from runtime import policy

        data = body()
        if str(data.get('kind') or '') != 'skill-pack' and not policy.may_administer_machine():
            return jsonify({'ok': False, 'error': policy.machine_refusal_key(), 'key': 'machine.refused'}), 403
        try:
            result = manager.workspace(account()).install_plugin(data, account(), admin=bool(data.get('admin')))
        except WorkspaceError as exc:
            return _error(exc)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc), 'key': 'plugin.badManifest'}), 400
        return jsonify({'ok': True, **result})

    @blueprint.get('/traces/<run_id>')
    def traces_for_run(run_id):
        from services.llm_trace import traces_for_run as list_traces

        return jsonify({'ok': True, 'conversations': list_traces(run_id)})

    @blueprint.post('/traces/<conversation_id>/apply')
    def trace_apply(conversation_id):
        from services.coding import node_results

        data = body()
        workspace = manager.workspace(account())
        if not workspace.store.get_conversation(conversation_id, account()):
            return _not_found('conversation.unknown', conversation_id)
        messages = workspace.store.list_messages(conversation_id, limit=400)
        provenance = next(
            (
                item.get('meta') or {}
                for item in reversed(messages)
                if (item.get('meta') or {}).get('kind') == 'trace_result'
            ),
            {},
        )
        run_id = str(provenance.get('run_id') or '')
        node_id = str(provenance.get('node_id') or '')
        if not run_id or not node_id:
            return jsonify({'ok': False, 'error': 'trace has no result', 'key': 'ai.traceNoResult'}), 400
        result = data.get('result', data)
        if not isinstance(result, (dict, list)):
            return jsonify({'ok': False, 'error': 'result must be a table or object', 'key': 'ai.traceBadResult'}), 400
        try:
            saved = node_results.save(run_id, node_id, result)
        except ValueError:
            return jsonify({'ok': False, 'error': 'run_id/node_id rejected', 'key': 'ai.traceBadResult'}), 400
        return jsonify(
            {
                'ok': True,
                'saved': saved,
                'run_id': run_id,
                'workflow_name': str(provenance.get('workflow_name') or ''),
                'node_id': node_id,
            }
        )

    @blueprint.get('/codebooks')
    def codebooks_list():
        from services.coding import codebooks

        return jsonify({'ok': True, 'codebooks': codebooks.list_codebooks()})

    @blueprint.get('/codebooks/<codebook_id>')
    def codebook_get(codebook_id):
        from services.coding import codebooks

        try:
            return jsonify({'ok': True, 'codebook': codebooks.load_codebook(codebook_id)})
        except codebooks.CodebookError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 404

    @blueprint.post('/codebooks')
    def codebook_save():
        from services.coding import codebooks

        data = body()
        try:
            saved = codebooks.save_codebook(data, codebook_id=str(data.get('id') or ''))
        except codebooks.CodebookError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        return jsonify({'ok': True, 'codebook': saved})

    @blueprint.delete('/codebooks/<codebook_id>')
    def codebook_delete(codebook_id):
        from services.coding import codebooks

        try:
            return jsonify({'ok': True, 'deleted': codebooks.delete_codebook(codebook_id)})
        except codebooks.CodebookError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 404

    # ── commands ──────────────────────────────────────────────────────────────

    @blueprint.post('/answer')
    def answer():
        payload = body()
        try:
            events = manager.workspace(account()).answer(
                str(payload.get('conversation_id') or ''),
                str(payload.get('call_id') or ''),
                payload.get('answers') or {},
                account=account(),
                custom=str(payload.get('custom') or ''),
                api_key=provider_key(),
                references=list(payload.get('references') or []),
            )
            if payload.get('stream') is False:
                return jsonify({'ok': True, 'events': list(_legacy_events(events))})
            return Response(_sse(_legacy_events(events)), mimetype='text/event-stream')
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.post('/stop')
    def stop():
        from runtime import processes

        conversation_id = str(body().get('conversation_id') or '')
        stopped = manager.workspace(account()).stop(conversation_id)
        # A command the assistant started is scope-tagged with the conversation; STOP ends both.
        return jsonify({'ok': stopped, 'stopped_processes': processes.stop_scope(conversation_id)})

    @blueprint.post('/steer')
    def steer():
        payload = body()
        return jsonify(
            {
                'ok': manager.workspace(account()).steer(
                    str(payload.get('conversation_id') or ''), str(payload.get('text') or '')
                )
            }
        )

    @blueprint.post('/command')
    def command():
        payload = body()
        try:
            return jsonify(
                manager.workspace(account()).command(
                    str(payload.get('name') or ''),
                    account=account(),
                    conversation_id=str(payload.get('conversation_id') or ''),
                    args=list(payload.get('args') or []),
                )
            )
        except WorkspaceError as exc:
            return _error(exc)

    return blueprint
