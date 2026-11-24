"""Content identity: what a node produced, and the line a child's reuse may not cross.

``core.asset.DataAsset`` is the contract, ``services/runs/store/assets.py`` persists it, and
``engine/run/asset.py`` fills it from a run. The two behaviours worth pinning are the ones a
fingerprint cannot answer: a child whose parent's content changed must NOT be restored, and a
lineage that is merely unknown must not be treated as a mismatch — an older run, a parent that
produced nothing and a link to another record all stay on the structural rule.
"""

import pytest
from core.asset import DataAsset, artifact_digest, rows_digest

from engine.run.asset import lineage_conflict, record_asset
from services.runs.store import RunStore

pytestmark = pytest.mark.unit

#: The DataAsset half of a stored record, by name — `record_asset` adds `run_id`/`node_id`/`input_sha`
#: and the store's column names, which are not the contract's.
_ASSET_FIELDS = ('id', 'kind', 'owner', 'origin', 'sha256', 'size', 'uri', 'parents', 'meta', 'created_at')


@pytest.fixture
def store(tmp_path):
    s = RunStore(str(tmp_path / 'runs.db'))
    yield s
    s.close()


def _run(store, rid='r1'):
    store.start_run(rid, 'demo', 'fp-canvas', mode='serial', headless=True, llm={}, lang='zh', node_total=2)
    return {'store': store, 'run_id': rid}


def _asset(store, ctx, nid, rows, upstream=()):
    return record_asset(store, ctx, {'id': nid, 'type': 'upload'}, nid, rows, list(upstream))


class TestTheDigest:
    def test_it_does_not_depend_on_key_order(self):
        left = [{'a': 1, 'b': 2}]
        right = [{'b': 2, 'a': 1}]
        assert rows_digest(left) == rows_digest(right)

    def test_different_content_is_a_different_digest(self):
        assert rows_digest([{'a': 1}])[0] != rows_digest([{'a': 2}])[0]

    def test_row_order_is_content(self):
        """A table's order is part of what the user sees, so it is part of the identity."""
        assert rows_digest([{'a': 1}, {'a': 2}])[0] != rows_digest([{'a': 2}, {'a': 1}])[0]

    def test_a_dict_product_has_an_identity_too(self):
        assert artifact_digest({'latex': 'x'})[0] != artifact_digest({'latex': 'y'})[0]


class TestRecordingOneNode:
    def test_it_writes_a_valid_asset_row(self, store):
        ctx = _run(store)
        record = _asset(store, ctx, 'node-1', [{'X': 1}])
        # `record_asset` answers `DataAsset.to_dict()` plus the two store columns, so the asset half
        # must still satisfy the contract it was built from.
        assert DataAsset.from_dict({name: record[name] for name in _ASSET_FIELDS}).id == record['id']
        stored = store.asset_for('r1', 'node-1')
        assert stored['sha256'] == record['sha256']
        assert stored['kind'] == 'table'
        assert stored['origin'] == 'run:r1:node-1'
        assert stored['owner'] == 'local', 'a login-free run is owned by "local", never by a blank'
        assert stored['meta_json'] and '"rows": 1' in stored['meta_json']

    def test_a_parent_is_named_and_its_hash_becomes_the_input(self, store):
        ctx = _run(store)
        parent = _asset(store, ctx, 'node-1', [{'X': 1}])
        child = _asset(store, ctx, 'node-2', [{'Y': 2}], upstream=[('node-1', [{'X': 1}])])
        assert child['parents'] == [parent['id']]
        assert child['input_sha'] == store.input_sha_for('r1', ['node-1'])

    def test_an_empty_result_has_no_asset(self, store):
        ctx = _run(store)
        assert _asset(store, ctx, 'node-1', []) is None
        assert store.asset_for('r1', 'node-1') is None

    def test_an_error_dict_is_not_content(self, store):
        ctx = _run(store)
        assert record_asset(store, ctx, {'id': 'node-1', 'type': 'output'}, 'node-1', {'error': 'no file'}, []) is None


class TestTheLineageRule:
    def test_unknown_lineage_keeps_reuse(self, store):
        assert lineage_conflict(store, 'r1', 'node-2', [('node-1', [])]) is False

    def test_the_same_content_keeps_reuse(self, store):
        ctx = _run(store)
        _asset(store, ctx, 'node-1', [{'X': 1}])
        _asset(store, ctx, 'node-2', [{'Y': 2}], upstream=[('node-1', [{'X': 1}])])
        assert lineage_conflict(store, 'r1', 'node-2', [('node-1', [{'X': 1}])]) is False

    def test_a_parent_whose_content_changed_refuses_reuse(self, store):
        ctx = _run(store)
        _asset(store, ctx, 'node-1', [{'X': 1}])
        _asset(store, ctx, 'node-2', [{'Y': 2}], upstream=[('node-1', [{'X': 1}])])
        # The parent re-ran and produced a different table under the SAME fingerprint.
        _asset(store, ctx, 'node-1', [{'X': 9}])
        assert lineage_conflict(store, 'r1', 'node-2', [('node-1', [{'X': 9}])]) is True

    def test_a_rewired_canvas_is_a_different_input(self, store):
        ctx = _run(store)
        _asset(store, ctx, 'node-1', [{'X': 1}])
        _asset(store, ctx, 'node-9', [{'X': 1}])
        _asset(store, ctx, 'node-2', [{'Y': 2}], upstream=[('node-1', [{'X': 1}])])
        # Same rows, different parent: the child was computed from another table's provenance.
        assert lineage_conflict(store, 'r1', 'node-2', [('node-9', [{'X': 1}])]) is True

    def test_an_older_run_without_a_lineage_is_not_refused(self, store):
        ctx = _run(store)
        record = _asset(store, ctx, 'node-2', [{'Y': 2}])
        store.put_asset({**record, 'input_sha': ''})
        assert lineage_conflict(store, 'r1', 'node-2', [('node-1', [])]) is False


