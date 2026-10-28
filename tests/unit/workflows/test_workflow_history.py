"""Canvas history: snapshots persist, restore whole payloads, and keep a per-workflow baseline."""

import json

import pytest

from services.workflows.history import (
    HistoryFullError,
    SnapshotCorruptError,
    WorkflowHistoryStore,
)


def canvas(nodes=2, label=''):
    return {
        'nodes': [
            {'id': f'node-{i}', 'type': 'name', 'title': label or f'N{i}', 'params': {'workflow_name': label}}
            for i in range(nodes)
        ],
        'connections': [{'from': 'node-0', 'to': 'node-1'}] if nodes > 1 else [],
        'settings': {'mode': 'serial', 'view': {'zoom': 1}, 'disabledTypes': []},
    }


@pytest.fixture()
def store(tmp_path):
    instance = WorkflowHistoryStore(str(tmp_path / 'workflow_history.db'))
    yield instance
    instance.close()


class TestSnapshots:
    def test_save_list_get_delete_round_trip(self, store):
        saved = store.save_snapshot(canvas(3), 'before layout', '日报')
        assert saved['nodes'] == 3
        assert saved['connections'] == 1
        assert saved['workflow_name'] == '日报'

        rows = store.list_snapshots()
        assert [row['id'] for row in rows] == [saved['id']]
        assert 'workflow' not in rows[0], 'the list must not carry whole canvases'

        full = store.get_snapshot(saved['id'])
        assert full['label'] == 'before layout'
        assert full['workflow'] == canvas(3)
        assert full['workflow']['settings']['view'] == {'zoom': 1}

        deleted, cleared = store.delete_snapshot(saved['id'])
        assert deleted is True
        assert cleared == []
        assert store.list_snapshots() == []
        assert store.get_snapshot(saved['id']) is None

    def test_a_snapshot_survives_reopening_the_store(self, tmp_path):
        path = str(tmp_path / 'workflow_history.db')
        first = WorkflowHistoryStore(path)
        saved = first.save_snapshot(canvas(2), 'kept', 'wf')
        first.close()
        second = WorkflowHistoryStore(path)
        try:
            assert [row['id'] for row in second.list_snapshots()] == [saved['id']]
            assert second.get_snapshot(saved['id'])['workflow'] == canvas(2)
        finally:
            second.close()

    def test_newest_first_and_same_instant_is_separated_by_insert_order(self, store, monkeypatch):
        monkeypatch.setattr('services.workflows.history._now', lambda: 1000.0)
        older = store.save_snapshot(canvas(1), 'first', 'wf')
        newer = store.save_snapshot(canvas(2), 'second', 'wf')
        assert [row['id'] for row in store.list_snapshots()] == [newer['id'], older['id']]

    def test_a_payload_without_a_node_list_is_refused_by_name(self, store):
        for bad in ({}, [], None, {'nodes': 'nope'}, {'nodes': [], 'connections': 'nope'}):
            with pytest.raises(ValueError) as exc:
                store.save_snapshot(bad)
            assert str(exc.value)
        assert store.counts()['snapshots'] == 0

    def test_an_over_long_label_is_refused_not_truncated(self, store):
        with pytest.raises(ValueError) as exc:
            store.save_snapshot(canvas(1), 'x' * 81)
        assert '80' in str(exc.value)
        assert store.counts()['snapshots'] == 0

    def test_a_full_history_refuses_without_dropping_an_old_snapshot(self, store, monkeypatch):
        monkeypatch.setattr(WorkflowHistoryStore, 'MAX_SNAPSHOTS', 2)
        first = store.save_snapshot(canvas(1), 'one', 'wf')
        second = store.save_snapshot(canvas(1), 'two', 'wf')
        with pytest.raises(HistoryFullError) as exc:
            store.save_snapshot(canvas(1), 'three', 'wf')
        assert '2' in str(exc.value)
        assert [row['id'] for row in store.list_snapshots()] == [second['id'], first['id']]

    def test_a_corrupt_payload_is_reported_with_its_id(self, store):
        saved = store.save_snapshot(canvas(1), 'broken', 'wf')
        store._execute('UPDATE canvas_snapshots SET payload = ? WHERE id = ?', ('{oops', saved['id']))
        with pytest.raises(SnapshotCorruptError) as exc:
            store.get_snapshot(saved['id'])
        assert saved['id'] in str(exc.value)

    def test_deleting_a_baseline_snapshot_clears_the_pointer_and_names_the_workflow(self, store):
        saved = store.save_snapshot(canvas(1), 'base', 'wf')
        store.set_layout('wf', 'baseline', saved['id'])
        deleted, cleared = store.delete_snapshot(saved['id'])
        assert deleted is True
        assert cleared == ['wf']
        layout = store.get_layout('wf')
        assert layout['strategy'] == 'algorithm'
        assert layout['snapshot'] is None

    def test_deleting_an_unknown_snapshot_is_not_an_error(self, store):
        assert store.delete_snapshot('missing') == (False, [])

    def test_rename_changes_only_the_label(self, store):
        saved = store.save_snapshot(canvas(2), 'before layout', '日报')
        renamed = store.rename_snapshot(saved['id'], '  重新排布前  ')
        assert renamed['label'] == '重新排布前'
        assert renamed['created_at'] == saved['created_at']
        assert renamed['nodes'] == saved['nodes']
        full = store.get_snapshot(saved['id'])
        assert full['label'] == '重新排布前'
        assert full['workflow'] == canvas(2)
        assert store.list_snapshots()[0]['label'] == '重新排布前'

    def test_rename_allows_an_empty_label_but_refuses_a_long_one(self, store):
        saved = store.save_snapshot(canvas(1), 'named', 'wf')
        assert store.rename_snapshot(saved['id'], '')['label'] == ''
        with pytest.raises(ValueError) as exc:
            store.rename_snapshot(saved['id'], 'x' * 81)
        assert '80' in str(exc.value)
        assert store.get_snapshot(saved['id'])['label'] == ''

    def test_renaming_a_missing_snapshot_returns_none(self, store):
        assert store.rename_snapshot('missing', 'x') is None


