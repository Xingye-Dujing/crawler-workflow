"""The fuse node's declaration: several parents, one canonical table, at least one entity role."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import fuse as executor

from engine.workflow import WorkflowEngine
from services.biblio import fuse as service

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
UPLOAD = {'id': 'u', 'type': 'upload', 'params': {'dataset_id': 'ds_1'}}


def _manifest():
    manifest = registry.manifest_for_node('fuse')
    assert manifest is not None
    return manifest


def _codes(params, parents=(UPLOAD,)):
    node = {'id': 'f', 'type': 'fuse', 'params': params}
    workflow = {'nodes': [node, *parents], 'connections': [{'from': p['id'], 'to': 'f'} for p in parents]}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'f']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['fuse']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['fuse'] == manifest.defaults()

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
    def test_no_input_is_named(self):
        assert _codes({}, parents=()) == ['fuse.no_input']

    def test_no_entity_candidate_is_named(self):
        assert _codes({'entity_columns': ''}) == ['fuse.needs_entity']

    def test_the_default_entity_role_is_enough(self):
        assert _codes({}) == []

    def test_the_service_answers_the_same_check_as_data(self):
        assert service.collect_problems({'entity_columns': ''})[0]['code'] == 'fuse.needs_entity'
