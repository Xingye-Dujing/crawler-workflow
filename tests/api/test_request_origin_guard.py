"""The cross-origin wall this unauthenticated server needs.

``CORS(app)`` ran on flask-cors's default ``origins='*'``: while the server was up, any page
the user visited could read ``/api/cookies/status`` (the account list), the run history and
dataset contents. Restricting the header stops the READ, but a simple cross-origin POST is
still sent and still executed by Flask, so the real defence is refusing the request the
browser tagged with a foreign ``Origin`` — the one signal that names the caller. Every case
here is one shape of that origin and the answer it must get.
"""

import pytest

pytestmark = pytest.mark.api


class TestTheLoopbackOriginPattern:
    def test_a_ported_loopback_origin_matches(self, app_module):
        assert app_module._LOOPBACK_ORIGIN.match('http://127.0.0.1:5000')
        assert app_module._LOOPBACK_ORIGIN.match('http://localhost:5000')

    def test_a_hostname_thatmerely_starts_with_localhost_does_not_match(self, app_module):
        """flask-cors matches with ``re.match``, which anchors only the START — without the
        trailing ``$`` an attacker origin like ``localhost.evil.com`` would be allowed."""
        assert app_module._LOOPBACK_ORIGIN.match('http://localhost.evil.com') is None


class TestOriginIsLocal:
    @pytest.mark.parametrize(
        'origin',
        ['http://127.0.0.1:5000', 'http://localhost:3000', 'http://[::1]:5000', 'http://127.0.0.1'],
    )
    def test_the_loopback_hosts_are_trusted(self, app_module, origin):
        assert app_module._origin_is_local(origin) is True

    @pytest.mark.parametrize('origin', ['http://localhost.evil.com', 'http://evil.com', 'https://10.0.0.5:5000'])
    def test_a_foreign_origin_is_not(self, app_module, origin):
        assert app_module._origin_is_local(origin) is False

    def test_an_absent_origin_is_not_a_cross_origin_request(self, app_module):
        # curl, the test client and a top-level same-origin GET carry no Origin.
        assert app_module._origin_is_local('') is True


class TestTheRequestGuard:
    def test_a_foreign_origin_is_refused_before_the_handler_runs(self, client):
        refused = client.get('/api/cookies/status', headers={'Origin': 'http://evil.example'})
        assert refused.status_code == 403
        body = refused.get_json()
        assert body['ok'] is False, 'a browser-parsed JSON answer, never an HTML error page'
        assert 'evil.example' in body['error'], 'the refusal names the origin it turned away'

    def test_a_foreign_origin_cannot_fire_a_bulk_write(self, client):
        """The whole point: a blind cross-origin POST that no CORS header could have blocked."""
        refused = client.post('/api/history/clear', json={'confirm': True}, headers={'Origin': 'http://evil.example'})
        assert refused.status_code == 403

    def test_a_loopback_origin_is_served_normally(self, client):
        ok = client.get('/api/history/runs', headers={'Origin': 'http://127.0.0.1:5000'})
        assert ok.status_code == 200

    def test_a_headerless_call_is_served_normally(self, client):
        assert client.get('/api/history/runs').status_code == 200
