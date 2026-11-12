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

    Every module that prints from the run path has to be listed here, one per forward: the
    scheduled fire's narration moved to ``engine.run_schedule`` on 2026-10-29, and a fixture that
    kept forwarding only to ``engine.run`` would let that line print into the real buffer while
    the test asserted on a list it never filled.
    """
    import api.biblio
    import api.report
    import app as app_module
    import nodes.executors.accumulate
    import nodes.executors.analysis
    import nodes.executors.biblio
    import nodes.executors.comment
    import nodes.executors.compile
    import nodes.executors.fuse
    import nodes.executors.output
    import nodes.executors.process
    import nodes.executors.resume
    import nodes.executors.source
    import nodes.executors.tokenize
    import nodes.executors.upload
    import nodes.executors.verify
    import nodes.executors.visualize
    import sessions.routes
    from executor_seams import forward

    import engine.run
    import engine.run_schedule
    import services.analysis.llm
    import services.charts.outputs
    import services.ingest.lifecycle
    import services.runs.queue
    import services.runs.settlement

    # The census (tests/unit/gates/test_console_seam_census.py) enumerates EVERY backend
    # module that resolves add_log from runtime.state, so this list must stay complete: a
    # module that prints during a run but is not forwarded lets a test patch app.add_log
    # and assert on a list the module never filled.
    forward(monkeypatch, api.biblio, 'add_log', app_module)
    forward(monkeypatch, api.report, 'add_log', app_module)
    forward(monkeypatch, engine.run, 'add_log', app_module)
    forward(monkeypatch, engine.run_schedule, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.accumulate, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.analysis, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.biblio, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.comment, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.compile, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.fuse, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.output, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.process, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.resume, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.source, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.tokenize, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.upload, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.verify, 'add_log', app_module)
    forward(monkeypatch, nodes.executors.visualize, 'add_log', app_module)
    forward(monkeypatch, services.analysis.llm, 'add_log', app_module)
    forward(monkeypatch, services.charts.outputs, 'add_log', app_module)
    forward(monkeypatch, services.ingest.lifecycle, 'add_log', app_module)
    forward(monkeypatch, services.runs.queue, 'add_log', app_module)
    forward(monkeypatch, services.runs.settlement, 'add_log', app_module)
    forward(monkeypatch, sessions.routes, 'add_log', app_module)


@pytest.fixture(autouse=True)
def _documents_run_inline(request, monkeypatch):
    """Document jobs run on the caller's thread unless the case is ABOUT the job runtime.

    The report/Paper/chart-PDF routes now start a background job and the product polls. Most
    API cases pin what the document IS, not how it is scheduled, so running the same body inline
    keeps the historical status/body and pays no thread + poll per assertion. ``async_documents``
    keeps the real runner so the 202/poll/ownership path has its own tests.
    """
    if request.node.get_closest_marker('async_documents'):
        return
    from services.reports import jobs

    monkeypatch.setattr(jobs, 'start', jobs.run_now)


@pytest.fixture
def profiles_off(monkeypatch):
    """This test's machine has no browser profiles, so nothing buys a Chrome.

    Saving IS the update now: ``/api/cookies/save`` opens a headless browser to carry the
    pasted session into that account's own directory. The fast tier has no browser to give
    it, and that attempt was reaching past the socket block — pytest-socket reported it as
    a warning while the plant swallowed the failure and answered “种入失败”. A test that is
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
