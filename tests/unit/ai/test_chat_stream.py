"""chat_once's optional on_delta mirrors each provider token without changing the buffered result."""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


def test_chat_once_streams_each_delta_but_returns_full_text(monkeypatch):
    from ai.providers import complete

    events = [
        {'type': 'text_delta', 'text': '体验'},
        {'type': 'text_delta', 'text': '卡顿'},
        {'type': 'text_delta', 'text': ' | 很卡'},
        {'type': 'usage', 'usage': {'prompt_tokens': 3, 'completion_tokens': 4}},
        {'type': 'done'},
    ]

    class FakeProvider:
        spec = SimpleNamespace(models=[])

        def stream(self, request):
            yield from events

    monkeypatch.setattr(complete, 'get_provider', lambda _id: FakeProvider())
    seen = []
    text = complete.chat_once('fake', 'm', '', 'prompt', on_delta=seen.append)
    assert text == '体验卡顿 | 很卡'
    assert seen == ['体验', '卡顿', ' | 很卡'], 'every text_delta forwarded in order'


def test_chat_once_without_listener_stays_buffered(monkeypatch):
    from ai.providers import complete

    class FakeProvider:
        spec = SimpleNamespace(models=[])

        def stream(self, request):
            yield {'type': 'text_delta', 'text': 'a'}
            yield {'type': 'text_delta', 'text': 'b'}
            yield {'type': 'done'}

    monkeypatch.setattr(complete, 'get_provider', lambda _id: FakeProvider())
    assert complete.chat_once('fake', 'm', '', 'prompt') == 'ab'
