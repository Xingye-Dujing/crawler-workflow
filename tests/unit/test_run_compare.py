"""Run-to-run comparison: statuses, row counts and one node's table diff."""

import pytest

from services.run_compare import compare_runs
from services.run_store import NODE_DONE, RUN_COMPLETED, RunStore


@pytest.fixture()
def store(tmp_path):
    instance = RunStore(str(tmp_path / 'runs.db'))
    yield instance
    instance.close()


def _seed(store, run_id, nodes, workflow_name='wf', fingerprint='fp-a'):
    store.start_run(run_id, workflow_name, fingerprint, node_total=len(nodes))
    for node_id, node_type, rows in nodes:
        store.begin_node(run_id, node_id, node_type, title=node_type.title(), fingerprint=f'{node_id}-fp')
        store.append_rows(run_id, node_id, rows)
        store.finish_node(run_id, node_id, NODE_DONE)
    store.finish_run(run_id, RUN_COMPLETED)


def _two_runs(store):
    _seed(
        store,
        'r1',
        [
            ('node-0', 'source', [{'id': 1, 't': 'a'}, {'id': 2, 't': 'b'}]),
            ('node-1', 'output', [{'k': 'x', 'v': 1}, {'k': 'y', 'v': 2}]),
        ],
    )
    _seed(
        store,
        'r2',
        [
            ('node-0', 'source', [{'id': 1, 't': 'A'}, {'id': 3, 't': 'c'}]),
            ('node-1', 'output', [{'k': 'x', 'v': 1}, {'k': 'z', 'v': 3}]),
        ],
    )


class TestCompareRuns:
    def test_the_default_node_is_the_latest_common_node_with_rows(self, store):
        _two_runs(store)
        result = compare_runs(store, 'r1', 'r2')
        assert result['node']['node_id'] == 'node-1'
        assert result['node']['rows_a'] == 2 and result['node']['rows_b'] == 2
        assert result['diff']['added_count'] == 1
        assert result['diff']['removed_count'] == 1
        assert result['same_shape'] is True
        assert result['same_workflow'] is True

    def test_a_named_node_and_key_report_changed_rows(self, store):
        _two_runs(store)
        result = compare_runs(store, 'r1', 'r2', node_id='node-0', key='id')
        assert result['node']['node_id'] == 'node-0'
        # The whole-row multiset sees the changed id-1 row on both the added and
        # removed sides; the named key is what adds the one changed pair on top.
        assert result['diff']['added_count'] == 2
        assert result['diff']['removed_count'] == 2
        assert result['diff']['changed_count'] == 1
        changed = result['diff']['changed'][0]
        assert changed['key'] == 1
        assert changed['a']['t'] == 'a' and changed['b']['t'] == 'A'

    def test_the_node_summary_lists_both_statuses_and_row_deltas(self, store):
        _two_runs(store)
        result = compare_runs(store, 'r1', 'r2')
        summary = {row['node_id']: row for row in result['nodes']}
        assert summary['node-0']['rows_a'] == 2
        assert summary['node-0']['rows_b'] == 2
        assert summary['node-0']['status_a'] == summary['node-0']['status_b'] == NODE_DONE
        assert summary['node-1']['row_delta'] == 0

    def test_a_different_shape_is_reported_but_common_nodes_still_compare(self, store):
        _two_runs(store)
        _seed(store, 'r3', [('node-0', 'source', [{'id': 9}]), ('node-9', 'output', [])])
        result = compare_runs(store, 'r1', 'r3')
        assert result['same_shape'] is False
        assert [row['node_id'] for row in result['nodes']] == ['node-0']
        assert result['node']['node_id'] == 'node-0'

    def test_missing_runs_and_nodes_are_named(self, store):
        _two_runs(store)
        with pytest.raises(LookupError) as exc:
            compare_runs(store, 'missing', 'r2')
        assert 'missing' in str(exc.value)
        with pytest.raises(LookupError) as exc:
            compare_runs(store, 'r1', 'r2', node_id='node-9')
        assert 'node-9' in str(exc.value)
        with pytest.raises(ValueError):
            compare_runs(store, 'r1', 'r1')

    def test_the_row_cap_is_named(self, store, monkeypatch):
        _two_runs(store)
        monkeypatch.setattr('services.run_compare.MAX_COMPARE_ROWS', 1)
        with pytest.raises(ValueError) as exc:
            compare_runs(store, 'r1', 'r2', node_id='node-0')
        assert 'node-0' in str(exc.value) and '1' in str(exc.value)