class TestLayoutBaseline:
    def test_a_workflow_without_a_row_uses_the_algorithm(self, store):
        assert store.get_layout('wf') == {
            'workflow_name': 'wf',
            'strategy': 'algorithm',
            'snapshot': None,
            'baseline_missing': False,
        }

    def test_a_baseline_points_at_one_snapshot_and_survives_a_reopen(self, store, tmp_path):
        saved = store.save_snapshot(canvas(2), 'arrangement', '日报')
        layout = store.set_layout('日报', 'baseline', saved['id'])
        assert layout['strategy'] == 'baseline'
        assert layout['snapshot']['id'] == saved['id']
        assert layout['baseline_missing'] is False
        again = store.get_layout('日报')
        assert again == layout

    def test_baselines_are_per_workflow(self, store):
        a = store.save_snapshot(canvas(1), 'A', 'wf-a')
        b = store.save_snapshot(canvas(1), 'B', 'wf-b')
        store.set_layout('wf-a', 'baseline', a['id'])
        store.set_layout('wf-b', 'baseline', b['id'])
        assert store.get_layout('wf-a')['snapshot']['id'] == a['id']
        assert store.get_layout('wf-b')['snapshot']['id'] == b['id']
        store.set_layout('wf-a', 'algorithm')
        assert store.get_layout('wf-a')['strategy'] == 'algorithm'
        assert store.get_layout('wf-b')['strategy'] == 'baseline', 'one workflow must not clear another'

    def test_baseline_requires_an_existing_snapshot(self, store):
        with pytest.raises(ValueError) as exc:
            store.set_layout('wf', 'baseline', 'not-there')
        assert 'not-there' in str(exc.value)
        with pytest.raises(ValueError):
            store.set_layout('wf', 'baseline', '')
        with pytest.raises(ValueError):
            store.set_layout('wf', 'sideways')

    def test_a_layout_without_a_workflow_name_is_refused(self, store):
        with pytest.raises(ValueError) as exc:
            store.set_layout('', 'algorithm')
        assert str(exc.value)

    def test_a_deleted_snapshot_leaves_the_baseline_missing_not_silently_algorithm(self, store):
        saved = store.save_snapshot(canvas(1), 'base', 'wf')
        store.set_layout('wf', 'baseline', saved['id'])
        # Delete behind the store's back so the pointer survives; this is the corruption a
        # manual DB edit or a half-finished migration would leave.
        store._execute('DELETE FROM canvas_snapshots WHERE id = ?', (saved['id'],))
        layout = store.get_layout('wf')
        assert layout['strategy'] == 'baseline'
        assert layout['snapshot'] is None
        assert layout['baseline_missing'] is True

    def test_renaming_a_workflow_moves_its_baseline(self, store):
        saved = store.save_snapshot(canvas(2), 'base', 'old')
        store.set_layout('old', 'baseline', saved['id'])
        store.rename_layout('old', 'new')
        assert store.get_layout('new')['snapshot']['id'] == saved['id']
        assert store.get_layout('old')['strategy'] == 'algorithm'
        assert store.get_layout('old')['snapshot'] is None

    def test_renaming_over_an_existing_target_replaces_that_row(self, store):
        a = store.save_snapshot(canvas(1), 'A', 'old')
        b = store.save_snapshot(canvas(1), 'B', 'new')
        store.set_layout('old', 'baseline', a['id'])
        store.set_layout('new', 'baseline', b['id'])
        store.rename_layout('old', 'new')
        assert store.get_layout('new')['snapshot']['id'] == a['id']
        assert store.get_layout('old')['strategy'] == 'algorithm'

    def test_deleting_a_workflow_drops_its_baseline_but_keeps_the_snapshot(self, store):
        saved = store.save_snapshot(canvas(1), 'base', 'wf')
        store.set_layout('wf', 'baseline', saved['id'])
        store.delete_layout('wf')
        assert store.get_layout('wf')['strategy'] == 'algorithm'
        assert store.get_snapshot(saved['id'])['id'] == saved['id']

    def test_the_payload_is_plain_json_not_a_python_repr(self, store):
        saved = store.save_snapshot({'nodes': [{'id': '节点-1', 'params': {'名称': '中文'}}]}, '中文', '工作流')
        full = store.get_snapshot(saved['id'])
        assert json.dumps(full['workflow'], ensure_ascii=False)
        assert full['workflow']['nodes'][0]['params']['名称'] == '中文'
