"""The framework-backed AI surface: ``/api/ai/ws``.

This is the migration surface. The old ``/api/ai`` routes stay untouched until parity is green; this
blueprint talks only to ``AgentWorkspace`` (one per account), so a turn is durable, reattachable and
keeps running when the browser closes. The browser owns the provider key: it travels in
``X-Provider-Key`` for the one request that needs it and is never stored.
"""

from __future__ import annotations

import base64

from agent_workspace import AIError as AgentError
from agent_workspace import ChatRequest
from agent_workspace.errors import WorkspaceError
from flask import Blueprint, Response, jsonify, request
from runtime import account_context


def _sse(events):
    for item in events:
        yield f'data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n'


def _attachments(raw) -> list[dict]:
    """Host-side extraction: the browser sends bytes, the framework only ever sees text/images.

    ``[{'name': 'a.pdf', 'data': '<base64>'}]`` is extracted here with ``ai.file_text``; an entry with
    ``text`` or ``image`` is passed through unchanged, so a client that already extracted can skip
    the upload. Every failure becomes a named refusal, never an empty document.
    """
    from ai import file_text
    from ai.errors import AIError as LegacyError

    found = []
    for item in raw or []:
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


def _not_found(kind: str, reason: str):
    return jsonify({'ok': False, 'error': kind, 'key': kind, 'reason': reason}), 404


def create_blueprint(manager):
    blueprint = Blueprint('ai_workspace', __name__, url_prefix='/api/ai/ws')

    def account() -> str:
        try:
            return str(account_context.current() or 'default')
        except Exception:
            return 'default'

    def body() -> dict:
        payload = request.get_json(silent=True)
        return payload if isinstance(payload, dict) else {}

    def provider_key() -> str:
        return str(request.headers.get('X-Provider-Key') or body().get('api_key') or '')

    # ── chat / turns ──────────────────────────────────────────────────────────

    @blueprint.post('/chat')
    def chat():
        payload = body()
        context = dict(payload.get('context') or {})
        for key in ('attachments', 'references', 'agent_mode', 'locale'):
            if key in payload:
                context[key] = payload[key]
        req = ChatRequest(
            text=str(payload.get('text') or ''),
            conversation_id=str(payload.get('conversation_id') or ''),
            account=account(),
            host=request.host_url.rstrip('/'),
            skill=str(payload.get('skill') or ''),
            provider=str(payload.get('provider') or ''),
            model=str(payload.get('model') or ''),
            api_key=provider_key(),
            context_payload=context,
            thinking=payload.get('thinking'),
            web_search=payload.get('web_search'),
            max_tokens=int(payload.get('max_tokens') or 0),
            timeout=int(payload.get('timeout') or 120),
        )
        workspace = manager.workspace(account())
        try:
            if payload.get('attachments'):
                req.context_payload['attachments'] = _attachments(payload.get('attachments'))
            if payload.get('stream') is False:
                events = list(workspace.ask(req))
                text = ''.join(str(item.get('text') or '') for item in events if item.get('type') == 'text_delta')
                return jsonify({'ok': True, 'events': events, 'text': text})
            return Response(_sse(workspace.ask(req)), mimetype='text/event-stream')
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
            )
            if payload.get('stream') is False:
                return jsonify({'ok': True, 'events': list(events)})
            return Response(_sse(events), mimetype='text/event-stream')
        except WorkspaceError as exc:
            return _error(exc)

    @blueprint.post('/stop')
    def stop():
        return jsonify({'ok': manager.workspace(account()).stop(str(body().get('conversation_id') or ''))})

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
