"""Tests for the runtime-configuration endpoints the UI bootstraps from.

Two read/write surfaces live here and neither one should surprise the frontend:

* ``GET /api/config`` — the three crawler defaults the canvas pre-fills its
  node forms with. What matters is that the payload is read from the live
  ``Config`` object on every request (a stale copy would make the settings
  panel a lie after an env change), not that any particular default is used.
* ``/api/cookies/*`` — credential bookkeeping. ``status`` only reports whether a
  file exists, and ``save`` refuses anything but the four known platforms,
  because the platform name becomes a path component. ``/api/cookies/generate``
  is deliberately untouched here: it drives a real browser and sleeps.
"""
import pytest

from config import Config

pytestmark = pytest.mark.api

CONFIG_KEYS = {'ollama_model', 'default_headless', 'max_workers'}
COOKIE_PLATFORMS = {'zhihu', 'weibo', 'xiaohongshu', 'wechat'}


class TestConfigEndpoint:
    def test_config_exposes_exactly_three_keys(self, client):
        response = client.get('/api/config')
        assert response.status_code == 200
        assert set(response.get_json()) == CONFIG_KEYS

    def test_config_reports_values_from_the_live_config_object(self, client):
        body = client.get('/api/config').get_json()
        assert body['ollama_model'] == Config.OLLAMA_MODEL
        assert body['default_headless'] is Config.DEFAULT_HEADLESS
        assert body['max_workers'] == Config.DEFAULT_MAX_WORKERS

    def test_config_is_not_cached_at_import_time(self, client, monkeypatch):
        monkeypatch.setattr(Config, 'OLLAMA_MODEL', 'patched-model:1')
        monkeypatch.setattr(Config, 'DEFAULT_MAX_WORKERS', 9)
        assert client.get('/api/config').get_json() == {
            'ollama_model': 'patched-model:1',
            'default_headless': True,
            'max_workers': 9,
        }

    def test_config_is_read_only(self, client):
        assert client.post('/api/config', json={}).status_code == 405


class TestCookieEndpoints:
    def test_status_answers_for_every_supported_platform(self, client):
        body = client.get('/api/cookies/status').get_json()
        assert body['ok'] is True
        assert set(body['cookies']) == COOKIE_PLATFORMS
        # Existence flags only: never the cookie contents.
        assert all(isinstance(flag, bool) for flag in body['cookies'].values())

    def test_save_persists_into_the_isolated_cookie_dir(self, client, app_module, data_root):
        payload = {'platform': 'weibo', 'cookies': [{'name': 'SUB', 'value': 'x'}]}
        response = client.post('/api/cookies/save', json=payload)
        body = response.get_json()
        assert response.status_code == 200
        assert body['ok'] is True
        assert 'weibo' in body['message']

        saved = data_root / 'data' / 'cookies' / 'weibo_cookies.json'
        assert saved.exists()
        assert app_module.cookie_manager.load('weibo') == [{'name': 'SUB', 'value': 'x'}]
        assert client.get('/api/cookies/status').get_json()['cookies']['weibo'] is True

    @pytest.mark.parametrize(
        ('payload', 'expected'),
        [
            ({'cookies': [{'name': 'a'}]}, 'Platform is required'),
            ({'platform': 'tiktok', 'cookies': [{'name': 'a'}]}, 'Unsupported platform'),
            ({'platform': 'zhihu', 'cookies': []}, 'Cookies data is required'),
        ],
    )
    def test_save_rejects_input_it_cannot_turn_into_a_safe_file(self, client, payload, expected):
        response = client.post('/api/cookies/save', json=payload)
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False
        assert expected in body['error']

    def test_save_of_a_foreign_platform_never_touches_the_store(self, client, data_root):
        payload = {'platform': '../escape', 'cookies': [{'name': 'a'}]}
        response = client.post('/api/cookies/save', json=payload)
        assert response.status_code == 400
        assert response.get_json()['ok'] is False
        # The platform name is a path component, so nothing may be written for
        # an unsupported one — neither inside the cookie dir nor above it.
        assert not (data_root / 'data' / 'cookies' / 'escape_cookies.json').exists()
        assert not (data_root / 'escape_cookies.json').exists()
