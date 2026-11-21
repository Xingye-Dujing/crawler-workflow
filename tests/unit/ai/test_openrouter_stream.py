"""OpenRouter row calls must parse OpenAI-compatible SSE when a trace listener is attached.

The trace seam always passes ``on_delta`` (default tier includes API calls). The row client's
OpenRouter branch used to ``json.loads`` each raw stream line — `data: {...}` never parsed, so every
traced OpenRouter call ended as "empty content" after two needless retries.
"""

import pytest

from analyzers.llm_client import LLMClient

pytestmark = pytest.mark.unit


class _StreamResponse:
    status_code = 200
    headers = {}
    encoding = 'utf-8'
    text = ''

    def iter_content(self, chunk_size=1024):
        yield b': keep-alive\n\n'
        yield b'data: {"choices":[{"delta":{"content":"" }}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":"\xe4\xbd\x93\xe9\xaa\x8c"}}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":"\xe5\x8d\xa1\xe9\xa1\xbf"}}]}\n\n'
        yield b'data: [DONE]\n\n'

    def json(self):
        return {}


def test_openrouter_streaming_parses_data_frames(monkeypatch):
    captured = {}

    class FakeRequests:
        class RequestException(Exception):
            pass

        @staticmethod
        def post(*args, **kwargs):
            captured.update(kwargs)
            return _StreamResponse()

    monkeypatch.setattr('analyzers.llm_client.requests', FakeRequests)
    client = LLMClient(provider='openrouter', model='m', api_key='k', timeout=5)
    seen = []
    answer = client.chat('prompt', on_delta=seen.append)
    assert answer == '体验卡顿'
    assert seen == ['体验', '卡顿']
    assert captured.get('stream') is True
