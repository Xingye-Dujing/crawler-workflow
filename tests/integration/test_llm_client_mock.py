"""Transport-boundary tests for analyzers/llm_client.py — no browser, no daemon.

OpenRouter must never be really called from tests (user requirement), so every
HTTP path goes through monkeypatched ``requests``; the local-Ollama path is
exercised against a fake ``ollama.Client``. The contracts pinned here are the
ones the row-runner and the UI depend on: provider routing, error *kinds*
(auth/quota/model/rate_limit/…), retry behaviour, payload shapes, how fast a
Stop lands between attempts, and the
model-list endpoints' filtering — all without a byte leaving the machine.
"""

import threading
import time

import pytest

import analyzers.llm_client as lc
from analyzers.llm_client import LLMClient, LLMError, list_free_models, list_ollama_models

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=''):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


def chat_payload(content='Emotion: pos\nConfidence: 0.9'):
    return {'choices': [{'message': {'content': content}}]}


@pytest.fixture
def no_sleep(monkeypatch):
    """Retry paths sleep — remove the delay but count the calls so tests can
    assert backoff actually happened."""
    calls = []
    monkeypatch.setattr(lc.time, 'sleep', lambda s: calls.append(s))
    return calls


# ─── provider routing and input validation ──────────────────────────────


class TestRouting:
    def test_unknown_provider_falls_back_to_ollama(self):
        assert LLMClient(provider='nonsense', model='m').provider == 'ollama'

    def test_openrouter_without_key_never_reaches_http(self, monkeypatch):
        def boom(*a, **k):  # pragma: no cover - must not run
            raise AssertionError('HTTP attempted without a key')

        monkeypatch.setattr(lc.requests, 'post', boom)
        client = LLMClient(provider='openrouter', model='x', api_key='')
        with pytest.raises(LLMError) as err:
            client.chat('hi')
        assert err.value.kind == 'auth'

    def test_openrouter_without_model_never_reaches_http(self, monkeypatch):
        monkeypatch.setattr(lc.requests, 'post', lambda *a, **k: (_ for _ in ()).throw(AssertionError))
        client = LLMClient(provider='openrouter', model='', api_key='sk-test')
        with pytest.raises(LLMError) as err:
            client.chat('hi')
        assert err.value.kind == 'model'

    def test_truncate_marks_cut_text(self):
        client = LLMClient(max_chars=5)
        assert client.truncate('abcdefgh') == 'abcde…'
        assert client.truncate('abc') == 'abc'
        assert LLMClient(max_chars=0).truncate('anything at all') == 'anything at all'


# ─── OpenRouter (mocked HTTP only — never real) ─────────────────────────


