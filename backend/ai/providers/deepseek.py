"""DeepSeek Messages API transport.

The Messages API is the one DeepSeek surface that carries every block the workspace renders:
thinking, text with citations, server-side search/fetch results and client tool calls. Chat
Completions is still used by the row analyzers, where a single prompt has no use for blocks.

The serializer follows the replay rules in the API docs: a client tool call is followed by its
result before the next user turn, thinking blocks are replayed when tools are present, and a
``read_link`` result keeps its signature so the page can be restored on later turns.
"""

import json

import requests

from ai.errors import AIError, AIProviderError
from ai.providers.base import Provider, event, http_error, open_stream, sse_events
from ai.types import ModelSpec, ProviderSpec, text_block

DEEPSEEK_CAPABILITIES = frozenset(
    {
        'thinking',
        'web_search',
        'read_url',
        'files',
        'safety',
        'title',
        'latest_reminder',
        'tools',
        'ask_user',
        'vision',
        'continue',
    }
)
V4_PRO_CAPABILITIES = frozenset(capability for capability in DEEPSEEK_CAPABILITIES if capability != 'files')

SPEC = ProviderSpec(
    id='deepseek',
    label_key='ai.provider.deepseek',
    notes_key='ai.providerNote.deepseek',
    protocol='messages',
    base_url='https://api.deepseek.com/anthropic/v1/messages',
    models=(
        ModelSpec('deepseek-flash', 'DeepSeek V4.1 Flash', 512000, DEEPSEEK_CAPABILITIES),
        ModelSpec('deepseek-v4-pro', 'DeepSeek V4 Pro', 512000, V4_PRO_CAPABILITIES),
    ),
    capabilities=DEEPSEEK_CAPABILITIES,
    models_url='https://api.deepseek.com/models',
)


def _wire_content(blocks: list, *, allow_server_replay: bool = True) -> list:
    content = []
    for block in blocks or ():
        kind = block.get('type')
        if kind == 'text':
            text = str(block.get('text') or '')
            if text:
                content.append({'type': 'text', 'text': text})
        elif kind == 'thinking':
            thinking = str(block.get('thinking') or '')
            if thinking:
                payload = {'type': 'thinking', 'thinking': thinking}
                if block.get('signature'):
                    payload['signature'] = str(block['signature'])
                content.append(payload)
        elif kind == 'tool_use':
            content.append(
                {
                    'type': 'tool_use',
                    'id': str(block.get('id') or ''),
                    'name': str(block.get('name') or ''),
                    'input': block.get('input') if isinstance(block.get('input'), dict) else {},
                }
            )
        elif (
            allow_server_replay
            and kind == 'server_tool_use'
            and block.get('kind') == 'read_link'
            or allow_server_replay
            and kind == 'web_fetch_tool_result'
            and block.get('kind') == 'read_link'
        ):
            content.append(block)
    return content


def _tool_result_message(message: dict) -> dict:
    content = str(message.get('content') or '')
    return {
        'role': 'user',
        'content': [
            {
                'type': 'tool_result',
                'tool_use_id': str(message.get('tool_call_id') or ''),
                'content': [{'type': 'text', 'text': content}] if content else [],
                **({'is_error': True} if message.get('is_error') else {}),
            }
        ],
    }


