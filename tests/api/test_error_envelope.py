"""Every refusal on ``/api/`` answers the envelope the panel parses.

The frontend calls ``resp.json()`` on every answer, so a framework page (Werkzeug's HTML 404, its
HTML 500, a debug traceback) reads to the user as "the button is broken" — the one outcome this
project's error handling exists to avoid. Two doors are pinned here: a refusal Flask raises itself
(:class:`werkzeug.exceptions.HTTPException`) and an exception no handler caught.

The third test covers the proxy prefix, because that value builds ``Location`` headers: a
client-supplied ``X-Forwarded-Prefix: //evil.example`` used to become a protocol-relative redirect
on the login page, concatenated before ``safe_next`` was ever consulted.
"""

import flask
import pytest
from werkzeug.exceptions import NotFound

pytestmark = pytest.mark.api


class TestApiRefusalsAreJson:
    def test_an_unknown_api_path_answers_the_envelope(self, client):
        with client.get('/api/definitely-not-a-route') as resp:
            assert resp.status_code == 404
            body = resp.get_json()
            assert body and body['ok'] is False, body
            assert body.get('status') == 404

    def test_a_framework_refusal_outside_api_keeps_its_own_page(self, client):
        """`/` and the static tree are read by a human, not by `resp.json()`."""
        with client.get('/definitely-not-a-route') as resp:
            assert resp.status_code == 404
            assert resp.mimetype != 'application/json'

    def test_an_unhandled_failure_answers_the_envelope(self, app_module):
        with app_module.app.test_request_context('/api/anything'):
            body, status = app_module._unexpected_failure(RuntimeError('kaboom'))
        assert status == 500
        payload = body.get_json()
        assert payload['ok'] is False
        assert 'kaboom' not in payload['error'], 'the cause belongs in the log, not in the response'

    def test_an_http_exception_reaching_the_catch_all_keeps_its_status(self, app_module):
        """The catch-all must not turn a 404 into a 500."""
        with app_module.app.test_request_context('/api/anything'):
            body, status = app_module._unexpected_failure(NotFound())
        assert status == 404
        assert body.get_json()['ok'] is False


class TestForwardedPrefixIsAPath:
    """`ProxyFix(x_prefix=1)` copies a CLIENT header into ``SCRIPT_NAME``; it must be a path only."""

    def test_a_prefix_that_is_a_redirect_is_dropped(self, app_module):
        with app_module.app.test_request_context('/', environ_overrides={'SCRIPT_NAME': '//evil.example'}):
            assert app_module._refuse_unsafe_url_prefix() is None
            assert flask.request.environ['SCRIPT_NAME'] == ''

    @pytest.mark.parametrize('hostile', ['//evil.example', 'https://evil.example', '/a/../b', '/a\\b', '/a b'])
    def test_every_unsafe_shape_is_dropped(self, app_module, hostile):
        with app_module.app.test_request_context('/', environ_overrides={'SCRIPT_NAME': hostile}):
            app_module._refuse_unsafe_url_prefix()
            assert flask.request.environ['SCRIPT_NAME'] == '', hostile

    @pytest.mark.parametrize('honest', ['', '/cixi', '/tools/cixi'])
    def test_a_real_prefix_is_kept(self, app_module, honest):
        with app_module.app.test_request_context('/', environ_overrides={'SCRIPT_NAME': honest}):
            app_module._refuse_unsafe_url_prefix()
            assert flask.request.environ['SCRIPT_NAME'] == honest
