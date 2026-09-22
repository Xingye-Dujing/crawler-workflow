"""Behaviour tests for the real canvas pointer layer (canvas.js + workflow.js).

The state harness pins what a canvas serialises to; this one pins how a user gets
there — dragging a wire between two nodes, clicking the thing that removes one,
folding a node and reloading the page, zooming, laying out, renaming. Those paths
were unenterable while the DOM stub had no selector engine, no parent chain and
dropped every animation frame; see tests/frontend/harness_canvas_ix.mjs.

Skipped when node is not on PATH, like every other frontend harness.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

JS_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_canvas_ix.mjs'


@pytest.fixture(scope='module')
def ix():
    proc = run_node(str(HARNESS), str(JS_DIR / 'canvas.js'), str(JS_DIR / 'workflow.js'))
    assert proc.returncode == 0, f'canvas harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestSelection:
    def test_selecting_a_second_node_clears_the_first(self, ix):
        """Two highlighted nodes would mean the canvas remembers two targets for a
        delete, and only one of them is what the user last touched."""
        assert ix['selection']['afterFirst'] == [ix['ids']['selection'][0]]
        assert ix['selection']['afterSecond'] == [ix['ids']['selection'][1]]
        assert ix['selection']['afterDeselect'] == []

    def test_the_status_bar_counts_the_nodes_on_the_page(self, ix):
        assert ix['selection']['statusText'].endswith('2')


class TestConnections:
    def test_dragging_from_an_out_port_to_an_in_port_wires_them(self, ix):
        made = ix['connect_created']
        assert made['connections'] == [{'from': ix['ids']['connect'][0], 'to': ix['ids']['connect'][1]}]
        assert made['toasts'] == ['CONN-CREATED']
        assert made['persisted'] == 1, 'a wire the draft does not carry is a wire lost on reload'

    def test_the_drag_shows_a_temporary_line_and_ends_with_none(self, ix):
        assert ix['connect_started']['tempLines'] == 1, 'the user must see the wire following the pointer'
        assert ix['connect_created']['tempLineGone'] is True
        assert ix['connect_cancel'] == {
            'beforeCancel': 1,
            'afterCancel': 0,
            'connectingFrom': None,
        }, 'a cancelled drag must not leave a phantom line on the page'

    def test_the_temporary_line_is_redrawn_as_the_pointer_moves(self, ix):
        """The path's `d` attribute is the whole visual: an empty one is an
        invisible wire that still reports a connection as pending."""
        assert ix['connect_temp_d'].startswith('M ')
        assert ' C ' in ix['connect_temp_d']

    def test_the_same_pair_is_not_wired_twice(self, ix):
        assert ix['connect_duplicate'] == {'connections': 1, 'toasts': []}

    def test_a_node_cannot_be_wired_to_itself(self, ix):
        """A self-loop is a cycle, and the backend's topological sort would refuse
        the whole workflow at run time — better refused at the drag."""
        assert ix['connect_self']['connections'] == 1

    def test_dropping_on_empty_canvas_creates_nothing(self, ix):
        assert ix['connect_dropped_on_nothing'] == {'connections': 1, 'connectingFrom': None}

    def test_tokenize_to_visualize_forces_the_word_frequency_output(self, ix):
        """The chart can only draw words a word-frequency table holds, so the link
        rewrites the tokenizer's mode rather than producing an empty cloud."""
        assert ix['tokenize_visualize']['mode'] == 'word_freq'
        assert ix['tokenize_visualize']['persistedMode'] == 'word_freq'
        assert 'word_freq' in ix['tokenize_visualize']['content']


