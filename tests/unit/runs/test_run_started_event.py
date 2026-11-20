"""The ``run.started`` event must carry the workflow's display name.

``_component_run`` resolves the name at its top via ``_wf_display_name``. Reading the
thread-local ``_wf_local.name`` instead published an empty ``workflow`` on a fresh run: the
monitor/consumer got an id with no name to show, even though the console line beside it named the
workflow correctly.
"""

from types import SimpleNamespace

import pytest
from runtime import run_events

from engine.run import _component_run
from services.runs.store import RunStore

pytestmark = pytest.mark.unit


def test_a_serial_component_publishes_its_workflow_name_on_run_started(tmp_path):
    events = []

    def listener(payload):
        events.append(payload)

    run_events.subscribe(listener)
    store = RunStore(str(tmp_path / 'runs.db'))
    engine = SimpleNamespace(nodes={'n1': {'id': 'n1', 'type': 'name', 'params': {'workflow_name': '日常采集'}}})
    created = []
    resumable = []
    ctx = {'open_records': []}
    try:
        result = _component_run(0, engine, ctx, created, resumable, False, 'fp', '', store, 'run-0', 'serial', True)
    finally:
        run_events.unsubscribe(listener)

    started = [event for event in events if event['event'] == 'run.started']
    assert len(started) == 1, events
    assert started[0]['workflow'] == '日常采集', 'the event carried an empty/incorrect workflow name'
    assert started[0]['workflow'], 'a fresh run published no workflow name'
    assert started[0]['run_id'] == result['run_id']
