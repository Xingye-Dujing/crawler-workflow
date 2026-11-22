"""The analysis node's declaration: a step pipeline, its column hooks, and the no-op refusal."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import analysis as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _manifest():
    manifest = registry.manifest_for_node('analysis')
    assert manifest is not None
    return manifest


def _codes(params):
    workflow = {'nodes': [{'id': 'a', 'type': 'analysis', 'params': params}], 'connections': []}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'a']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['analysis']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['analysis'] == manifest.defaults()

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
    def test_no_steps_and_no_operation_is_named(self):
        assert _codes({}) == ['engine.analysis_no_op']

    def test_steps_are_enough(self):
        assert _codes({'steps': '[{"op": "drop_null", "columns": "正文"}]'}) == []

    def test_an_operation_is_enough(self):
        assert _codes({'operation': 'drop_null'}) == []