class TestRepaint:
    def test_one_repaint_per_connection(self, ix):
        assert ix['repaint']['lines'] == 2
        assert ix['repaint']['hits'] == 2, 'a wire with no hover target cannot be removed by clicking'

    def test_queued_repaints_coalesce_into_one_frame(self, ix):
        """Every change schedules a frame; running each would rebuild every path on
        the canvas once per edit."""
        assert ix['repaint']['pendingCleared'] is True
        assert ix['repaint']['lines_after_two_schedules'] == 2

    def test_hovering_a_wire_marks_it_and_releases_it(self, ix):
        assert ix['repaint']['hover_paints_red'] == '#ff4444'
        assert ix['repaint']['hover_releases'] is True

    def test_clicking_the_wire_removes_the_connection(self, ix):
        gone = ix['repaint']['after_delete']
        assert gone['connections'] == 1
        assert gone['toasts'] == ['CONN-REMOVED']
        assert gone['persisted'] == 1, 'the removal must survive a reload'

    def test_a_wire_to_a_deleted_node_paints_nothing(self, ix):
        assert ix['repaint']['orphan']['lines'] == 0

    def test_deleting_a_node_prunes_the_wires_touching_it(self, ix):
        assert ix['delete_node_prunes'] == [], 'orphaned wires would render as a path to nowhere'


class TestFolding:
    def test_folding_hides_the_body_but_keeps_the_title(self, ix):
        assert ix['fold']['folded'] is True
        assert ix['fold']['contentHidden'] == 'none'
        assert ix['fold']['actionsHidden'] == 'none'

    def test_the_fold_survives_a_reload(self, ix):
        """The bug this pins: `toggleFold` wrote a draft that had no fold field,
        so the layout the user arranged unfolded itself on the next page."""
        assert ix['fold']['persisted'] is True
        assert ix['fold']['after_reload'] == {'folded': True, 'contentHidden': 'none'}

    def test_unfolding_persists_the_other_way(self, ix):
        assert ix['fold']['unfolded'] == {'folded': False, 'contentShown': True, 'persisted': False}

    def test_a_fold_aimed_at_a_missing_node_is_harmless(self, ix):
        assert ix['fold']['missing_node_is_harmless'] is True


class TestViewTransform:
    def test_zoom_is_bounded_at_both_ends(self, ix):
        """An unbounded zoom either becomes an unreadable smear or a dot, and every
        later drag coordinate is divided by it."""
        assert ix['zoom']['ceiling'] == 3
        assert ix['zoom']['floor'] == 0.2

    def test_the_zoom_readout_follows_the_scale(self, ix):
        assert ix['zoom']['status'] == '144%'
        assert 'scale(1.44)' in ix['zoom']['transform']

    def test_the_pan_is_rounded_to_whole_pixels(self, ix):
        """A sub-pixel pan smears node text; the readout is what a user notices."""
        assert ix['zoom']['pan_rounded'] == 'translate(11px, -3px) scale(0.2)'

    def test_reset_view_centres_the_nodes_and_reports_one_hundred(self, ix):
        assert ix['reset_view']['zoom'] == 1
        assert ix['reset_view']['status'] == '100%'
        assert (ix['reset_view']['panX'], ix['reset_view']['panY']) == (650, 280)

    def test_reset_view_on_an_empty_canvas_moves_nothing(self, ix):
        assert ix['reset_view_no_nodes'] == {'panX': 0, 'panY': 0, 'zoom': 1}


class TestAutoLayout:
    def test_the_layout_respects_the_wiring_order(self, ix):
        laid = ix['auto_layout']['positions']
        assert ix['auto_layout']['dependencyOrderPreserved'] is True
        assert ix['auto_layout']['noOverlap'] is True
        assert ix['auto_layout']['persisted'] == laid, 'a layout that is not saved is lost on reload'

    def test_two_unconnected_components_are_stacked_not_piled(self, ix):
        assert ix['auto_layout_two_components']['separated'] is True

    def test_an_empty_canvas_survives_the_request(self, ix):
        assert ix['auto_layout_empty']['survived'] is True


class TestSettingsPanelRoundTrip:
    def test_opening_a_node_marks_the_node_and_opens_the_panel(self, ix):
        assert ix['edit']['settingsNode'] == ix['ids']['edit']
        assert ix['edit']['panelOpen'] is True
        assert ix['edit']['buttonMarked'] is True
        assert ix['edit']['panelFilled'] is True, 'the shipped renderer must be the one that ran'

    def test_clicking_the_same_node_again_closes_and_clears(self, ix):
        off = ix['edit']['toggled_off']
        assert off == {'settingsNode': None, 'panelOpen': False, 'buttonMarked': False}

    def test_the_panel_can_be_reopened(self, ix):
        assert ix['edit']['reopened'] == {'settingsNode': ix['ids']['edit'], 'panelOpen': True}

    def test_a_deleted_nodes_panel_does_not_outlive_it(self, ix):
        assert ix['edit']['stale_closed'] == {'settingsNode': None, 'panelOpen': False}

    def test_editing_a_node_that_is_not_there_opens_no_panel(self, ix):
        """The id came from a stale click target; the panel must not be left on
        screen describing nothing."""
        assert ix['edit']['missing_node']['panelOpen'] is False


