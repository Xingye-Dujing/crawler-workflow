"""DeepSeek Chat Completions transport.

This is DeepSeek's own API (``POST /chat/completions`` on ``https://api.deepseek.com``), not the
Anthropic-compatible shim: the shim is a compatibility layer whose stream frames (``message_start``,
``content_block_delta``, ``signature_delta``) we had to re-derive, and a frame we did not recognise
ended the turn with “供应商返回了无法解析的数据”. The native protocol is documented field by field
and is what the platform, the SDK examples and the row analyzers all speak.

The wire rules that matter here, all from the API reference and the thinking-mode guide:

* ``thinking``: ``{"type": "enabled" | "disabled"}``; the strength is ``reasoning_effort``
  (``low``/``high``/``max``). Thinking is ON by default when neither field is sent, so a disabled
  turn says so explicitly.
* Thinking text arrives as ``delta.reasoning_content``, the answer as ``delta.content``; token
  counts arrive in the last chunk when ``stream_options.include_usage`` is set.
* Client tool calls arrive as ``delta.tool_calls[]`` (partial ``function.arguments`` per index).
  With ``tools`` present, every earlier assistant ``reasoning_content`` must be sent back or the API
  answers 400 — ``_assistant_message`` does that.
* DeepSeek's own web tools are declared as ``{"type": "deepseek_web_search"}`` /
  ``{"type": "deepseek_read_url"}``; the model runs them server-side, reports steps through
  ``choice.server_tool_event`` and sends the complete ``server_tool_calls`` (with the encrypted
  ``signature`` that restores a fetched page next turn) in the final delta.
* Files are referenced by ``{"type": "file", "file_id": …}`` inside the user content parts.
"""

import json

import requests

from ai.errors import AIError, AIProviderError
from ai.providers.base import Provider, data_frames, event, http_error, open_stream
from ai.types import ModelSpec, ProviderSpec

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
    protocol='chat',
    base_url='https://api.deepseek.com/chat/completions',
    models=(
        ModelSpec('deepseek-flash', 'DeepSeek V4.1 Flash', 512000, DEEPSEEK_CAPABILITIES),
        ModelSpec('deepseek-v4-pro', 'DeepSeek V4 Pro', 512000, V4_PRO_CAPABILITIES),
    ),
    capabilities=DEEPSEEK_CAPABILITIES,
    models_url='https://api.deepseek.com/models',
)

#: ``reasoning_effort`` values the API accepts. ``medium``/``xhigh``/``minimal`` are mapped by the
#: service, so this side only ever sends a canonical value.
EFFORTS = {'low': 'low', 'medium': 'high', 'high': 'high', 'max': 'max', 'xhigh': 'high', 'minimal': 'low'}

#: ``finish_reason`` → the canonical reason the transcript shows.
STOP_REASONS = {
    'stop': 'end_turn',
    'length': 'max_tokens',
    'content_filter': 'refusal',
    'tool_calls': 'tool_use',
    'insufficient_system_resource': 'max_tokens',
    'aborted': 'aborted',
}


def _assistant_message(message: dict) -> dict:
    blocks = message.get('blocks') or []
    text = ''.join(str(block.get('text') or '') for block in blocks if block.get('type') == 'text')
    thinking = ''.join(str(block.get('thinking') or '') for block in blocks if block.get('type') == 'thinking')
    calls = [
        {
            'id': str(block.get('id') or ''),
            'type': 'function',
            'function': {
                'name': str(block.get('name') or ''),
                'arguments': json.dumps(block.get('input') or {}, ensure_ascii=False),
            },
        }
        for block in blocks
        if block.get('type') == 'tool_use'
    ]
    payload = {'role': 'assistant', 'content': text}
    if thinking:
        # Replayed only when the turn carries tools (the guide: a tools request must return every
        # earlier reasoning_content or the API refuses with 400); a turn without tools ignores it.
        payload['reasoning_content'] = thinking
    if calls:
        payload['tool_calls'] = calls
    steps = _server_tool_steps(blocks)
    if steps:
        payload['server_tool_calls'] = steps
    return payload


