"""OpenAI chat-completions transport, shared by OpenCode Go and OpenRouter.

Both services speak the same wire protocol; the differences are the endpoint, the identity
headers and what the model can do, and those are declared by the provider spec rather than
branched on here. This module only translates the canonical message list into ``messages`` /
``tool_calls`` and the stream back into our event names.
"""

import json

import requests

from ai.errors import AIProviderError
from ai.providers.base import Provider, check_cancel, event, http_error, open_stream
from ai.types import ProviderSpec


def _assistant_message(message: dict) -> dict:
    blocks = message.get('blocks') or []
    text = ''.join(str(block.get('text') or '') for block in blocks if block.get('type') == 'text')
    thinking = ''.join(str(block.get('thinking') or '') for block in blocks if block.get('type') == 'thinking')
    calls = [
        {
            'id': block.get('id'),
            'type': 'function',
            'function': {
                'name': block.get('name'),
                'arguments': json.dumps(block.get('input') or {}, ensure_ascii=False),
            },
        }
        for block in blocks
        if block.get('type') == 'tool_use'
    ]
    payload = {'role': 'assistant', 'content': text}
    if calls:
        payload['tool_calls'] = calls
    if thinking:
        # DeepSeek's OpenAI-compatible route accepts reasoning_content on replay; a provider
        # that does not simply ignores an unknown assistant field.
        payload['reasoning_content'] = thinking
    return payload


def to_messages(system: str, messages: list) -> list:
    out = []
    if system:
        out.append({'role': 'system', 'content': system})
    for message in messages:
        role = str(message.get('role') or '')
        if role == 'assistant':
            out.append(_assistant_message(message))
        elif role == 'tool':
            out.append(
                {
                    'role': 'tool',
                    'tool_call_id': message.get('tool_call_id') or '',
                    'content': str(message.get('content') or ''),
                }
            )
        else:
            out.append({'role': 'user', 'content': str(message.get('content') or '')})
    return out


def to_tools(tools: list) -> list:
    return [
        {
            'type': 'function',
            'function': {
                'name': tool['name'],
                'description': tool.get('description') or '',
                'parameters': tool.get('input_schema') or {'type': 'object', 'properties': {}},
            },
        }
        for tool in tools or ()
    ]


