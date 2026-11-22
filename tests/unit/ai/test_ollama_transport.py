"""The local Ollama transport: the daemon's models, its per-model capabilities, and its tools.

No network: ``/api/tags`` and ``/api/show`` are answered by a fake and the stream is a byte list.
The three properties pinned here are the ones that made a local turn unable to act at all: one
hardcoded model in the picker, no tool schemas on the request, and tool results replayed as if the
user had said them.
"""

import json

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fresh_caches():
    from ai.providers import ollama

    with ollama._LOCK:
        ollama._CATALOG.clear()
        ollama._INFO.clear()
    yield
    with ollama._LOCK:
        ollama._CATALOG.clear()
        ollama._INFO.clear()


class FakeResponse:
    def __init__(self, payload=None, lines=None, status_code=200):
        self._payload = payload
        self._lines = lines or []
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ''

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(self.status_code)

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1024):
        for line in self._lines:
            yield (line + '\n').encode('utf-8')

    def close(self):
        pass


def _daemon(monkeypatch, models=('qwen3.5:9b', 'qwen3.5:4b'), capabilities=('completion', 'tools', 'thinking')):
    from ai.providers import ollama

    def fake_get(url, timeout=0):
        assert url.endswith('/api/tags')
        return FakeResponse({'models': [{'name': name} for name in models]})

    def fake_post(url, **kwargs):
        if url.endswith('/api/show'):
            return FakeResponse(
                {
                    'capabilities': list(capabilities),
                    'model_info': {'qwen35.context_length': 262144},
                }
            )
        assert url.endswith('/api/chat')
        return FakeResponse(lines=kwargs.get('_lines') or [])

    monkeypatch.setattr(ollama.requests, 'get', fake_get)
    monkeypatch.setattr(ollama.requests, 'post', fake_post)
    return ollama.OllamaProvider()


def test_the_picker_lists_the_models_the_daemon_actually_has(monkeypatch):
    provider = _daemon(monkeypatch)
    assert [row['id'] for row in provider.list_models()] == ['qwen3.5:9b', 'qwen3.5:4b']
    # Once the daemon has answered, the catalog row carries that list instead of the one static name.
    assert [row['id'] for row in provider.public()['models']] == ['qwen3.5:9b', 'qwen3.5:4b']
    assert 'tools' in provider.public()['capabilities']


def test_an_unreachable_daemon_still_answers_a_catalog(monkeypatch):
    from ai.providers import ollama

    def down(*_a, **_k):
        raise ollama.requests.ConnectionError('refused')

    monkeypatch.setattr(ollama.requests, 'get', down)
    provider = ollama.OllamaProvider()
    assert provider.public()['models'] == [provider.spec.models[0].to_dict()]


def test_capabilities_are_the_models_own_answer(monkeypatch):
    provider = _daemon(monkeypatch, capabilities=('completion',))
    assert provider.supports('tools', 'qwen3.5:9b') is False
    assert provider.supports('thinking', 'qwen3.5:9b') is False


def test_the_request_carries_tools_and_the_real_context_but_never_thinking(monkeypatch):
    provider = _daemon(monkeypatch)
    payload = provider._payload(
        {
            'model': 'qwen3.5:9b',
            'system': 'sys',
            'thinking': True,
            'tools': [{'name': 'workspace_list', 'description': 'list', 'input_schema': {'type': 'object'}}],
            'messages': [
                {
                    'role': 'assistant',
                    'blocks': [
                        {'type': 'text', 'text': 'checking'},
                        {'type': 'tool_use', 'id': 'call_1', 'name': 'workspace_list', 'input': {'path': ''}},
                    ],
                },
                {'role': 'tool', 'content': '{"ok": true}', 'tool_call_id': 'call_1'},
            ],
        }
    )
    assert payload['tools'][0]['function']['name'] == 'workspace_list'
    # A local turn never thinks: the request asked for it, the transport still refuses.
    assert payload['think'] is False
    # Ollama's own default is 4096 and does not grow with the model; a harness turn would be cut.
    assert payload['options']['num_ctx'] == ollama_max()
    assert payload['messages'][1]['tool_calls'][0]['function']['name'] == 'workspace_list'
    assert payload['messages'][2]['role'] == 'tool', 'a tool result is not something the user said'


def ollama_max():
    from ai.providers.ollama import MAX_NUM_CTX

    return MAX_NUM_CTX


def test_a_streamed_tool_call_becomes_a_tool_call_event(monkeypatch):
    provider = _daemon(monkeypatch)
    frames = [
        {'message': {'content': 'let me look'}, 'done': False},
        {
            'message': {
                'tool_calls': [
                    {'function': {'name': 'workspace_read', 'arguments': {'path': 'a.txt'}}},
                ]
            },
            'done': False,
        },
        {'message': {}, 'done': True, 'done_reason': 'length', 'prompt_eval_count': 10, 'eval_count': 3},
    ]

    from ai.providers import ollama

    def post(url, **kwargs):
        if url.endswith('/api/chat'):
            return FakeResponse(lines=[json.dumps(frame) for frame in frames])
        return FakeResponse(
            {'capabilities': ['completion', 'tools', 'thinking'], 'model_info': {'qwen35.context_length': 262144}}
        )

    monkeypatch.setattr(ollama.requests, 'post', post)
    events = list(provider.stream({'model': 'qwen3.5:9b', 'messages': [], 'tools': []}))
    kinds = [event['type'] for event in events]
    assert 'tool_call' in kinds
    call = next(event for event in events if event['type'] == 'tool_call')
    assert call['name'] == 'workspace_read'
    assert call['arguments'] == {'path': 'a.txt'}
    assert events[-1] == {'type': 'done', 'stop_reason': 'max_tokens'}


def test_a_daemon_that_ignores_think_false_cannot_leak_reasoning(monkeypatch):
    """Some GGUF templates still emit ``thinking`` or put a think block in ``content``.

    The product shows no reasoning trace for a local turn, so the transport drops the field and
    strips paired tags before the text reaches the transcript.
    """
    from ai.providers import ollama

    provider = _daemon(monkeypatch)
    frames = [
        {'message': {'thinking': 'secret plan', 'content': '<think>secret plan</think>answer'}, 'done': False},
        {'message': {}, 'done': True, 'prompt_eval_count': 3, 'eval_count': 1},
    ]

    def post(url, **kwargs):
        if url.endswith('/api/chat'):
            return FakeResponse(lines=[json.dumps(frame) for frame in frames])
        return FakeResponse(
            {'capabilities': ['completion', 'tools', 'thinking'], 'model_info': {'qwen35.context_length': 262144}}
        )

    monkeypatch.setattr(ollama.requests, 'post', post)
    events = list(provider.stream({'model': 'qwen3.5:9b', 'messages': [], 'tools': []}))
    assert not any(event['type'] == 'thinking_delta' for event in events)
    assert ''.join(event.get('text', '') for event in events if event['type'] == 'text_delta') == 'answer'