class TestOpenRouter:
    def _post(self, monkeypatch, *responses):
        sent = {'calls': []}
        queue = list(responses)

        def fake_post(url, headers=None, json=None, timeout=None):
            sent['calls'].append({'url': url, 'headers': headers, 'json': json, 'timeout': timeout})
            return queue.pop(0) if len(queue) > 1 else queue[0]

        monkeypatch.setattr(lc.requests, 'post', fake_post)
        return sent

    def test_success_sends_openai_shaped_request(self, monkeypatch):
        sent = self._post(monkeypatch, FakeResponse(200, chat_payload('hello')))
        client = LLMClient(provider='openrouter', model='a/b:free', api_key='sk-1', temperature=0.2, max_tokens=64)
        assert client.chat('prompt text') == 'hello'
        call = sent['calls'][0]
        assert call['url'] == lc.OPENROUTER_CHAT_URL
        assert call['headers']['Authorization'] == 'Bearer sk-1'
        assert call['json'] == {
            'model': 'a/b:free',
            'messages': [{'role': 'user', 'content': 'prompt text'}],
            'temperature': 0.2,
            'max_tokens': 64,
        }

    def test_deterministic_errors_raise_immediately(self, monkeypatch, no_sleep):
        # auth/quota/model are *deterministic kinds*: retrying cannot help, so
        # exactly one HTTP call must happen.
        for status, kind in ((401, 'auth'), (402, 'quota'), (404, 'model')):
            sent = self._post(monkeypatch, FakeResponse(status, text='nope'))
            client = LLMClient(provider='openrouter', model='m', api_key='k')
            with pytest.raises(LLMError) as err:
                client.chat('p')
            assert err.value.kind == kind
            assert len(sent['calls']) == 1

    def test_transitive_5xx_retries_then_raises_network(self, monkeypatch, no_sleep):
        sent = self._post(monkeypatch, FakeResponse(503, text='down'))
        client = LLMClient(provider='openrouter', model='m', api_key='k')
        with pytest.raises(LLMError) as err:
            client.chat('p', max_retries=3)
        assert err.value.kind == 'network'
        assert len(sent['calls']) == 3
        assert no_sleep, 'exponential backoff must sleep between attempts'

    def test_429_honours_retry_after(self, monkeypatch, no_sleep):
        sent = self._post(monkeypatch, FakeResponse(429, headers={'Retry-After': '7'}))
        client = LLMClient(provider='openrouter', model='m', api_key='k')
        with pytest.raises(LLMError) as err:
            client.chat('p', max_retries=2)
        assert err.value.kind == 'rate_limit'
        assert len(sent['calls']) == 2
        assert 7 in no_sleep

    def test_malformed_success_is_bad_response(self, monkeypatch, no_sleep):
        self._post(monkeypatch, FakeResponse(200, {'unexpected': True}))
        client = LLMClient(provider='openrouter', model='m', api_key='k')
        with pytest.raises(LLMError) as err:
            client.chat('p')
        assert err.value.kind == 'bad_response'

    def test_empty_content_eventually_gives_up_as_bad_response(self, monkeypatch, no_sleep):
        self._post(monkeypatch, FakeResponse(200, chat_payload('   ')))
        client = LLMClient(provider='openrouter', model='m', api_key='k')
        with pytest.raises(LLMError) as err:
            client.chat('p', max_retries=2)
        assert err.value.kind == 'bad_response'

    def test_connection_error_maps_to_network(self, monkeypatch, no_sleep):
        def raise_conn(*a, **k):
            raise lc.requests.exceptions.ConnectionError('refused')

        monkeypatch.setattr(lc.requests, 'post', raise_conn)
        client = LLMClient(provider='openrouter', model='m', api_key='k')
        with pytest.raises(LLMError) as err:
            client.chat('p', max_retries=2)
        assert err.value.kind == 'network'


# ─── Ollama transport against a fake client ─────────────────────────────


class FakeOllamaClient:
    instances = []

    def __init__(self, host=None, **kw):
        self.host = host
        self.calls = []
        FakeOllamaClient.instances.append(self)

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply

    reply = {'message': {'content': 'ok'}}


@pytest.fixture
def fake_ollama(monkeypatch):
    import ollama

    FakeOllamaClient.instances = []
    monkeypatch.setattr(ollama, 'Client', FakeOllamaClient)
    yield FakeOllamaClient
    FakeOllamaClient.instances = []