class TestAssetsFollowTheRows:
    def test_a_rerun_drops_the_nodes_assets(self, store):
        ctx = _run(store)
        _asset(store, ctx, 'node-1', [{'X': 1}])
        store.invalidate_nodes('r1', ['node-1'])
        assert store.asset_for('r1', 'node-1') is None

    def test_an_edited_node_drops_its_asset_with_its_rows(self, store):
        ctx = _run(store)
        _asset(store, ctx, 'node-1', [{'X': 1}])
        store.begin_node('r1', 'node-1', 'upload', fingerprint='fp-old')
        store.finish_node('r1', 'node-1', 'done')
        store.begin_node('r1', 'node-1', 'upload', fingerprint='fp-new')
        assert store.asset_for('r1', 'node-1') is None

    def test_deleting_a_run_deletes_its_assets(self, store):
        ctx = _run(store)
        _asset(store, ctx, 'node-1', [{'X': 1}])
        store.delete_run('r1')
        assert store.asset_for('r1', 'node-1') is None

    def test_dropping_a_whole_run_answers_how_many_went(self, store):
        ctx = _run(store)
        _asset(store, ctx, 'node-1', [{'X': 1}])
        _asset(store, ctx, 'node-2', [{'Y': 2}], upstream=[('node-1', [{'X': 1}])])
        assert store.drop_assets('r1') == 2
        assert store.asset_for('r1', 'node-1') is None


class TestTheSettlementReadsTheLineage:
    """The gate as ``run_node_durable`` applies it: a real store, a stubbed executor."""

    @pytest.fixture
    def harness(self, store, monkeypatch):
        from engine.run import node as node_module

        monkeypatch.setattr(node_module, 'add_log', lambda *_a, **_k: None)
        calls = []

        def fake_execute(node, *_a, **_k):
            calls.append(node['id'])
            return [{'out': len(calls)}]

        monkeypatch.setattr(node_module, 'execute_node', fake_execute)

        def attempt(resume: bool, upstream_rows, label='first'):
            ctx = {
                'store': store,
                'run_id': 'r1',
                'resume': resume,
                'fingerprints': {'node-2': 'fp-child'},
                'statuses': store.node_statuses('r1'),
                'open_records': [],
            }
            return node_module.run_node_durable(
                ctx,
                {'id': 'node-2', 'type': 'process'},
                True,
                [],
                [('node-1', upstream_rows)],
                0,
            )

        _run(store)
        return attempt, calls, store

    def test_the_first_attempt_runs_and_records_its_asset(self, harness):
        attempt, calls, _store = harness
        rows, status = attempt(resume=False, upstream_rows=[{'X': 1}])
        assert calls == ['node-2'] and status == 'done'
        assert rows == [{'out': 1}]
        assert _store.asset_for('r1', 'node-2') is not None

    def test_a_resume_restores_the_child_when_the_parent_is_unchanged(self, harness):
        attempt, calls, store = harness
        _asset(store, {'run_id': 'r1'}, 'node-1', [{'X': 1}])
        attempt(resume=False, upstream_rows=[{'X': 1}])
        rows, status = attempt(resume=True, upstream_rows=[{'X': 1}])
        assert status == 'restored'
        assert rows == [{'out': 1}], 'the stored rows came back without a second execution'
        assert calls == ['node-2'], 'a 继续 re-executed a node whose input had not changed'

    def test_a_resume_re_executes_the_child_when_the_parent_changed(self, harness):
        attempt, calls, store = harness
        _asset(store, {'run_id': 'r1'}, 'node-1', [{'X': 1}])
        attempt(resume=False, upstream_rows=[{'X': 1}])
        # The parent re-crawled and produced a different table under the same fingerprint.
        _asset(store, {'run_id': 'r1'}, 'node-1', [{'X': 9}])
        rows, status = attempt(resume=True, upstream_rows=[{'X': 9}])
        assert status == 'done'
        assert calls == ['node-2', 'node-2'], 'a 继续 restored rows computed from a table that no longer exists'
        assert rows == [{'out': 2}]