def _server_tool_steps(blocks: list) -> list:
    """Rebuild ``server_tool_calls`` from the stored blocks, one step per call, in call order.

    The read-link page body lives in the result block's ``signature``; sending it back is what puts
    the page into the next turn's context (the guide calls that out explicitly).
    """
    results = {}
    for block in blocks:
        if block.get('type') in ('web_search_tool_result', 'web_fetch_tool_result'):
            results[str(block.get('tool_use_id') or '')] = block
    steps = []
    for block in blocks:
        if block.get('type') != 'server_tool_use':
            continue
        tool_id = str(block.get('id') or '')
        result = results.get(tool_id) or {}
        call = {
            'index': 0,
            'id': tool_id,
            'type': str(block.get('name') or ''),
            'kind': str(block.get('kind') or 'search'),
            'action': block.get('input') if isinstance(block.get('input'), dict) else {},
            'status': 'failed' if result.get('type', '').endswith('_error') else 'completed',
        }
        content = result.get('content')
        if block.get('kind') == 'read_link':
            call['page'] = {
                'url': str(((content or {}).get('url') if isinstance(content, dict) else '') or ''),
                'title': str(((content or {}).get('content') or {}).get('title') or '')
                if isinstance(content, dict)
                else '',
            }
            if result.get('signature'):
                call['signature'] = str(result['signature'])
        elif isinstance(content, list):
            call['sources'] = [
                {
                    'type': 'url',
                    'url': str(row.get('url') or ''),
                    'title': str(row.get('title') or ''),
                    'snippet': str(row.get('snippet') or ''),
                    'site_name': row.get('site_name'),
                    'site_icon': row.get('site_icon'),
                    'published_at': row.get('page_age'),
                }
                for row in content
                if isinstance(row, dict) and row.get('type') == 'web_search_result'
            ]
        steps.append({'index': len(steps), 'reasoning_content': '', 'calls': [call]})
    return steps


def _user_content(message: dict, *, context_text: str = '', is_last_user: bool = False):
    text = str(message.get('content') or '')
    meta = message.get('meta') or {}
    if context_text and is_last_user:
        text = f'<cai_xi_hui_context>\n{context_text}\n</cai_xi_hui_context>\n\n{text}'
    parts = []
    for attachment in meta.get('attachments') or ():
        file_id = str(attachment.get('file_id') or '')
        if file_id:
            parts.append({'type': 'file', 'file_id': file_id})
    if not parts:
        return text
    if text:
        parts.append({'type': 'text', 'text': text})
    return parts


def to_messages(messages: list, *, context_text: str = '') -> list:
    """Turn canonical messages into Chat Completions messages (system turn excluded)."""
    out: list[dict] = []
    last_user = max(
        (index for index, message in enumerate(messages) if str(message.get('role') or '') == 'user'),
        default=-1,
    )
    for index, message in enumerate(messages):
        role = str(message.get('role') or '')
        if role == 'assistant':
            out.append(_assistant_message(message))
            continue
        if role == 'tool':
            out.append(
                {
                    'role': 'tool',
                    'tool_call_id': str(message.get('tool_call_id') or ''),
                    'content': str(message.get('content') or ''),
                }
            )
            continue
        reminder = str((message.get('meta') or {}).get('latest_reminder') or '')
        if reminder:
            # DeepSeek's own message type: it marks the newest user turn for its cache and the
            # model reads it as instructions, not as something the user said.
            out.append({'role': 'latest_reminder', 'content': reminder})
        out.append(
            {
                'role': 'user',
                'content': _user_content(message, context_text=context_text, is_last_user=index == last_user),
            }
        )
    _validate_tool_pairs(out)
    return out


def _validate_tool_pairs(messages: list) -> None:
    pending = set()
    for turn in messages:
        if turn.get('role') == 'assistant':
            calls = [str(call.get('id') or '') for call in turn.get('tool_calls') or ()]
            if calls:
                if pending:
                    raise AIError('ai.badRequest', kind='bad_request', detail='tool call without result')
                pending = set(calls)
        elif turn.get('role') == 'tool':
            pending.discard(str(turn.get('tool_call_id') or ''))
    if pending:
        raise AIError('ai.badRequest', kind='bad_request', detail='unresolved tool call')


def _function_tools(tools: list) -> list:
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


def _server_tool_blocks(call: dict) -> list:
    """One ``server_tool_calls`` entry → the call block plus its result block."""
    tool_id = str(call.get('id') or '')
    kind = str(call.get('kind') or 'search')
    action = call.get('action') if isinstance(call.get('action'), dict) else {}
    use = {
        'type': 'server_tool_use',
        'id': tool_id,
        'name': str(call.get('type') or ''),
        'input': action,
        'kind': kind,
    }
    error = call.get('error') if isinstance(call.get('error'), dict) else None
    if kind == 'read_link':
        page = call.get('page') if isinstance(call.get('page'), dict) else {}
        result = {
            'type': 'web_fetch_tool_result',
            'tool_use_id': tool_id,
            'kind': kind,
            'content': {
                'type': 'web_fetch_tool_result_error' if error else 'web_fetch_result',
                'url': str(page.get('url') or action.get('url') or ''),
                'content': {
                    'type': 'document',
                    'source': {'type': 'text', 'media_type': 'text/plain', 'data': ''},
                    'title': str(page.get('title') or ''),
                },
                'published_at': page.get('published_at'),
            },
        }
        if error:
            result['content']['error_code'] = str(error.get('code') or '')
        elif call.get('signature'):
            result['signature'] = str(call['signature'])
        return [use, result]
    sources = call.get('sources') if isinstance(call.get('sources'), list) else []
    content = [
        {
            'type': 'web_search_result',
            'url': str(row.get('url') or ''),
            'title': str(row.get('title') or ''),
            'snippet': str(row.get('snippet') or ''),
            'site_name': row.get('site_name'),
            'site_icon': row.get('site_icon'),
            'page_age': row.get('published_at'),
        }
        for row in sources
        if isinstance(row, dict)
    ]
    if error:
        content = [{'type': 'web_search_tool_result_error', 'error_code': str(error.get('code') or '')}]
    return [use, {'type': 'web_search_tool_result', 'tool_use_id': tool_id, 'content': content, 'kind': kind}]


