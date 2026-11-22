"""The name node's declaration: metadata only, refused when it labels nothing."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import name as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
UPLOAD = {'id': 'u', 'type': 'upload', 'params': {'dataset_id': 'ds_1'}}
PROCESS = {'id': 'p', 'type': 'process', 'params': {'operation': 'clean', 'text_column': '正文'}}


def _manifest():
    manifest = registry.manifest_for_node('name')
    assert manifest is not None
    return manifest


def _codes(name_node, connections):
    workflow = {'nodes': [name_node, dict(UPLOAD), dict(PROCESS)], 'connections': connections}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'n']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['name']
        assert (plugin.label_key, plugin.category, plugin.rows, plugin.quiet) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
            manifest.execution.quiet,
        )
        assert NODE_DEFAULTS['name'] == manifest.defaults()

    def test_the_hook_and_handler_are_the_executors_own(self):
        manifest = _manifest()
        assert registry.resolve(manifest.ports.emit_columns) is executor.emit_columns
        assert registry.resolve(manifest.execution.handler) is executor.run

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_a_blank_name_is_named(self):
        node = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '  '}}
        assert 'engine.name_no_label' in _codes(node, [{'from': 'n', 'to': 'u'}])

    def test_an_incoming_wire_is_refused(self):
        node = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '采集'}}
        codes = _codes(node, [{'from': 'u', 'to': 'n'}, {'from': 'n', 'to': 'x'}])
        assert 'engine.name_not_head' in codes

    def test_no_downstream_is_refused(self):
        node = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '采集'}}
        assert _codes(node, []) == ['engine.name_no_downstream']

    def test_a_head_label_with_a_downstream_is_clean(self):
        node = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '采集'}}
        assert _codes(node, [{'from': 'n', 'to': 'u'}]) == []
