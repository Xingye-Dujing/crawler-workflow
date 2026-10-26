"""Cumulative datasets: versioned appends, explicit identity, and the workflow node."""

import pandas as pd
import pytest
from nodes.executors.accumulate import execute_accumulate_node

from config import Config
from engine.workflow import WorkflowEngine
from services.dataset_store import DatasetStore


@pytest.fixture()
def store(tmp_path):
    instance = DatasetStore(str(tmp_path / 'datasets.db'))
    yield instance
    instance.close()


def _rows(*rows):
    return pd.DataFrame(list(rows), columns=['id', 'value'])


class TestAppendLineage:
    def test_the_first_append_creates_version_one_and_the_second_appends(self, store):
        first = store.append_lineage('微博累积', _rows({'id': 1, 'value': 'a'}, {'id': 2, 'value': 'b'}))
        assert first['changed'] is True
        assert first['added'] == 2 and first['rows'] == 2
        assert first['lineage']['version'] == 1
        assert store.lineage('微博累积')['rows'] == 2

        second = store.append_lineage(
            '微博累积',
            _rows({'id': 2, 'value': 'b'}, {'id': 3, 'value': 'c'}),
        )
        assert second['changed'] is True
        assert second['added'] == 1 and second['rows'] == 3
        assert second['lineage']['version'] == 2
        assert store.get(second['lineage']['current_dataset_id'])['id'].tolist() == [1, 2, 3]
        assert [row['version'] for row in store.lineage_history('微博累积')] == [2, 1]

    def test_a_rerun_with_no_new_rows_does_not_create_a_version(self, store):
        frame = _rows({'id': 1, 'value': 'a'})
        first = store.append_lineage('微博累积', frame)
        again = store.append_lineage('微博累积', frame.copy())
        assert again['changed'] is False
        assert again['added'] == 0
        assert again['lineage']['version'] == first['lineage']['version']
        assert len(store.lineage_history('微博累积')) == 1

    def test_named_columns_keep_the_existing_row_and_add_only_new_keys(self, store):
        store.append_lineage('微博累积', _rows({'id': 1, 'value': 'a'}))
        result = store.append_lineage(
            '微博累积',
            _rows({'id': 1, 'value': 'UPDATED'}, {'id': 2, 'value': 'b'}),
            identity='columns',
            key_columns=['id'],
        )
        assert result['added'] == 1
        current = store.get(result['lineage']['current_dataset_id'])
        assert current.to_dict('records') == [
            {'id': 1, 'value': 'a'},
            {'id': 2, 'value': 'b'},
        ]

    def test_a_schema_change_missing_key_or_missing_column_is_refused(self, store):
        store.append_lineage('微博累积', _rows({'id': 1, 'value': 'a'}))
        with pytest.raises(ValueError) as exc:
            store.append_lineage('微博累积', pd.DataFrame([{'id': 2, 'extra': 1}]))
        assert 'extra' in str(exc.value) and 'value' in str(exc.value)
        with pytest.raises(ValueError):
            store.append_lineage('微博累积', _rows({'id': 2, 'value': 'b'}), identity='columns')
        with pytest.raises(ValueError):
            store.append_lineage(
                '微博累积', _rows({'id': 2, 'value': 'b'}), identity='columns', key_columns=['missing']
            )
        with pytest.raises(ValueError):
            store.append_lineage('微博累积', _rows({'id': 2, 'value': 'b'}), identity='sideways')

    def test_the_total_row_cap_is_named(self, store, monkeypatch):
        store.append_lineage('微博累积', _rows({'id': 1, 'value': 'a'}))
        monkeypatch.setattr(Config, 'DATASET_MAX_ROWS', 1)
        with pytest.raises(ValueError) as exc:
            store.append_lineage('微博累积', _rows({'id': 2, 'value': 'b'}))
        assert '1' in str(exc.value)

    def test_reset_forgets_the_lineage_but_keeps_the_dataset(self, store):
        first = store.append_lineage('微博累积', _rows({'id': 1, 'value': 'a'}))
        dataset_id = first['lineage']['current_dataset_id']
        assert store.reset_lineage('微博累积') is True
        assert store.lineage('微博累积') is None
        assert store.get(dataset_id) is not None

    def test_purge_keeps_lineage_versions(self, store, monkeypatch):
        first = store.append_lineage('微博累积', _rows({'id': 1, 'value': 'a'}))
        monkeypatch.setattr(Config, 'DATASET_KEEP_DAYS', -1)
        store.purge_unreferenced()
        assert store.get(first['lineage']['current_dataset_id']) is not None

    def test_clear_removes_lineages_too(self, store):
        store.append_lineage('微博累积', _rows({'id': 1, 'value': 'a'}))
        store.clear()
        assert store.list_lineages() == []


