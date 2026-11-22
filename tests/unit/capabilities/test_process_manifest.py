"""The process node's declaration: one operation, its column, and the analyzer-specific checks."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import process as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _manifest():
    manifest = registry.manifest_for_node('process')
    assert manifest is not None
    return manifest


def _codes(params, operation=None):
    node = {'id': 'p', 'type': 'process', 'params': params}
    if operation is not None:
        node['operation'] = operation
    workflow = {'nodes': [node], 'connections': []}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'p']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['process']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['process'] == manifest.defaults()

    def test_the_hooks_handler_and_validator_are_the_executors_own(self):
        manifest = _manifest()
        assert registry.resolve(manifest.ports.emit_columns) is executor.emit_columns
        assert registry.resolve(manifest.ports.read_columns) is executor.read_columns
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_no_operation_is_named(self):
        assert _codes({}) == ['engine.process_no_op']

    def test_an_operation_in_params_is_accepted(self):
        assert _codes({'operation': 'clean', 'text_column': '正文'}) == []

    def test_an_operation_on_the_node_is_accepted(self):
        assert _codes({'text_column': '正文'}, operation='clean') == []

    def test_tokenize_without_a_column_is_named(self):
        assert _codes({'operation': 'tokenize'}) == ['engine.tokenize_no_column']

    def test_tokenize_with_a_column_is_clean(self):
        assert _codes({'operation': 'tokenize', 'text_column': '正文'}) == []
