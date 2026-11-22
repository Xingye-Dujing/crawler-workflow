"""The accumulate node's declaration: one table parent, a name, and an identity mode."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import accumulate as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
UPLOAD = {'id': 'u', 'type': 'upload', 'params': {'dataset_id': 'ds_1'}}


def _manifest():
    manifest = registry.manifest_for_node('accumulate')
    assert manifest is not None
    return manifest


def _codes(params, parents=(UPLOAD,), extra_nodes=()):
    node = {'id': 'a', 'type': 'accumulate', 'params': params}
    workflow = {'nodes': [node, *parents, *extra_nodes], 'connections': [{'from': p['id'], 'to': 'a'} for p in parents]}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'a']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['accumulate']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['accumulate'] == manifest.defaults()

    def test_the_hook_handler_and_validator_are_the_executors_own(self):
        manifest = _manifest()
        assert registry.resolve(manifest.ports.emit_columns) is executor.emit_columns
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_a_blank_name_is_named(self):
        assert 'engine.accumulate_no_name' in _codes({'identity': 'row'})

    def test_a_bad_identity_is_named(self):
        assert 'engine.accumulate_bad_identity' in _codes({'lineage_name': '评论', 'identity': 'moon'})

    def test_column_mode_needs_keys(self):
        assert 'engine.accumulate_no_keys' in _codes({'lineage_name': '评论', 'identity': 'columns'})

    def test_column_mode_with_keys_is_clean(self):
        assert _codes({'lineage_name': '评论', 'identity': 'columns', 'key_columns': '链接'}) == []

    def test_no_parent_is_named(self):
        assert 'engine.accumulate_one_parent' in _codes({'lineage_name': '评论'}, parents=())

    def test_two_parents_are_named(self):
        second = {'id': 'u2', 'type': 'upload', 'params': {'dataset_id': 'ds_2'}}
        assert 'engine.accumulate_one_parent' in _codes({'lineage_name': '评论'}, parents=(UPLOAD, second))

    def test_a_non_table_parent_is_named(self):
        name = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '采集'}}
        assert 'engine.accumulate_bad_parent' in _codes({'lineage_name': '评论'}, parents=(name,))