class TestOllamaTransport:
    def test_chat_passes_daemon_kwargs_and_returns_content(self, fake_ollama, monkeypatch):
        monkeypatch.setattr(lc, '_CHAT_KWARGS', frozenset({'model', 'messages', 'stream', 'options'}))
        client = LLMClient(
            provider='ollama', model='qwen3.5:9b', host='http://daemon:11434', temperature=0.1, max_tokens=32
        )
        assert client.chat('ping') == 'ok'
        sent = fake_ollama.instances[0]
        assert sent.host == 'http://daemon:11434'
        kwargs = sent.calls[0]
        assert kwargs['model'] == 'qwen3.5:9b'
        assert kwargs['messages'] == [{'role': 'user', 'content': 'ping'}]
        assert kwargs['stream'] is False
        assert kwargs['options'] == {'temperature': 0.1, 'num_predict': 32}
        assert 'think' not in kwargs  # older builds reject unknown kwargs

    def test_think_disabled_when_build_supports_it(self, fake_ollama, monkeypatch):
        monkeypatch.setattr(lc, '_CHAT_KWARGS', frozenset({'model', 'messages', 'stream', 'options', 'think'}))
        LLMClient(provider='ollama', model='m').chat('p')
        assert fake_ollama.instances[0].calls[0]['think'] is False

    def test_object_style_response_is_parsed(self, fake_ollama, monkeypatch):
        monkeypatch.setattr(lc, '_CHAT_KWARGS', frozenset())
        fake_ollama.reply = type('R', (), {'message': type('M', (), {'content': 'obj style'})})()
        assert LLMClient(provider='ollama', model='m').chat('p') == 'obj style'

    def test_missing_model_tag_raises_without_retrying(self, fake_ollama, monkeypatch, no_sleep):
        import ollama

        monkeypatch.setattr(lc, '_CHAT_KWARGS', frozenset())

        class Missing(fake_ollama):
            def chat(self, **kwargs):
                self.calls.append(kwargs)
                err = ValueError('no such model "ghost", try pulling first')
                err.status_code = 404
                raise err

        monkeypatch.setattr(ollama, 'Client', Missing)
        client = LLMClient(provider='ollama', model='ghost')
        with pytest.raises(LLMError) as err:
            client.chat('p', max_retries=5)
        assert err.value.kind == 'model'
        assert len(Missing.instances) == 1  # deterministic: no retry storm

    def test_unreachable_daemon_names_the_host(self, fake_ollama, monkeypatch, no_sleep):
        import ollama

        monkeypatch.setattr(lc, '_CHAT_KWARGS', frozenset())

        class Dead(fake_ollama):
            def chat(self, **kwargs):
                self.calls.append(kwargs)
                raise ConnectionRefusedError('connection refused')

        monkeypatch.setattr(ollama, 'Client', Dead)
        client = LLMClient(provider='ollama', model='m', host='http://127.0.0.1:9')
        with pytest.raises(LLMError) as err:
            client.chat('p', max_retries=2)
        assert err.value.kind == 'network'
        assert len(Dead.instances[0].calls) == 2  # one daemon client, both attempts
        assert '127.0.0.1:9' in str(err.value)  # the actionable part of the message

    def test_ollama_requires_a_model(self, fake_ollama):
        with pytest.raises(LLMError) as err:
            LLMClient(provider='ollama', model='').chat('p')
        assert err.value.kind == 'model'


# ─── interruptible retry backoff (Stop latency) ─────────────────────────