class OpenAICompatibleProvider(Provider):
    """One OpenAI-compatible endpoint; ``spec`` decides identity and capabilities."""

    spec: ProviderSpec

    def __init__(self, spec: ProviderSpec, extra_headers: dict | None = None, user_agent: str = ''):
        self.spec = spec
        self.extra_headers = extra_headers or {}
        self.user_agent = user_agent

    def _headers(self, request: dict) -> dict:
        headers = {'Content-Type': 'application/json'}
        if self.user_agent:
            headers['User-Agent'] = self.user_agent
        if request.get('api_key'):
            headers['Authorization'] = f'Bearer {request["api_key"]}'
        headers.update(self.extra_headers)
        session = str(request.get('session_id') or '')
        if session and 'x-opencode-session' not in headers:
            headers['x-opencode-session'] = session
        return headers

    def _payload(self, request: dict) -> dict:
        payload = {
            'model': request.get('model') or (self.spec.models[0].id if self.spec.models else ''),
            'messages': to_messages(request.get('system') or '', request.get('messages') or []),
            'stream': True,
            'stream_options': {'include_usage': True},
        }
        tools = to_tools(request.get('tools') or [])
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        if request.get('max_tokens'):
            payload['max_tokens'] = int(request['max_tokens'])
        if request.get('thinking') and self.spec.supports('thinking', payload['model']):
            payload['reasoning_effort'] = request.get('reasoning_effort') or 'high'
        if request.get('web_search') and self.spec.supports('web_search', payload['model']):
            # OpenRouter and Go do not offer DeepSeek's server tool; the capability check above
            # means this branch is only reachable by a provider that explicitly declares it.
            payload['web_search_options'] = {}
        return payload

    def stream(self, request: dict):
        payload = self._payload(request)
        response = open_stream(
            self.spec.base_url,
            self._headers(request),
            payload,
            int(request.get('timeout') or 180),
            request.get('cancel_event'),
        )
        tool_calls: dict[int, dict] = {}
        finish_reason = ''
        try:
            for name, frame in _frames(response, request.get('cancel_event')):
                if name == 'error':
                    error = frame.get('error') if isinstance(frame, dict) else None
                    raise AIProviderError(
                        'ai.server',
                        kind='network',
                        detail=str(error or frame)[:300],
                    )
                if isinstance(frame, dict) and frame.get('error'):
                    raise AIProviderError('ai.server', kind='network', detail=str(frame['error'])[:300])
                usage = frame.get('usage') if isinstance(frame, dict) else None
                if usage:
                    yield event('usage', usage=usage)
                for choice in (frame.get('choices') or []) if isinstance(frame, dict) else ():
                    delta = choice.get('delta') or {}
                    reasoning = delta.get('reasoning_content')
                    if isinstance(reasoning, dict):
                        reasoning = reasoning.get('content') or reasoning.get('text') or ''
                    if reasoning:
                        yield event('thinking_delta', text=str(reasoning))
                    content = delta.get('content')
                    if content:
                        yield event('text_delta', text=str(content))
                    for call in delta.get('tool_calls') or ():
                        index = int(call.get('index') or 0)
                        slot = tool_calls.setdefault(index, {'id': '', 'name': '', 'arguments': ''})
                        if call.get('id'):
                            slot['id'] = str(call['id'])
                        function = call.get('function') or {}
                        if function.get('name'):
                            slot['name'] += str(function['name'])
                        if function.get('arguments'):
                            slot['arguments'] += str(function['arguments'])
                    if choice.get('finish_reason'):
                        finish_reason = str(choice['finish_reason'])
            for slot in (tool_calls[index] for index in sorted(tool_calls)):
                if not slot['name']:
                    continue
                try:
                    arguments = json.loads(slot['arguments'] or '{}')
                except ValueError:
                    arguments = {}
                yield event(
                    'tool_call',
                    id=slot['id'] or '',
                    name=slot['name'],
                    arguments=arguments if isinstance(arguments, dict) else {},
                    raw_arguments=slot['arguments'],
                )
            yield event('done', stop_reason=finish_reason or 'end_turn')
        finally:
            response.close()

    def list_models(self, api_key: str = '', host: str = '') -> list:
        if not self.spec.models_url:
            return super().list_models(api_key, host)
        try:
            response = requests.get(
                self.spec.models_url,
                headers={'Authorization': f'Bearer {api_key}'} if api_key else {},
                timeout=20,
            )
            if response.status_code != 200:
                raise http_error(response.status_code, response.text[:200])
            payload = response.json()
        except (requests.RequestException, ValueError, AIProviderError):
            return super().list_models(api_key, host)
        rows = payload.get('data') if isinstance(payload, dict) else payload
        models = []
        for row in rows or ():
            if isinstance(row, dict) and row.get('id'):
                models.append({'id': str(row['id']), 'label': str(row.get('name') or row['id'])})
        return models or super().list_models(api_key, host)


def _frames(response, cancel_event):
    """Yield OpenAI SSE frames; ``[DONE]`` ends the stream without an event."""
    data_lines: list[str] = []
    for raw in response.iter_lines(decode_unicode=True, chunk_size=1024):
        check_cancel(cancel_event)
        if raw is None:
            continue
        line = raw if isinstance(raw, str) else raw.decode('utf-8', 'replace')
        if line == '':
            if not data_lines:
                continue
            payload = '\n'.join(data_lines)
            data_lines = []
            if payload.strip() == '[DONE]':
                return
            try:
                yield 'message', json.loads(payload)
            except ValueError as exc:
                raise AIProviderError('ai.badResponse', kind='bad_response', detail=payload[:200]) from exc
            continue
        if line.startswith(':'):
            continue
        field, _, value = line.partition(':')
        value = value[1:] if value.startswith(' ') else value
        if field == 'data':
            data_lines.append(value)
        elif field == 'event' and value == 'error':
            # Some gateways send an SSE event named error; the data still carries JSON.
            continue
    if data_lines:
        payload = '\n'.join(data_lines)
        if payload.strip() != '[DONE]':
            try:
                yield 'message', json.loads(payload)
            except ValueError as exc:
                raise AIProviderError('ai.badResponse', kind='bad_response', detail=payload[:200]) from exc