class TestAccumulateNode:
    def test_the_node_appends_and_returns_the_full_table(self, store, monkeypatch):
        logs = []
        monkeypatch.setattr('nodes.executors.accumulate.get_dataset_store', lambda: store)
        monkeypatch.setattr('nodes.executors.accumulate.add_log', logs.append)
        node = {
            'id': 'node-7',
            'type': 'accumulate',
            'params': {'lineage_name': '微博累积', 'identity': 'row', 'key_columns': ''},
        }
        first = execute_accumulate_node(node, [{'id': 1, 'value': 'a'}], {'run_id': 'r1'})
        second = execute_accumulate_node(node, [{'id': 1, 'value': 'a'}, {'id': 2, 'value': 'b'}], {'run_id': 'r2'})
        assert first == [{'id': 1, 'value': 'a'}]
        assert second == [{'id': 1, 'value': 'a'}, {'id': 2, 'value': 'b'}]
        assert logs and '微博累积' in logs[-1]
        assert store.lineage_history('微博累积')[0]['run_id'] == 'r2'

    def test_the_node_uses_named_key_columns(self, store, monkeypatch):
        monkeypatch.setattr('nodes.executors.accumulate.get_dataset_store', lambda: store)
        monkeypatch.setattr('nodes.executors.accumulate.add_log', lambda _line: None)
        node = {
            'id': 'node-7',
            'type': 'accumulate',
            'params': {'lineage_name': '微博累积', 'identity': 'columns', 'key_columns': 'id, 平台'},
        }
        execute_accumulate_node(node, [{'id': 1, '平台': 'weibo', 'value': 'a'}], {'run_id': 'r1'})
        rows = execute_accumulate_node(
            node,
            [{'id': 1, '平台': 'weibo', 'value': 'UPDATED'}, {'id': 2, '平台': 'weibo', 'value': 'b'}],
            {'run_id': 'r2'},
        )
        assert rows == [
            {'id': 1, '平台': 'weibo', 'value': 'a'},
            {'id': 2, '平台': 'weibo', 'value': 'b'},
        ]


class TestValidation:
    @staticmethod
    def _wf(accumulate_params, parents=('node-0',)):
        nodes = [
            {'id': 'node-0', 'type': 'upload', 'params': {'dataset_id': 'd1'}},
            {
                'id': 'node-1',
                'type': 'accumulate',
                'params': {'lineage_name': '累积', 'identity': 'row', 'key_columns': ''},
            },
        ]
        conns = [] if len(parents) == 0 else [{'from': parent, 'to': 'node-1'} for parent in parents]
        nodes[1]['params'].update(accumulate_params)
        return {'nodes': nodes, 'connections': conns}

    def test_a_valid_accumulate_node_has_no_errors(self):
        assert WorkflowEngine(self._wf({})).validate() == []

    def test_missing_name_and_bad_identity_are_named(self):
        errors = WorkflowEngine(self._wf({'lineage_name': ''})).validate()
        assert errors, 'a cumulative node with no name must be refused'
        errors = WorkflowEngine(self._wf({'identity': 'sideways'})).validate()
        assert errors, 'an unknown duplicate policy must be refused'

    def test_it_needs_exactly_one_table_parent(self):
        errors = WorkflowEngine(self._wf({}, parents=())).validate()
        assert errors
        errors = WorkflowEngine(self._wf({}, parents=('node-0', 'node-0'))).validate()
        assert errors
