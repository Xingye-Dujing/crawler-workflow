"""The upload node's declaration: a dataset id is required, and its columns come from the store."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import upload as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _manifest():
    manifest = registry.manifest_for_node('upload')
    assert manifest is not None
    return manifest


def _codes(params):
    workflow = {'nodes': [{'id': 'u', 'type': 'upload', 'params': params}], 'connections': []}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'u']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['upload']
        assert (plugin.label_key, plugin.category, plugin.rows, plugin.quiet) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
            manifest.execution.quiet,
        )
        assert NODE_DEFAULTS['upload'] == manifest.defaults()

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
    def test_a_missing_dataset_is_refused_before_the_run(self):
        assert _codes({}) == ['engine.upload_no_file']

    def test_a_bound_dataset_is_clean(self):
        assert _codes({'dataset_id': 'ds_1'}) == []

    def test_a_blank_id_is_missing_not_configured(self):
        assert _codes({'dataset_id': '   '}) == ['engine.upload_no_file']

    def test_the_emit_hook_answers_unknown_without_a_dataset(self):
        assert executor.emit_columns({'id': 'u', 'type': 'upload', 'params': {}}, None) is None
