"""The pure rules behind the login: credentials, the post-login destination, and the startup refusal.

The routes are exercised over HTTP in ``tests/api/test_auth_routes.py``; these are the parts a
route cannot express — in particular the cloud-mode refusals, which happen at import time and
therefore before any request exists.
"""

import pytest
from api import auth

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
        ],
    )
    def test_anything_else_becomes_the_root(self, target):
        assert auth.safe_next(target) == '/'


class TestCredentials:
    def test_both_halves_must_match(self, monkeypatch):
        monkeypatch.setattr(auth.Config, 'AUTH_USER', 'admin')
        monkeypatch.setattr(auth.Config, 'AUTH_PASSWORD', 'correct horse')
        assert auth.check_credentials('admin', 'correct horse') is True
        assert auth.check_credentials('admin', 'wrong') is False
        assert auth.check_credentials('root', 'correct horse') is False
        assert auth.check_credentials('', '') is False

    def test_no_password_means_no_login_at_all(self, monkeypatch):
        monkeypatch.setattr(auth.Config, 'AUTH_PASSWORD', '')
        assert auth.auth_enabled() is False
        assert auth.check_credentials('', '') is False


class TestStartupRefusal:
    """Cloud mode is the only shape that reaches strangers, so it is the only one that refuses."""

    def test_a_local_run_needs_no_password_or_key(self, monkeypatch):
        monkeypatch.setattr(auth.Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(auth.Config, 'AUTH_PASSWORD', '')
        monkeypatch.setattr(auth.Config, 'SECRET_KEY', auth.Config.DEFAULT_SECRET_KEY)
        assert auth.startup_error() is None

    def test_a_cloud_run_without_a_password_refuses_by_naming_the_variable(self, monkeypatch):
        monkeypatch.setattr(auth.Config, 'CLOUD_MODE', True)
        monkeypatch.setattr(auth.Config, 'AUTH_PASSWORD', '')
        monkeypatch.setattr(auth.Config, 'SECRET_KEY', 'a-real-key')
        message = auth.startup_error()
        assert message and 'CRAWLER_AUTH_PASSWORD' in message, message

    def test_a_cloud_run_with_the_published_key_refuses(self, monkeypatch):
        """The session cookie is signed with this key, so a known one is a login anyone can mint."""
        monkeypatch.setattr(auth.Config, 'CLOUD_MODE', True)
        monkeypatch.setattr(auth.Config, 'AUTH_PASSWORD', 'correct horse')
        monkeypatch.setattr(auth.Config, 'SECRET_KEY', auth.Config.DEFAULT_SECRET_KEY)
        message = auth.startup_error()
        assert message and 'SECRET_KEY' in message, message

    def test_a_local_login_with_the_published_key_refuses_too(self, monkeypatch):
        """The published key is unsafe wherever sessions are used, not only on a cloud host."""
        monkeypatch.setattr(auth.Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(auth.Config, 'AUTH_PASSWORD', 'correct horse')
        monkeypatch.setattr(auth.Config, 'SECRET_KEY', auth.Config.DEFAULT_SECRET_KEY)
        message = auth.startup_error()
        assert message and 'SECRET_KEY' in message, message

    def test_a_local_login_with_its_own_key_is_allowed(self, monkeypatch):
        monkeypatch.setattr(auth.Config, 'CLOUD_MODE', False)
        monkeypatch.setattr(auth.Config, 'AUTH_PASSWORD', 'correct horse')
        monkeypatch.setattr(auth.Config, 'SECRET_KEY', 'a-real-key')
        assert auth.startup_error() is None

    def test_a_cloud_run_with_both_set_is_allowed(self, monkeypatch):
        monkeypatch.setattr(auth.Config, 'CLOUD_MODE', True)
        monkeypatch.setattr(auth.Config, 'AUTH_PASSWORD', 'correct horse')
        monkeypatch.setattr(auth.Config, 'SECRET_KEY', 'a-real-key')
        assert auth.startup_error() is None
