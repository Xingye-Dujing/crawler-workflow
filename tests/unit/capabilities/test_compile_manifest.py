"""The compile node's declaration: every parent must be a visualize that emits LaTeX."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import compile as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
UPLOAD = {'id': 'u', 'type': 'upload', 'params': {'dataset_id': 'ds_1'}}


def _manifest():
    manifest = registry.manifest_for_node('compile')
    assert manifest is not None
    return manifest


def _visualize(node_id, latex=True, table=True):
    return {
        'id': node_id,
        'type': 'visualize',
        'params': {
            'chart_type': 'bar',
            'x_field': 'word',
            'emit_latex': latex,
            'emit_latex_table': table,
        },
    }


def _codes(node, parents):
    workflow = {'nodes': [node, *parents], 'connections': [{'from': p['id'], 'to': 'c'} for p in parents]}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'c']


def _compile(**params):
    return {'id': 'c', 'type': 'compile', 'params': params}


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['compile']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['compile'] == manifest.defaults() == {}

    def test_the_validator_and_handler_are_the_executors_own(self):
        manifest = _manifest()
        assert manifest.validators == ('nodes.executors.compile:validate_node',)
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_no_parent_is_named(self):
        assert _codes(_compile(), []) == ['engine.compile_no_upstream']

    def test_a_non_visualize_parent_is_named(self):
        assert 'engine.compile_bad_parent' in _codes(_compile(), [dict(UPLOAD)])

    def test_a_both_off_visualize_is_named(self):
        assert 'engine.compile_source_both_off' in _codes(_compile(), [_visualize('v', latex=False, table=False)])

    def test_a_visualize_with_one_box_on_is_clean(self):
        assert _codes(_compile(), [_visualize('v', latex=True, table=False)]) == []