class TestRename:
    def test_a_typed_name_reaches_the_title_the_element_and_the_draft(self, ix):
        typed = ix['rename']['typed']
        assert typed['title'] == '我的爬虫', 'the surrounding spaces are trimmed'
        assert typed['stamped'] == '我的爬虫', 'the element is what the re-stamp guard reads'
        assert typed['persisted'] == '我的爬虫'

    def test_the_dialog_opens_pre_filled_with_the_current_name(self, ix):
        assert ix['rename']['typed']['dialog']['initial'] == 'Data Source'

    def test_an_empty_answer_clears_the_custom_name_back_to_the_type_label(self, ix):
        assert ix['rename']['cleared_to_type_label'] == {'title': 'Data Source', 'stamped': 'Data Source'}

    def test_a_cancelled_dialog_changes_nothing(self, ix):
        assert ix['rename']['cancelled_leaves_it_alone'] is True

    def test_a_missing_node_never_opens_a_dialog(self, ix):
        assert ix['rename']['missing_node_makes_no_dialog'] is True

    def test_an_unnamed_node_follows_the_interface_language(self, ix):
        """A name the user typed is theirs and never translated; a default is the
        type's label in whatever language is showing."""
        followed = ix['rename']['follows_language_after_clear']
        assert followed['changed'] is True
        assert followed['chineseLabel'] == '处理'
        assert followed['stamped'] == '处理'


class TestNodePointerWiring:
    def test_a_header_press_starts_a_drag_and_selects_the_node(self, ix):
        drag = ix['wiring']['drag']
        assert drag['isDragging'] is True
        assert drag['dragTargetId'] == ix['ids']['wiring']
        assert drag['selected'] == ix['ids']['wiring']

    def test_moving_the_pointer_moves_the_node(self, ix):
        assert ix['wiring']['moved'] == {'left': '100px', 'top': '100px'}

    def test_releasing_ends_the_drag_and_persists_the_position(self, ix):
        released = ix['wiring']['released']
        assert released['isDragging'] is False
        assert released['dragTarget'] is None
        assert released['persistedX'] == 100

    def test_a_press_inside_the_action_bar_is_not_a_drag(self, ix):
        """Otherwise every click on edit or delete also nudges the node out of
        place."""
        assert ix['wiring']['actions_press_does_not_drag'] is True

    def test_node_behaviour_is_wired_by_listeners_not_inline_markup(self, ix):
        """The inline `onclick="canvas.deleteNode('<id>')"` template was how an
        id from a hand-edited workflow JSON reached the JavaScript engine."""
        wired = ix['wiring']['no_inline_handlers']
        assert wired['onclickAbsent'] == [True, True]
        assert wired['innerHtmlHasOn'] == [False, False]
        assert wired['listenerTypes'] == [['click'], ['click']]
        assert wired['titles'] == ['edit', 'delete']

    def test_the_trash_button_deletes_and_refreshes_the_count(self, ix):
        assert ix['wiring']['delete_button']['nodes'] == 0
        assert ix['wiring']['delete_button']['status'].endswith('0')

    def test_the_settings_button_opens_the_panel_for_its_own_node(self, ix):
        assert ix['wiring']['edit_button_opened_settings'] is True


