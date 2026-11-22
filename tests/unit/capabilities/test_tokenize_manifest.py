"""The tokenize pilot: one manifest declaration, every server surface reads it.

This file is the proof the P1 pilot promised. The old home of each fact is named in a test, so a
second copy cannot quietly return: the catalogue entry, the seed parameters, the pre-run refusal and
the lineage hooks all answer from ``capabilities_kernel/nodes/tokenize/manifest.py``, and the
executor keeps only the behavior it alone can know.
"""

import json
from pathlib import Path

import pytest
from capabilities_kernel import registry
from capabilities_kernel.manifest import API_VERSION
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import tokenize as executor

from engine.workflow import WorkflowEngine
from services.validation.engine import static_problems

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _manifest():
    manifest = registry.manifest_for_node('tokenize')
    assert manifest is not None, 'the tokenize manifest is not discovered'
    return manifest


def _workflow(params: dict) -> dict:
    return {
        'nodes': [{'id': 't', 'type': 'tokenize', 'title': '分词', 'params': params}],
        'connections': [],
    }


def _codes(workflow: dict) -> list[tuple]:
    return [(entry['id'], entry['code']) for entry in WorkflowEngine(workflow).validate_detailed()]


class TestTheManifestIsWhole:
    def test_every_section_passes_the_structural_check(self):
        assert _manifest().problems() == []

    def test_it_speaks_the_current_api_version(self):
        assert _manifest().api_version == API_VERSION

    def test_the_documented_page_and_contract_test_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file(), manifest.docs.page
        assert manifest.tests.contracts, 'a node needs a contract test'
        for relative in manifest.tests.contracts:
            assert (REPO / relative).is_file(), relative

    def test_the_ai_examples_are_json_the_server_could_receive(self):
        examples = _manifest().ai.examples
        assert examples, 'without an example the AI has to invent a node shape'
        assert json.loads(json.dumps(examples, ensure_ascii=False)) == list(examples)


class TestTheCatalogueReadsTheManifest:
    def test_the_served_entry_is_the_declared_identity(self):
        manifest = _manifest()
        plugin = PLUGINS['tokenize']
        assert plugin.type == manifest.identity.id
        assert plugin.label_key == manifest.identity.title_key
        assert plugin.category == manifest.identity.category
        assert plugin.rows == manifest.ports.rows
        assert plugin.quiet is manifest.execution.quiet

    def test_the_pilot_keeps_its_users_slot(self):
        """The hand-written catalogue had 分词 between 分析 and 文献; a migration may not reshuffle it."""
        assert list(PLUGINS).index('tokenize') == 8
        assert list(PLUGINS)[7:10] == ['analysis', 'tokenize', 'biblio']

    def test_the_seed_parameters_are_the_manifest_defaults(self):
        assert NODE_DEFAULTS['tokenize'] == _manifest().defaults()


class TestValidationRunsTheDeclaredRule:
    def test_a_missing_text_column_is_named_before_a_run(self):
        assert _codes(_workflow({})) == [('t', 'engine.tokenize_no_column')]

    def test_a_configured_column_produces_no_refusal(self):
        assert _codes(_workflow({'text_column': '正文'})) == []

    def test_a_whitespace_only_column_is_missing_not_configured(self):
        assert _codes(_workflow({'text_column': '   '})) == [('t', 'engine.tokenize_no_column')]

    def test_the_rule_is_data_and_survives_a_non_object_params_field(self):
        """A hand-edited node with ``"params": "去重"`` must be refused, not raise AttributeError."""
        problems = static_problems(_manifest(), {'id': 't', 'type': 'tokenize', 'params': '去重'})
        assert [problem['code'] for problem in problems] == ['engine.tokenize_no_column']
        assert problems[0]['severity'] == 'error'


class TestThePortsPointAtTheBehaviourModule:
    def test_the_declared_hooks_are_the_executors_own_functions(self):
        manifest = _manifest()
        assert registry.resolve(manifest.ports.emit_columns) is executor.emit_columns
        assert registry.resolve(manifest.ports.read_columns) is executor.read_columns
        assert registry.resolve(manifest.execution.handler) is executor.run

    def test_the_modes_are_the_enum_and_the_column_tables(self):
        manifest = _manifest()
        mode = manifest.param('output_mode')
        assert set(executor.OUTPUT_COLUMNS) == set(mode.enum)
        for name, columns in executor.OUTPUT_COLUMNS.items():
            node = {'id': 't', 'type': 'tokenize', 'params': {'output_mode': name, 'text_column': '正文'}}
            assert executor.emit_columns(node, ['正文']) == list(columns), name
            assert executor.read_columns(node) == ['正文'], name
