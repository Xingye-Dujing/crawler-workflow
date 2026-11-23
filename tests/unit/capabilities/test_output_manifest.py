"""The save node's declaration: two legitimate shapes, both checked before a run."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import output as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _manifest():
    manifest = registry.manifest_for_node('output')
    assert manifest is not None
    return manifest


UPLOAD = {'id': 'u', 'type': 'upload', 'params': {'dataset_id': 'ds_1'}}
NAME = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '采集'}}
COMPILE = {'id': 'c', 'type': 'compile', 'params': {}}
VISUALIZE = {
    'id': 'v',
    'type': 'visualize',
    'params': {'chart_type': 'bar', 'x_field': 'word', 'emit_latex': True, 'emit_latex_table': True},
}


def _codes(node, parents):
    workflow = {'nodes': [node, *parents], 'connections': [{'from': p['id'], 'to': 'o'} for p in parents]}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'o']


def _save(**params):
    node = {'id': 'o', 'type': 'output', 'params': {'operation': 'save', **params}}
    return node


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['output']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['output'] == manifest.defaults()

    def test_the_validator_and_handler_are_the_executors_own(self):
        manifest = _manifest()
        assert manifest.validators == ('nodes.executors.output:validate_node',)
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestTheTableShape:
    def test_no_parent_is_named(self):
        assert _codes(_save(), []) == ['engine.output_no_upstream']

    def test_a_table_parent_is_clean(self):
        assert _codes(_save(), [dict(UPLOAD)]) == []

    def test_a_pdf_parent_in_a_table_save_needs_pdf(self):
        workflow = {
            'nodes': [_save(format='csv'), dict(COMPILE)],
            'connections': [{'from': 'c', 'to': 'o'}],
        }
        entry = next(
            entry
            for entry in WorkflowEngine(workflow).validate_detailed()
            if entry['code'] == 'engine.output_needs_pdf'
        )
        # The parents can only produce a PDF, so the format has one legal value and the entry
        # offers it as a one-click fix instead of making the user hunt the dropdown.
        assert entry['fix'] == {'set': {'format': 'pdf'}}

    def test_a_metadata_parent_is_not_a_table(self):
        assert _codes(_save(format='csv'), [dict(NAME)]) == ['engine.output_no_table']

    def test_a_save_without_an_operation_is_named(self):
        node = {'id': 'o', 'type': 'output', 'params': {'format': 'csv'}}
        assert 'engine.output_no_op' in _codes(node, [dict(UPLOAD)])


class TestThePdfShape:
    def test_a_pdf_save_with_a_table_parent_is_mixed(self):
        assert 'engine.output_pdf_mixed' in _codes(_save(format='pdf'), [dict(UPLOAD)])

    def test_a_pdf_save_without_a_pdfable_parent_is_named(self):
        codes = _codes(_save(format='pdf'), [dict(UPLOAD)])
        assert 'engine.output_pdf_only_pdfable' in codes

    def test_both_pdf_sources_are_refused(self):
        codes = _codes(_save(format='pdf'), [dict(VISUALIZE), dict(COMPILE)])
        assert 'engine.output_pdf_two_sources' in codes

    def test_a_compile_parent_is_clean(self):
        assert _codes(_save(format='pdf'), [dict(COMPILE)]) == []

    def test_a_visualize_parent_is_clean(self):
        assert _codes(_save(format='pdf'), [dict(VISUALIZE)]) == []