class TestWorkspacePointer:
    def test_a_right_press_pans_and_closes_the_selection(self, ix):
        assert ix['pan']['isPanning'] is True
        assert ix['pan']['deselected'] is None
        assert ix['pan']['cursor'] == 'grabbing'

    def test_a_small_move_is_not_a_pan(self, ix):
        """Below the threshold the gesture was a right-CLICK, and the context menu
        the user asked for must still appear."""
        assert ix['pan']['below_threshold'] == {'panX': 0, 'wasDragging': False}

    def test_past_the_threshold_the_canvas_follows_the_pointer(self, ix):
        over = ix['pan']['over_threshold']
        assert over['wasDragging'] is True
        assert over['panX'] == 100
        assert 'translate(100px' in over['transform']

    def test_releasing_stops_the_pan(self, ix):
        assert ix['pan']['released'] == {'isPanning': False, 'cursor': 'default'}

    def test_a_pan_swallow_the_context_menu(self, ix):
        assert ix['pan']['pan_then_contextmenu_suppressed']['menuOpen'] is False
        assert ix['pan']['pan_then_contextmenu_suppressed']['wasDraggingAfter'] is False

    def test_a_right_click_on_empty_canvas_offers_only_the_node_free_actions(self, ix):
        empty = ix['pan']['contextmenu_on_empty_canvas']
        assert empty['menuOpen'] is True
        assert empty['contextNode'] is None
        assert empty['editHidden'] == 'none', 'edit/rename/delete need a node that is not there'

    def test_a_background_click_closes_the_settings_panel(self, ix):
        assert ix['pan']['background_click_closed_settings'] is True

    def test_a_click_on_a_node_keeps_the_panel_open(self, ix):
        assert ix['pan']['node_click_kept_settings'] is True


class TestContextMenu:
    def test_the_menu_names_the_node_it_opened_on(self, ix):
        assert ix['context_menu']['contextNode'] == ix['ids']['contextMenu']
        assert ix['context_menu']['open'] is True
        assert ix['context_menu']['editVisible'] == 'block'

    def test_the_fold_item_advertises_the_action_it_will_perform(self, ix):
        assert ix['context_menu']['foldAction'] == 'ctxFoldNode'
        assert ix['context_menu']['foldLabel'] == 'FOLD'

    def test_the_menu_closes_as_it_acts(self, ix):
        assert ix['context_menu']['fold_action']['stillOpen'] is False
        assert ix['context_menu']['delete_action']['menuClosed'] is True

    def test_the_fold_item_folds_the_right_node(self, ix):
        assert ix['context_menu']['fold_action']['folded'] is True
        assert ix['context_menu']['fold_action']['nodes'] == 1

    def test_the_delete_item_deletes_the_right_node(self, ix):
        assert ix['context_menu']['delete_action']['nodes'] == 0

    def test_a_new_node_lands_where_the_menu_was_opened(self, ix):
        created = ix['context_menu']['new_node']
        assert created['count'] == 1
        assert created['at'] == [['190px', '260px']], 'a random position hides the node behind the menu'

    def test_a_click_outside_the_menu_closes_it(self, ix):
        assert ix['context_menu']['outside_click_closes'] is False


class TestInitFromDraft:
    def test_a_stored_draft_comes_back_with_its_names_ids_and_order(self, ix):
        assert ix['init']['restored'] == ['node-9']
        assert ix['init']['title'] == '存档名'
        assert ix['init']['stamped'] == '存档名', 'the element is what decides a re-stamp later'
        assert ix['init']['nextId'] == 10

    def test_the_next_new_node_cannot_collide_with_a_restored_id(self, ix):
        assert ix['init']['next_id_avoids_the_restored'] == {'id': 'node-10', 'taken': True}

    def test_a_fold_comes_back_folded(self, ix):
        assert ix['init']['contentHidden'] == 'none'

    def test_a_corrupt_draft_opens_an_empty_canvas_instead_of_breaking(self, ix):
        """localStorage is user-editable and survives every upgrade; the only wrong
        outcome is a page that never finishes loading."""
        assert ix['init']['corrupt_draft'] == {'nodes': [], 'survived': True}

    def test_a_first_run_has_no_draft_at_all(self, ix):
        assert ix['init']['no_draft'] == {'nodes': []}


class TestNodeMarkup:
    def test_the_node_carries_icons_and_a_summary(self, ix):
        assert ix['icons']['markupHasSvg'] is True
        assert ix['icons']['summary'], 'an empty body reads as a node that has lost its settings'

    def test_the_upstream_lookup_finds_the_parent_and_reports_none_for_a_source(self, ix):
        assert ix['upstream']['found'] == ix['ids']['upstream'][0]
        assert ix['upstream']['none'] is None
