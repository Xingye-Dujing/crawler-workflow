"""Tests for the runtime-configuration endpoints the UI bootstraps from.

Two read/write surfaces live here and neither one should surprise the frontend:

* ``GET /api/config`` — the three crawler defaults the canvas pre-fills its
  node forms with. What matters is that the payload is read from the live
  ``Config`` object on every request (a stale copy would make the settings
  panel a lie after an env change), not that any particular default is used.
* ``GET /api/capabilities`` — the crawl matrix the Data Source panel builds
  itself from. The endpoint is the only way the browser learns what a platform
  can do, so the payload has to be the matrix and nothing else.
* ``/api/cookies/*`` — credential bookkeeping. ``status`` only reports whether a
  file exists, and ``save`` refuses anything but the platforms
  ``CookieManager.PLATFORMS`` lists, because the platform name becomes a path
  component — and it drops cookies that belong to some other site.
  ``/api/cookies/generate`` is deliberately untouched here: it drives a real
  browser and sleeps.
"""

import pytest

from config import Config
from services.cookie_manager import CookieManager

pytestmark = pytest.mark.api

CONFIG_KEYS = {'ollama_model', 'default_headless', 'max_workers'}
# The cookie panel's platform set is the manager's own list — mirroring it here
# would only ever record the last time someone forgot the other side.
COOKIE_PLATFORMS = set(CookieManager.PLATFORMS)


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


class TestCapabilitiesEndpoint:
    """``/api/capabilities`` is the panel's whole vocabulary, so the two things
    worth pinning are that it is the matrix (not a second list someone maintains)
    and that it carries keys rather than sentences (the payload has no
    language — the canvas translates it)."""

    def test_the_endpoint_hands_out_the_matrix_itself(self, client):
        import crawl_capabilities

        body = client.get('/api/capabilities').get_json()
        assert body == crawl_capabilities.as_dict()

    def test_the_payload_names_the_platforms_the_crawlers_can_crawl(self, client):
        from crawlers import CRAWLERS, is_crawlable

        body = client.get('/api/capabilities').get_json()
        assert [p['platform'] for p in body['platforms']] == [p for p in CRAWLERS if is_crawlable(p)]

    def test_no_text_travels_to_the_browser(self, client):
        """Every word the panel shows is a catalogue key.

        The test is structural because a stray sentence would not break anything
        until somebody switched language and found half a form still in the
        other one.
        """
        body = client.get('/api/capabilities').get_json()
        keys = []

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key.endswith('Key'):
                        keys.append((key, value))
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(body)
        assert keys, 'the payload stopped carrying any catalogue keys at all'
        # '' is how an absent label travels (not every field has a hint); a key
        # that is neither empty nor dotted is a sentence shipped to the browser.
        assert all(value == '' or '.' in value for _key, value in keys), keys

    def test_it_is_read_only(self, client):
        assert client.post('/api/capabilities', json={}).status_code == 405


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

    def test_pasted_cookies_from_another_site_never_enter_the_platform_file(self, client, app_module):
        """An extension export carries whatever the browser held, and a YouTube
        session is issued through a Google sign-in — so ``.google.com`` rows sit
        in the same paste. Those open Gmail and Drive, and have no business in a
        file named after YouTube. A lookalike suffix must not pass either, and an
        entry with no domain is kept because pastes routinely omit it."""
        payload = {
            'platform': 'youtube',
            'cookies': [
                {'name': 'SID', 'value': 'a', 'domain': '.youtube.com'},
                {'name': '__Secure-1PSID', 'value': 'b', 'domain': 'www.youtube.com'},
                {'name': 'SID', 'value': 'c', 'domain': '.google.com'},
                {'name': 'session', 'value': 'd', 'domain': '.evilyoutube.com'},
                {'name': 'PREF', 'value': 'e'},
            ],
        }
        response = client.post('/api/cookies/save', json=payload)
        body = response.get_json()
        assert response.status_code == 200
        assert body['count'] == 3
        assert [c['name'] for c in app_module.cookie_manager.load('youtube')] == ['SID', '__Secure-1PSID', 'PREF']

    def test_a_paste_of_nobody_s_here_is_refused_instead_of_saved_empty(self, client, app_module):
        """Writing an empty list would leave ``youtube_cookies.json`` behind, and
        the panel's exists-flag would call that "cookie configured"."""
        # The data dir is session-wide (the app has no per-test override), and the
        # test above just saved a YouTube file into it — start from a known blank.
        app_module.cookie_manager.delete('youtube')
        response = client.post(
            '/api/cookies/save', json={'platform': 'youtube', 'cookies': [{'name': 'SID', 'domain': '.google.com'}]}
        )
        assert response.status_code == 400
        assert response.get_json()['ok'] is False
        assert app_module.cookie_manager.exists('youtube') is False

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