def to_wire_messages(messages: list, *, context_text: str = '') -> list:
    """Turn canonical messages into Messages API turns, merging adjacent same-role turns."""
    out: list[dict] = []
    last_user_index = max(
        (index for index, message in enumerate(messages) if str(message.get('role') or '') == 'user'),
        default=-1,
    )
    for index, message in enumerate(messages):
        role = str(message.get('role') or '')
        if role == 'assistant':
            content = _wire_content(message.get('blocks') or [])
            if content:
                out.append({'role': 'assistant', 'content': content})
            continue
        if role == 'tool':
            out.append(_tool_result_message(message))
            continue
        reminder = str((message.get('meta') or {}).get('latest_reminder') or '')
        if reminder:
            out.append({'role': 'latest_reminder', 'content': reminder})
        content = str(message.get('content') or '')
        if context_text and index == last_user_index:
            content = f'<cai_xi_hui_context>\n{context_text}\n</cai_xi_hui_context>\n\n{content}'
        blocks = []
        for attachment in (message.get('meta') or {}).get('attachments') or ():
            file_id = str(attachment.get('file_id') or '')
            if not file_id:
                continue
            block_type = 'image' if attachment.get('kind') == 'image' else 'document'
            blocks.append({'type': block_type, 'source': {'type': 'file', 'file_id': file_id}})
        if content:
            blocks.append(text_block(content))
        out.append({'role': 'user', 'content': blocks})
    # Anthropic accepts adjacent same-role turns, but the API's replay checks and the cache
    # behave better with alternation. Merge text/tool-result user turns; never merge an
    # assistant turn into a user turn.
    merged: list[dict] = []
    for turn in out:
        previous = merged[-1] if merged else None
        if previous is not None and previous.get('role') == turn['role'] == 'user':
            merged[-1]['content'] = list(merged[-1].get('content') or []) + list(turn.get('content') or [])
        else:
            merged.append(turn)
    _validate_tool_pairs(merged)
    return merged


def _validate_tool_pairs(messages: list) -> None:
    pending = set()
    for turn in messages:
        if turn.get('role') == 'assistant':
            calls = [block.get('id') for block in turn.get('content') or [] if block.get('type') == 'tool_use']
            if calls:
                if pending:
                    raise AIError('ai.badRequest', kind='bad_request', detail='tool call without result')
                pending = set(calls)
        elif turn.get('role') == 'user':
            results = [
                block.get('tool_use_id') for block in turn.get('content') or [] if block.get('type') == 'tool_result'
            ]
            for result in results:
                pending.discard(result)
    if pending:
        raise AIError('ai.badRequest', kind='bad_request', detail='unresolved tool call')


