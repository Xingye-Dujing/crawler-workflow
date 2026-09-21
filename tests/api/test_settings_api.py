"""Tests for the runtime settings panel and the AI endpoints behind it.

``settings_store`` is the machine-local half of the app: the values that used
to be hardcoded in ``config.py`` and now get edited from the browser. The
contract worth pinning is that a bad edit degrades *loudly and locally* — the
handler answers 200 with a warning and falls back to the default, because a
rejected save would leave the panel showing something the server is not using.

The three ``/api/llm/*`` endpoints are the other half of the same panel. They
are the only routes in this file that would talk to the network, so every one
of them is exercised with the HTTP boundary in ``analyzers.llm_client``
stubbed; nothing here can reach Ollama or OpenRouter.
"""
import json

import pytest

import settings_store
from config import Config

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    """Own settings.json per test.

    The session harness points the store at a shared tmp file; a settings test
    that wrote there would decide what another test's ``GET`` sees.
    """
    path = tmp_path / 'settings.json'
    monkeypatch.setattr(settings_store, '_PATH', str(path))
    monkeypatch.setattr(settings_store, '_values', None)
    yield path
    settings_store._values = None


class _FakeResponse:
    """The handful of ``requests.Response`` members the LLM client reads."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f'HTTP {self.status_code}')


def _patch_http(monkeypatch, llm_client, verb, response=None, error=None, calls=None):
    """Replace the transport so a route can be driven without a daemon."""

    def fake(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(llm_client.requests, verb, fake)


class TestSettingsRead:
    def test_get_returns_every_key_the_defaults_advertise(self, client):
        body = client.get('/api/settings').get_json()
        assert body['ok'] is True
        assert set(body['settings']) == set(settings_store.DEFAULTS)
        assert body['settings']['window_size'] == '1920x1080'
        assert body['settings']['page_load_timeout'] == 40
        assert body['settings']['ollama_host'] == Config.OLLAMA_HOST

    def test_get_survives_a_corrupt_settings_file(self, client, settings_file):
        settings_file.write_text('{not json', encoding='utf-8')
        settings_store._values = None
        body = client.get('/api/settings').get_json()
        assert body['settings'] == settings_store.DEFAULTS


class TestSettingsWrite:
    def test_valid_patch_is_persisted_and_reported(self, client, settings_file):
        patch = {'window_size': '1280x720', 'page_load_timeout': '20', 'ollama_host': 'http://ollama.lan:11434'}
        response = client.post('/api/settings', json={'settings': patch})
        body = response.get_json()
        assert response.status_code == 200
        assert body['warnings'] == []
        assert body['settings']['window_size'] == '1280x720'
        # Numbers are stored as numbers, so a crawler can use them directly.
        assert body['settings']['page_load_timeout'] == 20

        on_disk = json.loads(settings_file.read_text(encoding='utf-8'))
        assert on_disk['window_size'] == '1280x720'
        # Readers pull through the cache, which proves the save was applied and
        # not merely written.
        assert settings_store.get_setting('ollama_host') == 'http://ollama.lan:11434'

    def test_a_bare_object_is_accepted_as_the_patch(self, client):
        body = client.post('/api/settings', json={'element_timeout': 30}).get_json()
        assert body['warnings'] == []
        assert body['settings']['element_timeout'] == 30

    def test_unknown_keys_are_ignored_rather_than_stored(self, client):
        body = client.post('/api/settings', json={'secret': 'x', 'window_size': '900x900'}).get_json()
        assert 'secret' not in body['settings']
        assert body['settings']['window_size'] == '900x900'

    @pytest.mark.parametrize(
        ('patch', 'key', 'expected', 'warning'),
        [
            ({'window_size': 'big'}, 'window_size', '1920x1080', 'WIDTHxHEIGHT'),
            ({'window_size': '1920'}, 'window_size', '1920x1080', 'WIDTHxHEIGHT'),
            ({'window_size': '1920x'}, 'window_size', '1920x1080', 'WIDTHxHEIGHT'),
            ({'ollama_host': 'localhost:11434'}, 'ollama_host', Config.OLLAMA_HOST, 'must start with http'),
            ({'ollama_host': 'ftp://box:11434'}, 'ollama_host', Config.OLLAMA_HOST, 'must start with http'),
            ({'driver_path': ''}, 'driver_path', Config.DRIVER_PATH, 'Driver path was empty'),
        ],
    )
    def test_bad_input_falls_back_to_the_default_with_a_warning(self, client, patch, key, expected, warning):
        body = client.post('/api/settings', json=patch).get_json()
        assert body['ok'] is True
        assert body['settings'][key] == expected
        assert len(body['warnings']) == 1
        assert warning in body['warnings'][0]

    # Documented behaviour of save_settings(): fall back and warn. Used to be
    # unreachable for the two timeouts because the warning was rendered with
    # ``t('set.badNumber', key=key, ...)`` — i18n.t() owns a parameter called
    # ``key``, so the collision raised TypeError and 500-ed the panel. The
    # templates now take ``setting`` and the warning actually arrives.
    @pytest.mark.parametrize(
        ('patch', 'key', 'expected', 'warning'),
        [
            ({'page_load_timeout': 'abc'}, 'page_load_timeout', 40, 'is not a number'),
            ({'page_load_timeout': None}, 'page_load_timeout', 40, 'is not a number'),
            ({'page_load_timeout': '1000'}, 'page_load_timeout', 40, 'is outside 5-300'),
            ({'element_timeout': '1'}, 'element_timeout', 15, 'is outside 3-600'),
            ({'element_timeout': '9999'}, 'element_timeout', 15, 'is outside 3-600'),
        ],
    )
    def test_unusable_timeout_warns_and_restores_the_default(self, client, patch, key, expected, warning):
        response = client.post('/api/settings', json=patch)
        assert response.status_code == 200
        body = response.get_json()
        assert body['settings'][key] == expected
        assert warning in body['warnings'][0]

    def test_a_valid_timeout_is_stored_as_a_number(self, client):
        body = client.post('/api/settings', json={'element_timeout': '7'}).get_json()
        assert body['warnings'] == []
        assert body['settings']['element_timeout'] == 7

    def test_trailing_slash_is_stripped_from_a_good_host(self, client):
        body = client.post('/api/settings', json={'ollama_host': 'http://box:11434/'}).get_json()
        assert body['warnings'] == []
        assert body['settings']['ollama_host'] == 'http://box:11434'

    def test_missing_driver_files_warn_without_losing_the_path(self, client, tmp_path):
        real = tmp_path / 'chromedriver.exe'
        real.write_text('placeholder', encoding='utf-8')
        good = client.post('/api/settings', json={'driver_path': str(real)}).get_json()
        assert good['warnings'] == []
        assert good['settings']['driver_path'] == str(real)

        ghost = client.post('/api/settings', json={'driver_path': str(tmp_path / 'nope.exe')}).get_json()
        assert ghost['settings']['driver_path'] == str(tmp_path / 'nope.exe')
        assert 'does not exist' in ghost['warnings'][0]

        empty = client.post('/api/settings', json={'driver_path': '   '}).get_json()
        assert empty['settings']['driver_path'] == Config.DRIVER_PATH
        assert 'restored the default' in empty['warnings'][0]


class TestLlmPanelEndpoints:
    """Every LLM route runs against a stubbed transport in ``llm_client``."""

    @pytest.fixture
    def llm_client(self):
        from analyzers import llm_client

        return llm_client

    def test_openrouter_catalog_is_filtered_to_free_models(self, client, llm_client, monkeypatch):
        payload = {
            'data': [
                {'id': 'z:free', 'pricing': {'prompt': '0', 'completion': '0'}},
                {'id': 'a:free', 'pricing': {'prompt': '0', 'completion': '0'}},
                {'id': 'paid/model', 'pricing': {'prompt': '0.01', 'completion': '0.02'}},
            ]
        }
        _patch_http(monkeypatch, llm_client, 'get', response=_FakeResponse(payload))
        body = client.get('/api/llm/models').get_json()
        assert body == {'ok': True, 'models': ['a:free', 'z:free']}

    def test_openrouter_failure_answers_502_with_an_empty_list(self, client, llm_client, monkeypatch):
        error = llm_client.requests.RequestException('offline')
        _patch_http(monkeypatch, llm_client, 'get', error=error)
        response = client.get('/api/llm/models')
        assert response.status_code == 502
        body = response.get_json()
        assert body['ok'] is False
        assert body['models'] == []
        assert 'Could not fetch the OpenRouter model list' in body['error']

    def test_ollama_tags_come_from_the_configured_address(self, client, llm_client, monkeypatch):
        monkeypatch.setattr(settings_store, '_values', {'ollama_host': 'http://ollama.test:11434'})
        payload = {'models': [{'name': 'qwen3.5:9b'}, {'name': 'nomic-embed-text'}, {'model': 'fallback:tag'}]}
        calls = []
        _patch_http(monkeypatch, llm_client, 'get', response=_FakeResponse(payload), calls=calls)
        body = client.get('/api/llm/ollama/models').get_json()
        assert calls[0][0] == 'http://ollama.test:11434/api/tags'
        # Embedding-only models cannot answer a chat request, so they are gone.
        assert body['models'] == ['fallback:tag', 'qwen3.5:9b']
        assert body['host'] == 'http://ollama.test:11434'

    def test_unreachable_daemon_reports_the_address_it_tried(self, client, llm_client, monkeypatch):
        monkeypatch.setattr(settings_store, '_values', {'ollama_host': 'http://dead.host:11434'})
        error = llm_client.requests.ConnectionError('refused')
        _patch_http(monkeypatch, llm_client, 'get', error=error)
        response = client.get('/api/llm/ollama/models')
        assert response.status_code == 502
        body = response.get_json()
        assert body['models'] == []
        assert 'http://dead.host:11434' in body['error']

    def test_connection_test_round_trips_through_the_stubbed_transport(self, client, llm_client, monkeypatch):
        payload = {'choices': [{'message': {'content': '  OK  '}}]}
        calls = []
        _patch_http(monkeypatch, llm_client, 'post', response=_FakeResponse(payload), calls=calls)
        request_body = {'provider': 'openrouter', 'model': 'x:free', 'api_key': 'k'}
        body = client.post('/api/llm/test', json=request_body).get_json()
        assert body['ok'] is True
        assert body['reply'] == 'OK'
        assert body['provider'] == 'openrouter:x:free'
        assert body['model'] == 'x:free'
        # The host is only meaningful for the local transport.
        assert body['host'] == ''
        assert body['latency_ms'] >= 0
        assert calls[0][0] == llm_client.OPENROUTER_CHAT_URL
        assert calls[0][1]['headers']['Authorization'] == 'Bearer k'

    def test_connection_test_reports_a_missing_key_instead_of_calling(self, client, llm_client, monkeypatch):
        calls = []
        _patch_http(monkeypatch, llm_client, 'post', response=_FakeResponse({}), calls=calls)
        body = client.post('/api/llm/test', json={'provider': 'openrouter', 'model': 'x:free'}).get_json()
        assert body['ok'] is False
        assert body['kind'] == 'auth'
        assert body['error'] == 'OpenRouter API key is missing'
        assert calls == []

    def test_connection_test_reports_a_missing_local_model(self, client):
        body = client.post('/api/llm/test', json={'provider': 'ollama', 'model': ''}).get_json()
        assert body['ok'] is False
        assert body['kind'] == 'model'
        assert 'No Ollama model set' in body['error']

    def test_a_saved_value_survives_a_lost_cache(self, client, settings_file):
        """Dropping the cache is what a server restart does: the file decides."""
        client.post('/api/settings', json={'window_size': '700x700'})
        settings_store._values = None
        assert settings_file.exists()
        assert client.get('/api/settings').get_json()['settings']['window_size'] == '700x700'
