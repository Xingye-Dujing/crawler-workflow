"""The pure rules behind the login: credentials, the post-login destination, and the startup refusal.

The routes are exercised over HTTP in ``tests/api/test_auth_routes.py``; these are the parts a
route cannot express — in particular the cloud-mode refusals, which happen at import time and
therefore before any request exists.
"""

import pytest
from api import auth
from core.config import Config

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
