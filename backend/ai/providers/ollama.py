"""The local Ollama daemon transport.

Ollama serves newline-delimited JSON rather than SSE. It is the one provider with no server-side
tools and no conversation title; the workspace hides those switches from its capability answer
instead of sending a field the daemon will ignore.
"""

import json

import requests

from ai.errors import AIProviderError
from ai.providers.base import Provider, event, stream_lines
from ai.types import ModelSpec, ProviderSpec

SPEC = ProviderSpec(
    id='ollama',
    label_key='ai.provider.ollama',
    notes_key='ai.providerNote.ollama',
    protocol='ollama',
    base_url='',
    models=(ModelSpec('qwen3.5:9b', 'qwen3.5:9b', 32768, frozenset()),),
    local_only=True,
    capabilities=frozenset(),
)


class OllamaProvider(Provider):
    spec = SPEC

    def _base(self, host: str = '') -> str:
        raw = (host or '').strip().rstrip('/')
        if not raw:
            raw = 'http://localhost:11434'
        if not raw.startswith(('http://', 'https://')):
            raw = 'http://' + raw
        return raw

    def _payload(self, request: dict) -> dict:
        messages = [{'role': 'system', 'content': request.get('system') or ''}] if request.get('system') else []
        for message in request.get('messages') or ():
            role = str(message.get('role') or 'user')
            if role == 'tool':
                role = 'user'
            content = str(message.get('content') or '')
            if role == 'assistant':
                content = ''.join(str(block.get('text') or '') for block in message.get('blocks') or ())
            messages.append({'role': role, 'content': content})
        return {
            'model': request.get('model') or 'qwen3.5:9b',
            'messages': messages,
            'stream': True,
            'options': {'temperature': float(request.get('temperature') or 0.2)},
        }

    def stream(self, request: dict):
        url = self._base(request.get('host')) + '/api/chat'
        try:
            response = requests.post(
                url, json=self._payload(request), stream=True, timeout=(10, int(request.get('timeout') or 180))
            )
        except requests.RequestException as exc:
            raise AIProviderError('ai.network', kind='network', detail=str(exc)[:300]) from exc
        if response.status_code != 200:
            response.close()
            raise AIProviderError('ai.http', kind='error', status=response.status_code, detail=response.text[:300])
        try:
            for line in stream_lines(response, request.get('cancel_event')):
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                except ValueError as exc:
                    raise AIProviderError('ai.badResponse', kind='bad_response', detail=line[:200]) from exc
                if frame.get('error'):
                    raise AIProviderError('ai.server', kind='network', detail=str(frame['error'])[:300])
                message = frame.get('message') or {}
                if message.get('thinking'):
                    yield event('thinking_delta', text=str(message['thinking']))
                if message.get('content'):
                    yield event('text_delta', text=str(message['content']))
                if frame.get('done'):
                    usage = {
                        'prompt_tokens': frame.get('prompt_eval_count') or 0,
                        'completion_tokens': frame.get('eval_count') or 0,
                    }
                    yield event('usage', usage=usage)
                    break
            yield event('done', stop_reason='end_turn')
        finally:
            response.close()

    def list_models(self, api_key: str = '', host: str = '') -> list:
        try:
            response = requests.get(self._base(host) + '/api/tags', timeout=8)
            response.raise_for_status()
            names = [str(model.get('name') or model.get('model') or '') for model in response.json().get('models', [])]
        except (requests.RequestException, ValueError):
            return super().list_models(api_key, host)
        return [{'id': name, 'label': name} for name in names if name and 'embed' not in name.lower()]