class DeepSeekProvider(Provider):
    spec = SPEC

    def _payload(self, request: dict) -> dict:
        model = str(request.get('model') or 'deepseek-flash')
        thinking = bool(request.get('thinking')) and self.spec.supports('thinking', model)
        payload = {
            'model': model,
            'stream': True,
            'messages': to_wire_messages(request.get('messages') or [], context_text=request.get('context_text') or ''),
            'max_tokens': int(request.get('max_tokens') or 8192),
            'thinking': {'type': 'enabled' if thinking else 'disabled'},
        }
        system = str(request.get('system') or '')
        if system:
            payload['system'] = system
        if thinking:
            payload['output_config'] = {'effort': str(request.get('reasoning_effort') or 'high')}
        tools = []
        for tool in request.get('tools') or ():
            tools.append(
                {
                    'name': tool['name'],
                    'description': tool.get('description') or '',
                    'input_schema': tool.get('input_schema') or {'type': 'object', 'properties': {}},
                }
            )
        server_tools = []
        if request.get('web_search') and self.spec.supports('web_search', model):
            server_tools.append({'type': 'deepseek_web_search', 'name': 'deepseek_web_search'})
        if request.get('web_search') and self.spec.supports('read_url', model):
            # Fetch is part of what the search toggle promises; sending it while the user turned
            # search off would hand the provider a capability the turn did not request.
            server_tools.append({'type': 'deepseek_read_url', 'name': 'deepseek_read_url'})
        if server_tools:
            tools.extend(server_tools)
        if tools:
            payload['tools'] = tools
        if request.get('safety') and self.spec.supports('safety', model):
            payload['safety_check'] = {'level': str(request.get('safety') or 'high')}
        if request.get('title') and self.spec.supports('title', model):
            payload['title'] = {'enabled': True}
        user_id = str(request.get('user_id') or '')
        if user_id:
            payload['user_id'] = user_id
        return payload

    def _headers(self, request: dict) -> dict:
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {request.get("api_key") or ""}',
            'User-Agent': 'CaiXiHui-AI/1.0',
            'anthropic-beta': 'files-api-2025-04-14',
        }

    def stream(self, request: dict):
        payload = self._payload(request)
        response = open_stream(
            self.spec.base_url,
            self._headers(request),
            payload,
            int(request.get('timeout') or 180),
            request.get('cancel_event'),
        )
        tool_slots: dict[int, dict] = {}
        stop_reason = ''
        try:
            for name, frame in sse_events(response, request.get('cancel_event')):
                if name == 'error' or frame.get('type') == 'error':
                    detail = frame.get('error') if isinstance(frame, dict) else frame
                    raise AIProviderError('ai.server', kind='network', detail=str(detail)[:300])
                kind = str(frame.get('type') or '')
                if kind == 'ping':
                    continue
                if kind == 'message_start':
                    continue
                if kind == 'content_block_start':
                    index = int(frame.get('index') or 0)
                    block = frame.get('content_block') or {}
                    block_type = block.get('type')
                    if block_type == 'thinking':
                        if block.get('thinking'):
                            yield event('thinking_delta', text=str(block['thinking']))
                    elif block_type == 'text':
                        if block.get('text'):
                            yield event('text_delta', text=str(block['text']))
                    elif block_type in ('server_tool_use', 'web_search_tool_result', 'web_fetch_tool_result'):
                        yield event('server_tool', block=block)
                    elif block_type == 'tool_use':
                        tool_slots[index] = {
                            'id': str(block.get('id') or ''),
                            'name': str(block.get('name') or ''),
                            'input': block.get('input') if isinstance(block.get('input'), dict) else {},
                            'arguments': '',
                        }
                    continue
                if kind == 'content_block_delta':
                    index = int(frame.get('index') or 0)
                    delta = frame.get('delta') or {}
                    delta_type = delta.get('type')
                    if delta_type == 'thinking_delta':
                        yield event('thinking_delta', text=str(delta.get('thinking') or ''))
                    elif delta_type == 'text_delta':
                        yield event('text_delta', text=str(delta.get('text') or ''))
                    elif delta_type == 'signature_delta':
                        yield event('thinking_signature', signature=str(delta.get('signature') or ''))
                    elif delta_type == 'citations_delta':
                        yield event('citation', citation=delta.get('citation') or {})
                    elif delta_type == 'input_json_delta' and index in tool_slots:
                        tool_slots[index]['arguments'] += str(delta.get('partial_json') or '')
                    continue
                if kind == 'content_block_stop':
                    index = int(frame.get('index') or 0)
                    slot = tool_slots.pop(index, None)
                    if slot is not None:
                        arguments = slot.get('input') or {}
                        if slot.get('arguments'):
                            try:
                                parsed = json.loads(slot['arguments'])
                            except ValueError:
                                parsed = {}
                            if isinstance(parsed, dict):
                                arguments = parsed
                        yield event(
                            'tool_call',
                            id=slot['id'],
                            name=slot['name'],
                            arguments=arguments,
                            raw_arguments=slot.get('arguments') or '',
                        )
                    continue
                if kind == 'message_delta':
                    delta = frame.get('delta') or {}
                    stop_reason = str(delta.get('stop_reason') or '')
                    if frame.get('usage'):
                        yield event('usage', usage=frame['usage'])
                    if delta.get('title'):
                        yield event('title', title=str(delta['title']))
                    if stop_reason == 'refusal':
                        yield event('refusal', reason=str(delta.get('stop_details') or ''))
                    continue
                if kind == 'message_stop':
                    break
            yield event('done', stop_reason=stop_reason or 'end_turn')
        finally:
            response.close()

    def list_models(self, api_key: str = '', host: str = '') -> list:
        if not api_key:
            return super().list_models(api_key, host)
        # A key was supplied, so the provider's answer IS the measurement: a 401, a quota refusal
        # or a network fault used to come back as the static catalogue, which made the panel's
        # “刷新模型” unable to distinguish a working key from a dead one.
        try:
            response = requests.get(
                self.spec.models_url,
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise AIProviderError('ai.network', kind='network', detail=str(exc)[:300]) from exc
        if response.status_code != 200:
            raise http_error(response.status_code, response.text[:200])
        try:
            payload = response.json()
        except ValueError as exc:
            raise AIProviderError('ai.badResponse', kind='bad_response', detail=response.text[:200]) from exc
        rows = payload.get('data') if isinstance(payload, dict) else payload
        return [
            {'id': str(row['id']), 'label': str(row.get('label') or row['id'])}
            for row in rows or ()
            if isinstance(row, dict) and row.get('id')
        ]
