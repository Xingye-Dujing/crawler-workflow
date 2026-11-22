"""The biblio node's declaration: 56 parameters, one option list each, and one table parent.

The point of this contract is the DERIVATION: ``services.biblio.schema`` no longer keeps its own
``DEFAULTS``/option tuples — they are read from the manifest, so a parameter added here reaches the
validator, the served catalogue and the run without a second edit. The cases below pin that the
derivation really happened (not that the two copies agree) and that the validator still refuses
what the engine used to refuse.
"""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import biblio as executor

from engine.workflow import WorkflowEngine
from services.biblio import schema

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
UPLOAD = {'id': 'u', 'type': 'upload', 'params': {'dataset_id': 'ds_1'}}
NAME = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '采集'}}


def _manifest():
    manifest = registry.manifest_for_node('biblio')
    assert manifest is not None
    return manifest


def _codes(params, parents=(UPLOAD,)):
    node = {'id': 'b', 'type': 'biblio', 'params': params}
    workflow = {'nodes': [node, *parents], 'connections': [{'from': p['id'], 'to': 'b'} for p in parents]}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'b']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['biblio']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['biblio'] == manifest.defaults()

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


class TestTheSchemaIsDerived:
    def test_the_defaults_are_the_manifest_defaults(self):
        assert _manifest().defaults() == schema.DEFAULTS
        assert len(schema.DEFAULTS) == 56

    def test_every_option_tuple_is_its_parameter_enum(self):
        pairs = {
            'entity_type': schema.ENTITY_TYPES,
            'output_shape': schema.OUTPUT_SHAPES,
            'selection': schema.SELECTION_MODES,
            'link_measure': schema.LINK_MEASURES,
            'counting': schema.COUNTING_MODES,
            'pruning': schema.PRUNING_MODES,
            'pruning_scope': schema.PRUNING_SCOPES,
            'pathfinder_r': schema.PATHFINDER_R,
            'label_method': schema.LABEL_METHODS,
            'label_source': schema.LABEL_SOURCES,
        }
        for param, options in pairs.items():
            assert options == tuple(_manifest().param(param).enum), param

    def test_every_range_check_names_a_declared_parameter(self):
        names = {spec.name for spec in _manifest().params}
        assert {item[0] for item in schema.RANGE_CHECKS} <= names
        assert {item[0] for item in schema.OPTION_CHECKS} <= names

    def test_the_problems_are_data_and_the_errors_are_the_same_facts(self):
        params = {'entity_type': 'moonbase'}
        problems = schema.collect_problems(params)
        assert [problem['code'] for problem in problems] == ['biblio.bad_option']
        assert problems[0]['context']['param'] == 'entity_type'
        assert schema.collect_errors(params, '计量 #b')[0].startswith('计量 #b')


class TestValidation:
    def test_no_input_is_named(self):
        assert _codes({}, parents=()) == ['engine.biblio_no_input']

    def test_two_parents_are_named(self):
        second = {'id': 'u2', 'type': 'upload', 'params': {'dataset_id': 'ds_2'}}
        assert 'engine.biblio_multi_input' in _codes({}, parents=(UPLOAD, second))

    def test_a_name_node_counts_as_a_wire(self):
        codes = _codes({}, parents=(UPLOAD, NAME))
        assert 'engine.biblio_multi_input' in codes

    def test_defaults_are_clean(self):
        assert _codes({}) == []

    def test_an_unknown_entity_is_named(self):
        assert _codes({'entity_type': 'moonbase'}) == ['biblio.bad_option']

    def test_a_number_out_of_range_is_named(self):
        assert 'biblio.bad_option' in _codes({'top_n': 0})

    def test_an_inverted_year_range_is_named(self):
        assert 'biblio.time_range' in _codes({'time_start': '2024', 'time_end': '2015'})

    def test_a_bad_year_is_named(self):
        assert 'biblio.bad_option' in _codes({'time_start': 'yesterday'})

    def test_fractional_counting_on_a_coupling_network_is_named(self):
        assert 'biblio.counting_no_coupling' in _codes(
            {'entity_type': 'document', 'counting': 'fractional', 'burst': False},
        )

    def test_bursts_on_a_coupling_network_are_named(self):
        assert 'biblio.coupling_no_burst' in _codes({'entity_type': 'document', 'burst': True})

    def test_a_shape_without_its_switch_is_named(self):
        assert 'biblio.shape_needs_cluster' in _codes({'output_shape': 'clusters', 'cluster': False})
        assert 'biblio.shape_needs_variation' in _codes({'output_shape': 'variation'})
        assert 'biblio.dual_map_needs_basemap' in _codes({'output_shape': 'dual_map'})

    def test_a_watch_without_a_project_is_named(self):
        assert 'biblio.watch_needs_project' in _codes({'watch_label': '十月'})

    def test_watching_a_non_entity_shape_is_named(self):
        assert 'biblio.watch_needs_entity_table' in _codes(
            {'watch_project': 'p', 'output_shape': 'variation', 'variation': True},
        )

    def test_cluster_labels_without_clustering_are_named(self):
        assert 'biblio.cluster_labels_need_cluster' in _codes({'cluster': False, 'cluster_labels': 'A=甲'})
