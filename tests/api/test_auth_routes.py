"""The login gate over HTTP: what an unauthenticated stranger can reach, and what a session buys.

The gate is a single app-level ``before_request`` (``app._require_login`` → ``api/auth.gate``), so
the matrix that matters is "API answered 401 / page redirected / login itself reachable", not one
test per route: a per-route list would go stale the next time a Blueprint is added.

The login is enabled per test by patching ``Config.AUTH_PASSWORD``, because that is the switch the
product reads at request time (the same class attribute the startup refusal consults).
"""

import pytest
from api import auth
from core.config import Config

pytestmark = pytest.mark.api

PASSWORD = 'correct horse battery'


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(Config, 'AUTH_USER', 'admin')
    monkeypatch.setattr(Config, 'AUTH_PASSWORD', PASSWORD)
    return auth


def _login(client, password=PASSWORD, user='admin', next_url='/'):
    return client.post('/login', data={'username': user, 'password': password, 'next': next_url})


class TestWithoutASession:
    def test_an_api_call_answers_401_with_the_marker_header(self, client, auth_on):
        response = client.get('/api/config')
        assert response.status_code == 401
        body = response.get_json()
        assert body['ok'] is False
        assert 'Sign in' in body['error'], body
        # The page tells THIS 401 (expired login) from a node refusal by the header, and sends the
        # user to the login page instead of showing the node's sentence.
        assert response.headers['X-Auth-Required'] == '1'

    def test_a_page_redirects_to_the_login_and_keeps_the_address(self, client, auth_on):
        response = client.get('/?tab=2')
        assert response.status_code == 302
        assert response.headers['Location'].startswith('/login?next=')
        assert '%2F%3Ftab%3D2' in response.headers['Location'], response.headers['Location']

    def test_the_login_page_itself_is_reachable(self, client, auth_on):
        response = client.get('/login')
        assert response.status_code == 200
        assert response.mimetype == 'text/html'
        body = response.get_data(as_text=True)
        assert 'name="username"' in body and 'type="password"' in body
        assert 'auth.required' not in body, 'the page must show a sentence, not a catalogue key'

    def test_the_login_page_speaks_the_language_of_the_browser_that_asked(self, client, auth_on):
        response = client.get(
            '/login', environ_overrides={'HTTP_X_LANG': ''}, headers={'Accept-Language': 'zh-CN,zh;q=0.9'}
        )
        assert '登录' in response.get_data(as_text=True)
        response = client.get(
            '/login', environ_overrides={'HTTP_X_LANG': ''}, headers={'Accept-Language': 'en-US,en;q=0.9'}
        )
        assert 'Sign in' in response.get_data(as_text=True)


class TestLoggingIn:
    def test_the_right_password_opens_the_session(self, client, auth_on):
        response = _login(client)
        assert response.status_code == 302
        assert response.headers['Location'] == '/'
        config = client.get('/api/config')
        assert config.status_code == 200
        assert config.get_json()['auth_required'] is True

    def test_a_wrong_password_is_refused_and_sets_no_session(self, client, auth_on):
        response = _login(client, password='wrong')
        assert response.status_code == 401
        assert 'Wrong' in response.get_data(as_text=True), 'the page must say what failed'
        assert client.get('/api/config').status_code == 401

    def test_a_wrong_username_is_refused(self, client, auth_on):
        assert _login(client, user='root').status_code == 401
        assert client.get('/api/config').status_code == 401

    def test_the_next_address_is_honoured(self, client, auth_on):
        response = _login(client, next_url='/api/config')
        assert response.headers['Location'] == '/api/config'
        assert client.get('/api/config').status_code == 200

    @pytest.mark.parametrize('next_url', ['https://evil.example/', '//evil.example/', '/\\evil.example'])
    def test_an_offsite_next_is_ignored(self, client, auth_on, next_url):
        response = _login(client, next_url=next_url)
        assert response.headers['Location'] == '/'

    def test_logout_is_post_only(self, client, auth_on):
        """A cross-site image or link must not be able to end someone's session. A GET reaches no
        logout handler — either the route's 405 or the static catch-all's 404, depending on how
        Werkzeug orders the two — and the session is still alive afterwards."""
        _login(client)
        assert client.get('/logout').status_code in (404, 405)
        assert client.get('/api/config').status_code == 200

    def test_logout_ends_the_session(self, client, auth_on):
        _login(client)
        assert client.get('/api/config').status_code == 200
        response = client.post('/logout')
        assert response.status_code == 302 and response.headers['Location'] == '/login'
        assert client.get('/api/config').status_code == 401

    def test_logout_revokes_a_copied_cookie(self, client, auth_on):
        """Clearing only the browser's copy leaves a signed cookie that still opens the app; the
        server must close the id, or a stolen cookie outlives the logout."""
        _login(client)
        copied = client.get_cookie('cixi_session').value
        client.post('/logout')
        client.set_cookie('cixi_session', copied)
        assert client.get('/api/config').status_code == 401

    def test_a_session_cannot_be_replayed_after_the_password_changes(self, client, auth_on, monkeypatch):
        """A signed cookie outlives the process, so the credential is stamped into it: changing the
        password revokes every session already handed out."""
        _login(client)
        assert client.get('/api/config').status_code == 200
        monkeypatch.setattr(Config, 'AUTH_PASSWORD', 'a new password')
        assert client.get('/api/config').status_code == 401


class TestWithoutAPassword:
    """The local single-user default: no login page, no gate, no change from before."""

    def test_nothing_is_gated(self, client, monkeypatch):
        monkeypatch.setattr(Config, 'AUTH_PASSWORD', '')
        assert client.get('/api/config').status_code == 200
        assert client.get('/').status_code == 200

    def test_the_login_page_sends_you_home(self, client, monkeypatch):
        monkeypatch.setattr(Config, 'AUTH_PASSWORD', '')
        response = client.get('/login')
        assert response.status_code == 302 and response.headers['Location'] == '/'

    def test_logout_is_a_no_op(self, client, monkeypatch):
        monkeypatch.setattr(Config, 'AUTH_PASSWORD', '')
        response = client.post('/logout')
        assert response.status_code == 302 and response.headers['Location'] == '/'