class TestInterruptibleBackoff:
    """A stopped run must stop *now*, not after the backoff it was mid-way through.

    Both transports used to call ``time.sleep`` between attempts: with a
    300 s daemon timeout, exponential backoff and a ``Retry-After`` on top, the
    Stop button could take minutes to land. The client now naps on the run's
    cancel event instead, so these tests are timing tests — generously bounded,
    but far below the seconds the sleeps would otherwise cost.
    """

    def test_client_accepts_the_cancel_event_by_that_name(self):
        # app.py constructs the client with this exact keyword — a rename here
        # breaks every LLM run with a TypeError, not just these tests.
        ev = threading.Event()
        assert LLMClient(cancel_event=ev)._cancel is ev
        assert LLMClient()._cancel is None

    def test_sleep_uses_the_clock_when_nothing_can_cancel_it(self, monkeypatch):
        slept = []
        monkeypatch.setattr(lc.time, 'sleep', lambda s: slept.append(s))
        LLMClient()._sleep(1.25)
        assert slept == [1.25]

    def test_sleep_returns_at_once_when_the_flag_is_already_up(self):
        ev = threading.Event()
        ev.set()
        started = time.monotonic()
        LLMClient(cancel_event=ev)._sleep(3600)
        assert time.monotonic() - started < 1.0

    def test_sleep_wakes_when_the_flag_is_raised_mid_flight(self):
        ev = threading.Event()
        threading.Timer(0.05, ev.set).start()
        started = time.monotonic()
        LLMClient(cancel_event=ev)._sleep(3600)
        assert ev.is_set()
        assert time.monotonic() - started < 5.0

    def test_openrouter_backoff_does_not_outlive_a_stop(self, monkeypatch):
        def raise_conn(*a, **k):
            raise lc.requests.RequestException('refused')

        monkeypatch.setattr(lc.requests, 'post', raise_conn)
        ev = threading.Event()
        ev.set()
        client = LLMClient(provider='openrouter', model='m', api_key='k', cancel_event=ev)
        started = time.monotonic()
        with pytest.raises(LLMError) as err:
            client.chat('p', max_retries=4)  # would sleep 2 + 4 + 8 + 16 s
        assert err.value.kind == 'network'
        assert time.monotonic() - started < 2.0

    def test_one_blip_still_retries_and_answers(self, monkeypatch):
        # A raised Stop flag shortens the nap; it must not skip the retry itself.
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise lc.requests.RequestException('transient blip')
            return FakeResponse(200, chat_payload('Emotion: pos'))

        monkeypatch.setattr(lc.requests, 'post', flaky)
        ev = threading.Event()
        ev.set()
        client = LLMClient(provider='openrouter', model='m', api_key='k', cancel_event=ev)
        started = time.monotonic()
        assert client.chat('p', max_retries=2) == 'Emotion: pos'
        assert len(calls) == 2
        assert time.monotonic() - started < 2.0

    def test_ollama_backoff_does_not_outlive_a_stop(self, fake_ollama, monkeypatch):
        import ollama

        monkeypatch.setattr(lc, '_CHAT_KWARGS', frozenset())

        class Dead(fake_ollama):
            def chat(self, **kwargs):
                self.calls.append(kwargs)
                raise ConnectionRefusedError('connection refused')

        monkeypatch.setattr(ollama, 'Client', Dead)
        ev = threading.Event()
        ev.set()
        client = LLMClient(provider='ollama', model='m', host='http://127.0.0.1:9', cancel_event=ev)
        started = time.monotonic()
        with pytest.raises(LLMError) as err:
            client.chat('p', max_retries=4)  # would sleep 0.5 + 1 + 1.5 + 2 s
        assert err.value.kind == 'network'
        assert len(Dead.instances[0].calls) == 4  # retries still happen
        assert time.monotonic() - started < 2.0


class TestBaseUrl:
    def test_empty_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv('OLLAMA_HOST', raising=False)
        assert lc._ollama_base_url('') == lc.OLLAMA_DEFAULT_HOST

    def test_bare_hostport_gets_a_scheme(self):
        assert lc._ollama_base_url('192.168.1.5:11434') == 'http://192.168.1.5:11434'

    def test_trailing_slash_is_trimmed(self):
        assert lc._ollama_base_url('http://x:1/') == 'http://x:1'


# ─── model catalogues (mocked GET) ──────────────────────────────────────


class TestModelLists:
    def test_free_models_filtered_and_sorted(self, monkeypatch):
        payload = {
            'data': [
                {'id': 'z/free', 'pricing': {'prompt': '0', 'completion': '0'}},
                {'id': 'a/paid', 'pricing': {'prompt': '0.01', 'completion': '0'}},
                {'id': 'b/completion-cost', 'pricing': {'prompt': '0', 'completion': '0.002'}},
                {'id': 'm/free', 'pricing': {'prompt': '0', 'completion': '0'}},
                {'id': 'nopricing'},
            ]
        }
        monkeypatch.setattr(lc.requests, 'get', lambda url, timeout=None: FakeResponse(200, payload))
        assert list_free_models() == ['m/free', 'z/free']

    def test_ollama_tags_drop_embedding_models(self, monkeypatch):
        payload = {
            'models': [
                {'name': 'qwen3.5:9b'},
                {'model': 'all-minilm'},  # kept: the filter goes by NAME only — no capability metadata
                {'name': 'nomic-embed-text'},
                {'name': ''},
            ]
        }
        monkeypatch.setattr(lc.requests, 'get', lambda url, timeout=None: FakeResponse(200, payload))
        assert list_ollama_models(host='http://h:11434') == ['all-minilm', 'qwen3.5:9b']
