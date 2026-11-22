"""The verify node's declaration: exactly two data tables and the key columns it compares."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import verify as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
LIST = {'id': 'l', 'type': 'upload', 'params': {'dataset_id': 'ds_list'}}
RESULT = {'id': 'r', 'type': 'upload', 'params': {'dataset_id': 'ds_result'}}


def _manifest():
    manifest = registry.manifest_for_node('verify')
    assert manifest is not None
    return manifest


def _codes(params, parents=(LIST, RESULT)):
    node = {'id': 'v', 'type': 'verify', 'params': params}
    workflow = {'nodes': [node, *parents], 'connections': [{'from': p['id'], 'to': 'v'} for p in parents]}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'v']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['verify']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['verify'] == manifest.defaults()

    def test_the_hook_handler_and_validator_are_the_executors_own(self):
        manifest = _manifest()
        assert registry.resolve(manifest.ports.read_columns) is executor.read_columns
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_two_data_parents_and_keys_are_clean(self):
        assert _codes({'input_key_column': '链接', 'result_key_column': '文章URL'}) == []

    def test_one_parent_is_named(self):
        assert 'engine.verify_two_inputs' in _codes(
            {'input_key_column': '链接', 'result_key_column': '文章URL'},
            parents=(LIST,),
        )

    def test_a_name_parent_does_not_count_as_a_table(self):
        name = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '采集'}}
        assert 'engine.verify_two_inputs' not in _codes(
            {'input_key_column': '链接', 'result_key_column': '文章URL'},
            parents=(LIST, RESULT, name),
        )

    def test_the_list_key_is_required(self):
        assert 'engine.verify_need_list_col' in _codes({'result_key_column': '文章URL'})

    def test_the_result_key_is_required(self):
        assert 'engine.verify_need_result_col' in _codes({'input_key_column': '链接'})

    def test_the_read_hook_skips_blank_columns(self):
        node = {'id': 'v', 'type': 'verify', 'params': {'input_key_column': '链接', 'result_key_column': ' '}}
        assert executor.read_columns(node) == ['链接']
