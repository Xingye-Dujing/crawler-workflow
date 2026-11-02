"""The pure rules behind the login: credentials, the post-login destination, and the startup refusal.

The routes are exercised over HTTP in ``tests/api/test_auth_routes.py``; these are the parts a
route cannot express — in particular the cloud-mode refusals, which happen at import time and
therefore before any request exists.
"""

import pytest
from api import auth
from core.config import Config

from services.accounts import security

pytestmark = pytest.mark.unit


class TestSafeNext:
    """Only a path on this server may be a destination after login."""

    @pytest.mark.parametrize('target', ['/', '/api/config', '/workflow?name=a%20b', '/a/b#frag'])
    def test_local_paths_survive(self, target):
        assert auth.safe_next(target) == target

    @pytest.mark.parametrize(
        'target',
        [
            '',
            None,
            'https://evil.example/',
            '//evil.example/',
            '/\\evil.example',
            'javascript:alert(1)',
            'workflow',
            # A control character is legal in a URL path and ILLEGAL in a response header: the
            # redirect would raise after the session had already been created.
            '/a\nb',
            '/a\r\nX-Injected: 1',
            '/a\x00b',
            '/a\x01b',
        ],
    )
    def test_anything_else_becomes_the_root(self, target):
        assert auth.safe_next(target) == '/'


class TestAccountsMode:
    def test_a_password_turns_the_login_on(self, monkeypatch):
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'correct horse battery')
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        assert auth.auth_enabled() is True

    def test_no_password_and_no_registry_means_no_login(self, monkeypatch):
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        assert auth.auth_enabled() is False


class TestStartupRefusal:
    """Cloud mode is the only shape that reaches strangers, so it is the only one that refuses."""

    def test_a_local_run_needs_no_password_or_key(self, monkeypatch):
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        monkeypatch.setattr(Config, 'SECRET_KEY', Config.DEFAULT_SECRET_KEY)
        assert auth.startup_error() is None

    def test_a_cloud_run_without_a_bootstrap_password_refuses_by_naming_it(self, monkeypatch):
        monkeypatch.setattr(Config, 'CLOUD_MODE', True)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        monkeypatch.setattr(Config, 'SECRET_KEY', 'a-real-key')
        message = auth.startup_error()
        assert message and 'CRAWLER_ADMIN_PASSWORD' in message, message

    def test_a_cloud_run_with_the_published_key_refuses(self, monkeypatch):
        """The session cookie is signed with this key, so a known one is a login anyone can mint."""
        monkeypatch.setattr(Config, 'CLOUD_MODE', True)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'correct horse battery')
        monkeypatch.setattr(Config, 'SECRET_KEY', Config.DEFAULT_SECRET_KEY)
        message = auth.startup_error()
        assert message and 'SECRET_KEY' in message, message

    def test_a_local_login_with_the_published_key_refuses_too(self, monkeypatch):
        """The published key is unsafe wherever sessions are used, not only on a cloud host."""
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'correct horse battery')
        monkeypatch.setattr(Config, 'SECRET_KEY', Config.DEFAULT_SECRET_KEY)
        message = auth.startup_error()
        assert message and 'SECRET_KEY' in message, message

    def test_a_local_login_with_its_own_key_is_allowed(self, monkeypatch):
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'correct horse battery')
        monkeypatch.setattr(Config, 'SECRET_KEY', 'a-real-key')
        assert auth.startup_error() is None

    def test_a_cloud_run_with_both_set_is_allowed(self, monkeypatch):
        monkeypatch.setattr(Config, 'CLOUD_MODE', True)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'correct horse battery')
        monkeypatch.setattr(Config, 'SECRET_KEY', 'a-real-key')
        assert auth.startup_error() is None


class TestTheTokenComparison:
    """``hmac.compare_digest`` refuses a non-ASCII ``str`` — and every token a CLIENT sends is one."""

    def test_matching_tokens_are_accepted(self):
        assert security.token_matches('a-token', 'a-token') is True

    def test_a_non_ascii_token_is_refused_rather_than_raising(self):
        """A header value is decoded latin-1 and a form field UTF-8, so "café" reaches the
        comparison as text the stdlib will not compare: the CSRF check turned into an HTTP 500."""
        assert security.token_matches('caf\u00e9', 'another-token') is False
        assert security.token_matches('\u30c6\u30b9\u30c8', '\u30c6\u30b9\u30c8') is True

    def test_an_empty_token_never_matches_even_an_empty_expected(self):
        """A missing header must not be able to satisfy a session whose token is empty (a
        scheduled identity carries none)."""
        assert security.token_matches('', '') is False
        assert security.token_matches(None, 'x') is False


class TestThePublicBind:
    """A bind outside this machine with no accounts is an open server, whatever "cloud" says."""

    @pytest.fixture(autouse=True)
    def _no_registry(self, tmp_path, monkeypatch):
        """Accounts mode also turns on when ``accounts.db`` exists, so this class owns its path."""
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path / 'data'))
        monkeypatch.setattr(Config, 'ACCOUNTS_DB', str(tmp_path / 'data' / 'accounts.db'))

    @pytest.mark.parametrize('host', ['0.0.0.0', '::', '192.168.1.7', '0.0.0.0:5000'])
    def test_a_public_bind_without_accounts_is_refused_by_name(self, monkeypatch, host):
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        message = auth.public_bind_refusal(host)
        assert message and 'CRAWLER_ADMIN_PASSWORD' in message, message
        assert host in message

    @pytest.mark.parametrize('host', ['127.0.0.1', 'localhost', '::1', ''])
    def test_the_machine_keeps_its_own_bind(self, monkeypatch, host):
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
        assert auth.public_bind_refusal(host) is None

    def test_an_open_bind_is_fine_once_accounts_gate_it(self, monkeypatch):
        monkeypatch.setattr(Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'correct horse battery')
        assert auth.public_bind_refusal('0.0.0.0') is None
