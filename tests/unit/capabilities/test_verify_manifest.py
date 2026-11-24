"""The verify node's declaration: exactly two data tables and the key columns it compares."""

from pathlib import Path

import pytest
from capabilities_kernel import registry
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS
from nodes.executors import verify as executor

from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
LIST = {'id': 'l', 'type': 'upload', 'params': {'dataset_id': 'ds_list'}}
RESULT = {'id': 'r', 'type': 'upload', 'params': {'dataset_id': 'ds_result'}}


def _manifest():
    manifest = registry.manifest_for_node('verify')
    assert manifest is not None
    return manifest


def _codes(params, parents=(LIST, RESULT)):
    node = {'id': 'v', 'type': 'verify', 'params': params}
    workflow = {'nodes': [node, *parents], 'connections': [{'from': p['id'], 'to': 'v'} for p in parents]}
    return [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed() if entry['id'] == 'v']


class TestTheDeclaration:
    def test_the_manifest_is_whole_and_matches_the_catalogue(self):
        manifest = _manifest()
        assert manifest.problems() == []
        plugin = PLUGINS['verify']
        assert (plugin.label_key, plugin.category, plugin.rows) == (
            manifest.identity.title_key,
            manifest.identity.category,
            manifest.ports.rows,
        )
        assert NODE_DEFAULTS['verify'] == manifest.defaults()

    def test_the_hook_handler_and_validator_are_the_executors_own(self):
        manifest = _manifest()
        assert registry.resolve(manifest.ports.read_columns) is executor.read_columns
        assert registry.resolve(manifest.ports.emit_columns) is executor.emit_columns
        assert registry.resolve(manifest.execution.handler) is executor.run
        assert registry.resolve(manifest.validators[0]) is executor.validate_node

    def test_the_page_and_contract_exist(self):
        manifest = _manifest()
        assert (REPO / manifest.docs.page).is_file()
        for path in manifest.tests.contracts:
            assert (REPO / path).is_file()


class TestValidation:
    def test_two_data_parents_and_keys_are_clean(self):
        assert _codes({'input_key_column': '链接', 'result_key_column': '文章URL'}) == []

    def test_one_parent_is_named(self):
        assert 'engine.verify_two_inputs' in _codes(
            {'input_key_column': '链接', 'result_key_column': '文章URL'},
            parents=(LIST,),
        )

    def test_a_name_parent_does_not_count_as_a_table(self):
        name = {'id': 'n', 'type': 'name', 'params': {'workflow_name': '采集'}}
        assert 'engine.verify_two_inputs' not in _codes(
            {'input_key_column': '链接', 'result_key_column': '文章URL'},
            parents=(LIST, RESULT, name),
        )

    def test_the_list_key_is_required(self):
        assert 'engine.verify_need_list_col' in _codes({'result_key_column': '文章URL'})

    def test_the_result_key_is_required(self):
        assert 'engine.verify_need_result_col' in _codes({'input_key_column': '链接'})

    def test_the_read_hook_skips_blank_columns(self):
        node = {'id': 'v', 'type': 'verify', 'params': {'input_key_column': '链接', 'result_key_column': ' '}}
        assert executor.read_columns(node) == ['链接']


class TestTheOutputContract:
    """The report is the LIST's columns plus five audit ones — not the fan-in union."""

    def test_the_first_wire_is_the_list(self):
        node = {'id': 'v', 'type': 'verify', 'params': {}}
        parents = [['链接', '笔记内容'], ['文章URL', '评论内容']]
        assert executor.emit_columns(node, None, parents) == [
            '链接',
            '笔记内容',
            *executor.REPORT_COLUMNS,
        ]

    def test_swap_tables_makes_the_second_wire_the_list(self):
        node = {'id': 'v', 'type': 'verify', 'params': {'swap_tables': True}}
        parents = [['链接', '笔记内容'], ['文章URL', '评论内容']]
        assert executor.emit_columns(node, None, parents) == ['文章URL', '评论内容', *executor.REPORT_COLUMNS]

    def test_the_result_only_columns_are_never_promised(self):
        node = {'id': 'v', 'type': 'verify', 'params': {}}
        columns = executor.emit_columns(node, None, [['链接'], ['评论内容']])
        assert '评论内容' not in columns

    def test_an_audit_name_already_in_the_list_is_not_duplicated(self):
        node = {'id': 'v', 'type': 'verify', 'params': {}}
        columns = executor.emit_columns(node, None, [['链接', executor.COL_STATUS], ['文章URL']])
        assert columns.count(executor.COL_STATUS) == 1

    def test_an_unknown_or_single_wire_stays_unknown(self):
        node = {'id': 'v', 'type': 'verify', 'params': {}}
        assert executor.emit_columns(node, None, None) is None
        assert executor.emit_columns(node, None, [None, ['文章URL']]) is None
        assert executor.emit_columns(node, None, [['链接']]) is None

    def test_the_static_model_hands_the_wires_over_in_connection_order(self):
        """The lineage view asks the hook with the wires in connection order, so the list side,
        and only the list side, is the one the report keeps."""
        from nodes.executors.tokenize import OUTPUT_COLUMNS
        from nodes.schema import compute_columns

        nodes = {
            'list': {'id': 'list', 'type': 'tokenize', 'params': {'output_mode': 'words_only'}},
            'result': {'id': 'result', 'type': 'tokenize', 'params': {'output_mode': 'csv_line'}},
            'v': {'id': 'v', 'type': 'verify', 'params': {}},
        }
        forwards = compute_columns(
            nodes,
            [{'from': 'list', 'to': 'v'}, {'from': 'result', 'to': 'v'}],
        )['v']
        assert forwards == [*OUTPUT_COLUMNS['words_only'], *executor.REPORT_COLUMNS]
        swapped = compute_columns(
            nodes,
            [{'from': 'result', 'to': 'v'}, {'from': 'list', 'to': 'v'}],
        )['v']
        assert swapped == [*OUTPUT_COLUMNS['csv_line'], *executor.REPORT_COLUMNS]
