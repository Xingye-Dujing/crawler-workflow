"""API-test helpers layered on the shared ``client`` fixture from tests/conftest.py."""

import pytest
from sessions import profiles


@pytest.fixture(autouse=True)
def _forward_run_console(monkeypatch):
    """A test's patch of ``app.add_log`` still captures what the run worker prints.

    The orchestration resolves ``add_log`` in its own module (``engine.run``), so patching the app
    re-export alone would silence only the app-side lines and let the worker print into the real
    buffer — the case would then assert on console text it never captured. Same call-time lookup
    the executor seams already use (``tests/executor_seams.py``).
    """
    import app as app_module
    from executor_seams import forward

    import engine.run

    forward(monkeypatch, engine.run, 'add_log', app_module)


@pytest.fixture
def profiles_off(monkeypatch):
    """This test's machine has no browser profiles, so nothing buys a Chrome.

    Saving IS the update now: ``/api/cookies/save`` opens a headless browser to carry the
    pasted session into that account's own directory. The fast tier has no browser to give
    it, and that attempt was reaching past the socket block — pytest-socket reported it as
    a warning while the plant swallowed the failure and answered 「种入失败」. A test that is
    about something else (what was saved, which verdict the cache dropped) therefore was
    reading an answer from a machine state it never declared. Switching the feature off is
    a real setting, so the reply such a test asserts is the reply that machine gives.

    The tests ABOUT the plant stub the browser factory instead — see
    ``test_cookie_save_plants_profile.py`` — because for those the launch is the subject.
    """
    monkeypatch.setattr(profiles, 'is_enabled', lambda: False)


@pytest.fixture
def paste(client):
    """``paste(records, name=…)`` → dataset id, through the real paste endpoint.

    Test data arrives over HTTP rather than by poking the store, so a test that
    needs a file also proves the response hands back an id the Upload node and
    the analysis endpoints can resolve.
    """

    def _paste(records, name: str = 'pasted'):
        response = client.post('/api/data/paste', json={'data': records, 'name': name})
        body = response.get_json()
        assert response.status_code == 200, body
        assert body['ok'] is True, body
        return body['dataset_id']

    return _paste
