"""Behaviour tests for reusable nodes: one canvas entry, an ordered boundary, a run expansion.

The harness runs the REAL ``canvas.js`` + ``workflow.js`` + ``reusable.js``. The key
structural assertions are the ones a screenshot cannot make: the inside nodes never
enter ``canvas.nodes``, auto-layout therefore sees one measured block, the file keeps
the group, the run gets namespaced children, and external wires land on the template's
ordered input slots. The rest pins create/insert/toggle/preview/status behaviour.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_reusable.mjs'
STATIC = REPO / 'backend' / 'static'
CANVAS_JS = STATIC / 'js' / 'canvas.js'
WORKFLOW_JS = STATIC / 'js' / 'workflow.js'
REUSABLE_JS = STATIC / 'js' / 'reusable.js'
APP_JS = STATIC / 'js' / 'app.js'
INDEX_HTML = STATIC / 'index.html'
STYLE_CSS = STATIC / 'css' / 'style.css'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]


@pytest.fixture(scope='module')
def ru() -> dict:
    proc = run_node(str(HARNESS), str(CANVAS_JS), str(WORKFLOW_JS), str(REUSABLE_JS))
    assert proc.returncode == 0, proc.stderr[-2500:]
    return json.loads(proc.stdout)


class TestCreateFromSelection:
    def test_the_selected_nodes_become_one_collapsed_group(self, ru):
        created = ru['create']
        assert created['collapsed'] is True
        assert created['template_name'] == '清洗流水线'
        assert created['template_nodes'] == 2
        assert created['nodes_left'] == ['node-1', 'node-4', created['group']]
        assert [created['group']] == [n for n in created['nodes_left'] if n not in ('node-1', 'node-4')]

    def test_the_outside_wires_are_rewired_to_the_group(self, ru):
        assert ru['create']['connections'] == [
            ['node-1', ru['create']['group']],
            [ru['create']['group'], 'node-4'],
        ]

    def test_the_template_sent_to_the_store_has_relative_positions_and_real_sizes(self, ru):
        body = ru['create']['save_request'][0]
        assert body['name'] == '清洗流水线'
        assert [n['id'] for n in body['nodes']] == ['node-2', 'node-3']
        assert body['nodes'][0]['x'] == 0 and body['nodes'][1]['x'] == 300
        assert body['nodes'][0]['w'] == 220 and body['nodes'][0]['h'] == 80
        assert body['connections'] == [{'from': 'node-2', 'to': 'node-3'}]
        assert body['inputs'] == ['node-2']
        assert body['outputs'] == ['node-3']

    def test_creation_says_so(self, ru):
        assert ru['create']['toasts'] == ['CREATED']


class TestInsert:
    def test_a_saved_template_adds_exactly_one_node(self, ru):
        assert ru['insert']['added'] == 1
        assert ru['insert']['name'] == '已保存的模板'
        assert ru['insert']['nodes'] == 2
        assert ru['insert']['toasts'] == ['INSERTED']


class TestRunVersusFile:
    def test_a_run_expands_the_inside_and_namespaces_every_child(self, ru):
        expand = ru['expand']
        assert expand['run_has_group'] is False
        assert expand['run_ids'] == ['node-6__a', 'node-6__b', 'node-7']
        assert ['node-6__a', 'node-6__b'] in expand['run_connections']
        assert ['node-7', 'node-6__a'] in expand['run_connections']

    def test_a_file_keeps_the_group_and_its_external_wire(self, ru):
        assert ru['expand']['file_types'] == ['reusable', 'process']
        assert ru['expand']['file_connections'] == [['node-7', 'node-6']]

    def test_two_inputs_map_in_connection_order_to_the_template_slots(self, ru):
        conns = ru['slots']['connections']
        assert ['node-8', 'node-11__a'] in conns
        assert ['node-9', 'node-11__b'] in conns
        assert ['node-11__c', 'node-10'] in conns
        assert ru['slots']['errors'] == []

    def test_a_missing_input_is_named_before_the_run(self, ru):
        assert ru['missing_input']['errors'] == ['reusable.missingInputs']

    def test_saving_a_workflow_uses_the_file_shape(self, ru):
        assert ru['file_save']['has_group'] is True
        assert len(ru['file_save']['ids']) == 1


class TestToggleAndStatus:
    def test_collapsed_the_group_aggregates_running_over_done(self, ru):
        assert ru['collapsed_status'] == {
            'params': True,
            'badge': 'running',
            'badgeClass': 'node-run-badge run-running',
            'stage': False,
        }

    def test_expanded_the_inside_is_dom_only_with_its_own_boxes_and_statuses(self, ru):
        expanded = ru['expanded']
        assert expanded['params'] is False
        assert expanded['width'].endswith('px')
        assert expanded['stage'] is True
        assert expanded['inner_cards'] == 3
        assert expanded['inner_lines'] == 2
        assert expanded['running_dots'] == 1
        assert expanded['done_dots'] == 1
        # The structural point: the three inside nodes did not join the canvas model.
        assert expanded['model_has_only_group'] == ['node-12']
        assert expanded['auto_layout_calls'] == 1

    def test_a_failed_child_turns_the_group_red(self, ru):
        assert ru['failed_status'] == {'badge': 'failed', 'badgeClass': 'node-run-badge run-failed'}

    def test_collapsing_removes_the_inside_and_its_width(self, ru):
        assert ru['collapsed'] == {'params': True, 'width': '', 'stage': False}

    def test_the_style_preference_can_turn_off_the_layout_on_expand(self, ru):
        assert ru['auto_layout_off'] == {'calls': 0, 'expanded': True}
        assert ru['auto_layout_on']['calls'] == 1

    def test_a_history_state_remembers_the_open_inside(self, ru):
        """The fold state is a param, so undo/restore brings back the expanded view,
        not a collapsed group whose inside the user had just opened."""
        assert ru['restore'] == {'collapsed': False, 'stage': True}


class TestPreview:
    def test_a_collapsed_group_can_still_be_read_inside(self, ru):
        preview = ru['preview']
        assert preview['open'] is True
        assert preview['title'] == 'INSIDE 双入口'
        assert preview['stage_cards'] == 3
        assert preview['side_nodes'] == 3
        assert preview['slots'] == 2
        assert preview['closed'] is True

    def test_a_saved_template_can_be_read_before_it_is_inserted(self, ru):
        preview = ru['template_preview']
        assert preview['open'] is True
        assert preview['title'] == 'INSIDE 模板直看'
        assert preview['stage_cards'] == 2
        assert preview['side_nodes'] == 2
        assert preview['statuses'] == 0, 'a template without an instance has no run status to paint'

    def test_the_settings_form_names_the_slots_and_escapes_the_template_name(self, ru):
        settings = ru['settings']
        assert settings['has_slot_rows'] == 2
        assert settings['escaped_name'] is True
        assert settings['toggle_call'] is True
        assert settings['preview_call'] is True


class TestUnwrap:
    def test_the_group_becomes_ordinary_nodes_and_the_outside_wires_survive(self, ru):
        unwrap = ru['unwrap']
        assert unwrap['group_gone'] is True
        assert unwrap['inner_count'] == 3
        inner = set(unwrap['inner_ids'])
        conns = unwrap['connections']
        assert [c for c in conns if c[0] == unwrap['up']][0][1] in inner
        assert [c for c in conns if c[1] == unwrap['down']][0][0] in inner
        assert len([c for c in conns if c[0] in inner and c[1] in inner]) == 2
        assert unwrap['group'] not in {end for c in conns for end in c}
        assert unwrap['toasts'] == ['UNWRAPPED']

    def test_unwrap_is_one_undo_step(self, ru):
        unwrap = ru['unwrap']
        assert unwrap['undo_group_back'] is True
        assert unwrap['undo_nodes'] == sorted([unwrap['up'], unwrap['down'], unwrap['group']])
        assert not (set(unwrap['inner_ids']) & set(unwrap['undo_nodes']))

    def test_too_many_external_wires_refuses_before_moving_anything(self, ru):
        refused = ru['unwrap_too_many']
        assert refused['group_still'] is True
        assert len(refused['model']) == 4
        assert refused['toasts'] == ['TOO-MANY-INPUTS']

    def test_a_disabled_group_unwraps_into_disabled_children(self, ru):
        assert ru['unwrap_disabled'] == {'count': 3, 'all_disabled': True, 'toasts': ['UNWRAPPED']}

    def test_the_settings_form_offers_the_unwrap_door(self, ru):
        assert ru['unwrap_settings'] == {'has_unwrap': True, 'has_hint': True}


class TestAutoLayoutBlock:
    def test_the_expanded_group_is_one_measured_block_not_a_frame_around_neighbours(self, ru):
        block = ru['autolayout_block']
        assert block['group_size'] == [800, 500], 'the measured expansion must drive the layout'
        assert block['overlap'] is False, 'the neighbour must not land inside the group block'
        assert len(block['model_has_group_only']) == 2, block['model_has_group_only']
        assert ru['expanded']['model_has_only_group'] == ['node-12'], (
            'the group is the only model node while expanded; its three children are DOM-only'
        )


class TestContracts:
    def test_the_style_select_refreshes_the_themed_trigger(self, ru):
        assert ru['custom_select']['value'] == 'baseline'
        assert ru['custom_select']['calls'] >= 1, 'a native value write must also refresh CustomSelect'

    def test_a_right_clicked_unselected_node_is_the_one_grouped(self, ru):
        created = ru['create_from_ids']
        assert created['template_nodes'] == [created['only']]
        assert created['model'] == [created['group']], 'the single clicked node leaves only the group'

    def test_the_browser_type_list_matches_the_template_validator(self):
        from services.reusable_store import ALLOWED_TYPES

        source = REUSABLE_JS.read_text(encoding='utf-8')
        match = re.search(r'var REUSABLE_ALLOWED_TYPES = \[(.*?)\];', source, re.S)
        assert match, 'the allow-list must stay a literal a test can read'
        listed = set(re.findall(r"'([^']+)'", match.group(1)))
        assert listed == set(ALLOWED_TYPES)

    def test_the_page_has_every_door_and_container(self):
        page = INDEX_HTML.read_text(encoding='utf-8')
        for element_id in (
            'ctx-create-reusable',
            'ctx-insert-reusable',
            'ctx-preview-reusable',
            'ctx-toggle-reusable',
            'ctx-unwrap-reusable',
            'reusable-preview-overlay',
            'reusable-preview-stage',
            'reusable-preview-side',
            'reusable-auto-layout',
        ):
            assert f'id="{element_id}"' in page, element_id
        assert '<script src="/js/reusable.js"></script>' in page
        assert 'ReusableNodes.createFromSelection()' in page or 'ReusableNodes' in page

    def test_the_style_menu_carries_the_expand_layout_preference(self):
        page = INDEX_HTML.read_text(encoding='utf-8')
        assert 'ReusableNodes.setAutoLayoutOnExpand(this.checked)' in page
        assert 'data-i18n="reusable.autoLayoutOnExpand"' in page
        app = APP_JS.read_text(encoding='utf-8')
        assert 'reusableAutoLayout' in app
        css = STYLE_CSS.read_text(encoding='utf-8')
        assert '.settings-checkbox' in css

    def test_the_canvas_routes_the_layout_button_and_paints_group_statuses(self):
        canvas = CANVAS_JS.read_text(encoding='utf-8')
        assert 'ReusableNodes.expand' in canvas
        assert 'expandReusable' in canvas
        assert 'ReusableNodes.paintStatuses' in canvas
        assert '_paintRunBadge' in canvas
        workflow = WORKFLOW_JS.read_text(encoding='utf-8')
        assert 'ReusableNodes.errors()' in workflow
        assert 'canvas.toWorkflowJSON({ expandReusable: false })' in workflow
        assert 'ReusableNodes.settingsHtml(nodeId)' in workflow

    def test_every_new_word_has_both_catalogues(self):
        app = APP_JS.read_text(encoding='utf-8')
        for key in (
            'node.reusable',
            'ctx.createReusable',
            'ctx.insertReusable',
            'ctx.previewReusable',
            'ctx.expandReusable',
            'reusable.previewTitle',
            'reusable.inputsWired',
            'reusable.autoLayoutOnExpand',
            'reusable.badTemplate',
            'nodeType.reusable',
        ):
            assert app.count(f"'{key}'") >= 2, f'{key} must exist in zh and en'