class DeepSeekProvider(Provider):
    spec = SPEC

    def _payload(self, request: dict) -> dict:
        model = str(request.get('model') or self.spec.models[0].id)
        thinking = bool(request.get('thinking')) and self.spec.supports('thinking', model)
        payload = {
            'model': model,
            'stream': True,
            'stream_options': {'include_usage': True},
            'messages': to_messages(request.get('messages') or [], context_text=request.get('context_text') or ''),
            'max_tokens': int(request.get('max_tokens') or 8192),
            # Sent explicitly both ways: omitted, DeepSeek turns thinking ON by default.
            'thinking': {'type': 'enabled' if thinking else 'disabled'},
        }
        if thinking:
            payload['reasoning_effort'] = EFFORTS.get(str(request.get('reasoning_effort') or 'high').lower(), 'high')
        temperature = request.get('temperature')
        if temperature is not None and not thinking:
            # The guide: thinking mode ignores it, so sending it there would only mislead.
            payload['temperature'] = max(0.0, min(2.0, float(temperature)))
        system = str(request.get('system') or '')
        if system:
            payload['messages'] = [{'role': 'system', 'content': system}, *payload['messages']]
        tools = _function_tools(request.get('tools') or ())
        server = []
        if request.get('web_search') and self.spec.supports('web_search', model):
            server.append({'type': 'deepseek_web_search'})
            # Fetch is part of what the search toggle promises; sending it while the user turned
            # search off would hand the provider a capability the turn did not request.
            if self.spec.supports('read_url', model):
                server.append({'type': 'deepseek_read_url'})
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        if server:
            payload['tools'] = list(payload.get('tools') or []) + server
            # `required` and a named tool are refused in thinking mode; `auto` lets the model choose.
            payload.setdefault('tool_choice', 'auto')
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
        tool_calls: dict[int, dict] = {}
        server_calls: list = []
        annotations: list = []
        finish_reason = ''
        try:
            for _name, frame in data_frames(response, request.get('cancel_event')):
                if not isinstance(frame, dict):
                    continue
                error = frame.get('error')
                if error:
                    # A generation that fails after the first byte still answers 200, then ends with
                    # a chunk that carries `error` and no choices, and never sends [DONE].
                    detail = error.get('message') if isinstance(error, dict) else str(error)
                    raise AIProviderError('ai.server', kind='network', detail=str(detail or error)[:300])
                if frame.get('usage'):
                    yield event('usage', usage=frame['usage'])
                for choice in frame.get('choices') or ():
                    delta = choice.get('delta') or {}
                    reasoning = delta.get('reasoning_content')
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
                    # The complete server-tool history and the citations are sent once, with the
                    # chunk that carries `finish_reason`.
                    if delta.get('server_tool_calls'):
                        server_calls = list(delta['server_tool_calls'])
                    if delta.get('annotations'):
                        annotations = list(delta['annotations'])
                    if delta.get('title'):
                        yield event('title', title=str(delta['title']))
                    if choice.get('finish_reason'):
                        finish_reason = str(choice['finish_reason'])
            for block in self._replay_blocks(server_calls):
                yield event('server_tool', block=block)
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
            for citation in self._citations(annotations):
                yield event('citation', citation=citation)
            yield event('done', stop_reason=STOP_REASONS.get(finish_reason, 'end_turn'))
        finally:
            response.close()

    @staticmethod
    def _replay_blocks(server_calls: list) -> list:
        """Flatten the final ``server_tool_calls`` (steps of calls) into our block vocabulary."""
        blocks = []
        for step in server_calls or ():
            for call in (step or {}).get('calls') or ():
                blocks.extend(_server_tool_blocks(call))
        return blocks

    @staticmethod
    def _citations(annotations: list) -> list:
        out = []
        for row in annotations or ():
            if not isinstance(row, dict) or row.get('type') != 'url_citation':
                continue
            data = row.get('url_citation') or {}
            url = str(data.get('url') or '')
            if not url:
                continue
            out.append(
                {
                    'type': 'web_search_result_location',
                    'url': url,
                    'title': str(data.get('title') or url),
                    'start_index': data.get('start_index'),
                    'end_index': data.get('end_index'),
                }
            )
        return out

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
        labels = {model.id: model.label for model in self.spec.models}
        return [
            {
                'id': str(row['id']),
                'label': str(row.get('label') or row.get('name') or labels.get(str(row['id'])) or row['id']),
            }
            for row in rows or ()
            if isinstance(row, dict) and row.get('id')
        ]
