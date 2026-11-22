"""The source node's declaration and its matrix-driven pre-run check.

The validator reads the same platform matrix as the executor; these cases pin that the node is
refused by name for the matrix's own reasons, and that an anonymous mode is not asked for a login.
"""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.executors import source as executor

from engine.workflow import WorkflowEngine
from services.validation.engine import ValidationContext

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _manifest():
    manifest = registry.manifest_for_node('source')
    assert manifest is not None
    return manifest


def _node(params, platform='weibo'):
    return {'id': 's', 'type': 'source', 'platform': platform, 'params': params}


def _keys(params, platform='weibo', data_inputs=frozenset()):
    context = ValidationContext(
        node_id='s',
        label='源 #s',
        nodes={},
        connections=[],
        data_inputs=data_inputs,
    )
    return [problem['message_key'] for problem in executor.validate_node(_node(params, platform), context)]


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['source']
        assert (plugin.label_key, plugin.category, plugin.rows, plugin.defaults_from) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
            manifest.ui.defaults_from,
        )

    def test_the_form_is_the_matrix_and_the_dynamic_defaults_are_not_declared(self):
        manifest = _manifest()
        assert manifest.params == ()
        assert manifest.ui.form == 'custom'
        assert manifest.ui.defaults_from == 'capabilities'

    def test_the_handler_and_validator_are_the_executors_own(self):
        manifest = _manifest()
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_the_engine_wires_the_manifest_validator(self):
        workflow = {'nodes': [_node({}, platform='')], 'connections': []}
        entries = WorkflowEngine(workflow).validate_detailed()
        assert [(entry['id'], entry['code']) for entry in entries] == [('s', 'engine.source')]

    def test_no_platform_is_named(self):
        assert _keys({}, platform='') == ['engine.source_no_platform']

    def test_an_unknown_platform_is_named(self):
        assert _keys({}, platform='moonbase') == ['engine.source_unknown_platform']

    def test_a_missing_required_field_is_named(self):
        assert _keys({'collect': 'posts'})[0] == 'engine.source_missing'

    def test_an_anonymous_board_is_not_asked_for_a_login(self):
        assert _keys({'collect': 'hot'}) == []

    def test_an_unknown_mode_is_named_when_the_cell_offers_several(self):
        assert _keys({'collect': 'moonbase'}) == ['engine.source_unknown_mode']

    def test_a_watermark_outside_bilibili_author_is_named(self):
        keys = _keys({'collect': 'posts', 'keyword': 'x', 'watermark': True}, platform='zhihu')
        assert 'engine.watermarkUnsupported' in keys

    def test_a_watermark_with_recrawl_is_named(self):
        keys = _keys(
            {'collect': 'author', 'author': 'https://space.bilibili.com/1', 'watermark': True, 'recrawl': True},
            platform='bilibili',
        )
        assert 'engine.watermarkRecrawl' in keys
