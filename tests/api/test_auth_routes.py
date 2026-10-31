"""The login gate over HTTP: what an unauthenticated stranger can reach, and what a session buys.

The gate is a single app-level ``before_request`` (``app._require_login`` → ``api/auth.gate``), so
the matrix that matters is "API answered 401 / page redirected / login itself reachable", not one
test per route: a per-route list would go stale the next time a Blueprint is added.

Accounts are enabled per test by pointing ``Config.ADMIN_PASSWORD`` at a bootstrap password and
letting the service create the first administrator in the test's own ``accounts.db`` (the shared
conftest gives every test a fresh path).
"""

import re

import pytest
from api import auth
from core.config import Config
from runtime.account_context import Account

from services.accounts import service as accounts_service

pytestmark = pytest.mark.api

PASSWORD = 'correct horse battery'


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(Config, 'ADMIN_USER', 'admin')
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', PASSWORD)
    monkeypatch.setattr(Config, 'SESSION_IDLE_MINUTES', 120)
    monkeypatch.setattr(Config, 'SESSION_MAX_HOURS', 24)
    accounts_service.reset_service()
    accounts_service.reset_throttle()
    accounts_service.get_account_service().bootstrap()
    yield auth
    accounts_service.reset_service()


def _login(client, password=PASSWORD, user='admin', next_url='/'):
    page = client.get('/login?lang=en')
    match = re.search(r'name="csrf" value="([^"]+)"', page.get_data(as_text=True))
    assert match, 'the login form must carry its one-shot CSRF token'
    return client.post(
        '/login',
        data={'username': user, 'password': password, 'next': next_url, 'csrf': match.group(1)},
    )


def _csrf(client) -> str:
    return client.get('/api/config').get_json()['auth']['csrf_token']


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

    def test_the_page_lets_the_browser_report_its_origin(self, client, auth_on):
        """``no-referrer`` made Chromium send ``Origin: null`` on the login POST.

        Measured in real Chrome 148: the document origin is ``http://127.0.0.1:PORT``, but the
        form submission carried ``Origin: null`` and no Referer, so the app's own foreign-origin
        guard refused every real login while curl and the test client passed. ``same-origin``
        keeps the cross-site referrer suppressed and lets a same-origin POST name itself.
        """
        assert client.get('/login').headers['Referrer-Policy'] == 'same-origin'

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
        payload = config.get_json()
        assert payload['auth_required'] is True
        assert payload['auth']['user'] == {'username': 'admin', 'role': 'admin'}
        assert payload['auth']['csrf_token']

    def test_a_wrong_password_is_refused_and_sets_no_session(self, client, auth_on):
        response = _login(client, password='wrong')
        assert response.status_code == 401
        assert 'Wrong' in response.get_data(as_text=True), 'the page must say what failed'
        assert client.get('/api/config').status_code == 401

    def test_a_wrong_username_is_refused(self, client, auth_on):
        assert _login(client, user='root').status_code == 401
        assert client.get('/api/config').status_code == 401

    def test_a_post_without_the_form_token_is_refused(self, client, auth_on):
        response = client.post('/login', data={'username': 'admin', 'password': PASSWORD, 'next': '/'})
        assert response.status_code == 401
        assert client.get('/api/config').status_code == 401

    def test_a_second_get_does_not_break_the_rendered_form_token(self, client, auth_on):
        """Chrome fetches ``/login?next=/favicon.ico`` right after the document.

        That second GET used to mint a new session token after the page had rendered the old one,
        so a real browser's submit was refused while curl and the test client passed. The token is
        minted once and reused until the POST consumes it.
        """
        page = client.get('/login?lang=en').get_data(as_text=True)
        first = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        client.get('/login?next=%2Ffavicon.ico')
        second_page = client.get('/login?lang=en').get_data(as_text=True)
        assert re.search(r'name="csrf" value="([^"]+)"', second_page).group(1) == first
        response = client.post(
            '/login',
            data={'username': 'admin', 'password': PASSWORD, 'next': '/', 'csrf': first},
        )
        assert response.status_code == 302, response.get_data(as_text=True)

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
        token = _csrf(client)
        assert client.get('/api/config').status_code == 200
        response = client.post('/logout', headers={'X-CSRF-Token': token})
        assert response.status_code == 302 and response.headers['Location'] == '/login'
        assert client.get('/api/config').status_code == 401

    def test_a_mutating_call_without_the_csrf_token_is_refused(self, client, auth_on):
        _login(client)
        assert client.post('/logout').status_code == 403
        assert client.get('/api/config').status_code == 200

    def test_logout_revokes_a_copied_cookie(self, client, auth_on):
        """Clearing only the browser's copy leaves a live session row; the server must revoke it,
        or a stolen cookie outlives the logout."""
        _login(client)
        copied = client.get_cookie('cixi_session').value
        client.post('/logout', headers={'X-CSRF-Token': _csrf(client)})
        client.set_cookie('cixi_session', copied)
        assert client.get('/api/config').status_code == 401

    def test_changing_the_password_revokes_other_sessions(self, client, auth_on):
        """The current session survives; every other session of the account is revoked."""
        _login(client)
        other = client.application.test_client()
        other.environ_base['HTTP_X_LANG'] = 'en'
        _login(other)
        assert other.get('/api/config').status_code == 200
        response = client.post(
            '/api/account/password',
            json={'current_password': PASSWORD, 'new_password': 'a brand new password'},
            headers={'X-CSRF-Token': _csrf(client)},
        )
        assert response.status_code == 200, response.get_json()
        assert client.get('/api/config').status_code == 200
        assert other.get('/api/config').status_code == 401


class TestAForcedPasswordChange:
    def test_every_api_is_refused_until_the_password_changes(self, client, auth_on):
        svc = accounts_service.get_account_service()
        row = svc.store.get_user_by_username('admin')
        svc.reset_password(Account(row['user_id'], 'admin', 'admin'), row['user_id'], PASSWORD, True)
        _login(client)
        blocked = client.get('/api/data/datasets')
        assert blocked.status_code == 403
        assert blocked.headers['X-Password-Change-Required'] == '1'
        assert client.get('/api/config').status_code == 200
        changed = client.post(
            '/api/account/password',
            json={'current_password': PASSWORD, 'new_password': 'a brand new password'},
            headers={'X-CSRF-Token': _csrf(client)},
        )
        assert changed.status_code == 200, changed.get_json()
        assert client.get('/api/data/datasets').status_code == 200


class TestWithoutAPassword:
    """The local single-user default: no login page, no gate, no change from before."""

    def test_nothing_is_gated(self, client, monkeypatch):
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        assert client.get('/api/config').status_code == 200
        assert client.get('/').status_code == 200

    def test_the_login_page_sends_you_home(self, client, monkeypatch):
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        response = client.get('/login')
        assert response.status_code == 302 and response.headers['Location'] == '/'

    def test_logout_is_a_no_op(self, client, monkeypatch):
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        response = client.post('/logout')
        assert response.status_code == 302 and response.headers['Location'] == '/'
