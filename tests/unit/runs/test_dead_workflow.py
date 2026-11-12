"""A workflow-level fault must leave a durable failure, not a silent 已完成 run.

``_run_single_workflow`` raises outside ``run_node_durable`` when the graph itself is broken
(``group_by_level`` / ``_inputs_for`` / a stage that cannot be built). The run verdict is read
from the node rows, so the branch has to write FAILED for the nodes it never reached.
"""

from types import SimpleNamespace

import pytest
from runtime.state import execution_state

from engine.run import _mark_dead_workflow
from services.runs.store import NODE_DONE, NODE_FAILED, RunStore

pytestmark = pytest.mark.unit


def _engine():
    return SimpleNamespace(
        nodes={
            'n1': {'id': 'n1', 'type': 'source', 'title': '源'},
            'n2': {'id': 'n2', 'type': 'output', 'title': '导出'},
        }
    )


def test_every_unsettled_node_of_the_dead_workflow_is_failed(tmp_path):
    store = RunStore(str(tmp_path / 'runs.db'))
    store.start_run('r1', 'wf', 'fp', headless=True)
    ctx = {'store': store, 'run_id': 'r1', 'fingerprints': {}}
    execution_state['attempted_nodes'] = set()
    try:
        _mark_dead_workflow(ctx, _engine(), 0, RuntimeError('bad graph'))
    finally:
        attempted = set(execution_state['attempted_nodes'])
        execution_state['attempted_nodes'] = set()

    statuses = store.node_statuses('r1')
    assert {nid: row['status'] for nid, row in statuses.items()} == {
        'n1': NODE_FAILED,
        'n2': NODE_FAILED,
    }
    assert 'bad graph' in statuses['n1']['error']
    assert attempted == {'n1', 'n2'}, 'the finish line only counts attempted nodes'


def test_a_node_that_already_finished_keeps_its_own_verdict(tmp_path):
    store = RunStore(str(tmp_path / 'runs.db'))
    store.start_run('r1', 'wf', 'fp', headless=True)
    store.begin_node('r1', 'n1', 'source', title='源')
    store.finish_node('r1', 'n1', NODE_DONE)
    ctx = {'store': store, 'run_id': 'r1', 'fingerprints': {}}
    execution_state['attempted_nodes'] = set()
    try:
        _mark_dead_workflow(ctx, _engine(), 0, RuntimeError('bad graph'))
    finally:
        execution_state['attempted_nodes'] = set()

    statuses = store.node_statuses('r1')
    assert statuses['n1']['status'] == NODE_DONE
    assert statuses['n2']['status'] == NODE_FAILED
