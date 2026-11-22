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


def _codes(params):
    workflow = {'nodes': [{'id': 'v', 'type': 'visualize', 'params': params}], 'connections': []}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'v']


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

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_no_chart_type_is_named(self):
        assert 'engine.visualize_no_chart' in _codes({})

    def test_a_bar_chart_without_x_is_named(self):
        assert 'engine.visualize_no_x' in _codes({'chart_type': 'bar'})

    def test_a_bar_chart_with_x_is_clean(self):
        assert _codes({'chart_type': 'bar', 'x_field': 'word'}) == []

    def test_a_chart_that_needs_no_x_is_not_asked_for_one(self):
        assert NO_X_TYPES, 'the chart registry declares no no-x chart; this guard measures nothing'
        chart = sorted(NO_X_TYPES)[0]
        assert 'engine.visualize_no_x' not in _codes({'chart_type': chart})

    def test_a_chart_specific_required_field_is_named(self):
        assert 'engine.chart_field_missing' in _codes({'chart_type': 'stack_pct', 'x_field': 'word'})
