"""The visualize node's declaration: chart type, fields, and the ChartSpec's own requirements."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import visualize as executor

from engine.workflow import WorkflowEngine
from services.charts.registry import NO_X_TYPES

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _manifest():
    manifest = registry.manifest_for_node('visualize')
    assert manifest is not None
    return manifest


def _entries(params):
    workflow = {'nodes': [{'id': 'v', 'type': 'visualize', 'params': params}], 'connections': []}
    return [entry for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'v']


def _codes(params):
    return [entry['code'] for entry in _entries(params)]


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['visualize']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['visualize'] == manifest.defaults()

    def test_the_hook_handler_and_validator_are_the_executors_own(self):
        manifest = _manifest()
        assert registry.resolve(manifest.ports.read_columns) is executor.read_columns
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node
        assert manifest.preflight == 'nodes.executors.visualize:preflight'
        assert registry.resolve(manifest.preflight) is executor.preflight

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()

    def test_a_blank_chart_type_means_the_manifests_default(self):
        """``DEFAULT_CHART`` is a link to this declaration, not a second opinion: the executor and
        the chart contract pair a blank box with the value a new node starts from."""
        from services.charts.registry import DEFAULT_CHART

        spec = _manifest().param('chart_type')
        assert spec is not None
        assert spec.default == DEFAULT_CHART


class TestValidation:
    def test_a_blank_chart_type_is_the_declared_default(self):
        """A blank box draws the manifest's default (bar), so it is not refused; only a value the
        registry does not serve is."""
        assert 'engine.chart_unknown' not in _codes({})
        assert 'engine.chart_field_missing' in _codes({})

    def test_a_bar_chart_without_x_is_named(self):
        entry = next(
            entry for entry in _entries({'chart_type': 'bar'}) if entry['code'] == 'engine.chart_field_missing'
        )
        assert entry['param'] == 'x_field'

    def test_a_bar_chart_with_x_is_clean(self):
        assert _codes({'chart_type': 'bar', 'x_field': 'word'}) == []

    def test_a_chart_that_needs_no_x_is_not_asked_for_one(self):
        assert NO_X_TYPES, 'the chart registry declares no no-x chart; this guard measures nothing'
        chart = sorted(NO_X_TYPES)[0]
        assert 'engine.chart_field_missing' not in _codes({'chart_type': chart})

    def test_a_chart_specific_required_field_is_named(self):
        entries = [entry for entry in _entries({'chart_type': 'stack_pct', 'x_field': 'word'})]
        missing = [entry for entry in entries if entry['code'] == 'engine.chart_field_missing']
        assert [entry['param'] for entry in missing] == ['stack_fields']

    def test_an_off_list_chart_type_is_named_with_the_default_as_its_fix(self):
        entries = _entries({'chart_type': 'moonbase'})
        unknown = [entry for entry in entries if entry['code'] == 'engine.chart_unknown']
        assert unknown and unknown[0]['fix'] == {'set': {'chart_type': 'bar'}}

    def test_a_renamed_column_is_named_by_the_data_contract(self):
        """The engine stays pure (no database): the caller hands it each node's table shape.
        Without evidence the chart is not judged; with the upstream's shape the rename is named."""
        workflow = {
            'nodes': [
                {'id': 'p', 'type': 'upload', 'params': {'dataset_id': 'd1'}},
                {'id': 'v', 'type': 'visualize', 'params': {'chart_type': 'bar', 'x_field': '词'}},
            ],
            'connections': [{'from': 'p', 'to': 'v'}],
        }
        engine = WorkflowEngine(workflow)
        assert 'engine.missing_column' not in [entry['code'] for entry in engine.validate_detailed()]
        entries = engine.validate_detailed(columns={'p': ['X']})
        missing = [entry for entry in entries if entry['code'] == 'engine.missing_column']
        assert missing and missing[0]['id'] == 'v'
        assert '词' in missing[0]['message']

    def test_a_sample_with_a_text_value_column_is_named(self):
        workflow = {
            'nodes': [
                {
                    'id': 'v',
                    'type': 'visualize',
                    'params': {'chart_type': 'bar', 'x_field': 'X', 'y_field': 'Y'},
                }
            ],
            'connections': [],
        }
        entries = WorkflowEngine(workflow).validate_detailed(samples={'v': [{'X': '甲', 'Y': '很高'}]})
        named = [entry for entry in entries if entry['code'] == 'engine.chart_column_not_numeric']
        assert named and named[0]['param'] == 'y_field'
