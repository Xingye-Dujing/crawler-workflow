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


class TestConnectionWarnings:
    """A wire is explained the moment it is drawn, because the engine treats each
    node type's fan-in differently and half of those differences are silent.

    The harness (`connect_warnings`) drives the REAL async `finishConnection` and reads
    back which warning fired, whether "undo" took the wire back, and whether ticking
    "don't warn again" mutes only that one category. Message bodies are stubbed to
    sentinels (FANIN-FIRST …), so an assertion names the OUTCOME, not a sentence.
    """

    def test_a_first_wire_into_a_process_is_a_normal_feed_and_is_not_warned(self, ix):
        """One upstream is how a process node is meant to be fed — warning there would
        cry wolf on every ordinary connection."""
        assert ix['connect_warnings']['process_first_silent'] is True

    def test_a_second_wire_into_a_process_warns_that_only_the_first_is_used(self, ix):
        got = ix['connect_warnings']['process_fanin']
        assert got['msg'].startswith('FANIN-FIRST'), got
        assert got['toggles'] == ['conn_dismiss_fanin_first']
        assert got['connections'] == 2, 'the wire is kept; the warning only explains it'

    def test_two_tables_into_an_output_warn_that_they_merge(self, ix):
        got = ix['connect_warnings']['output_merge']
        assert got['msg'].startswith('FANIN-MERGE'), got
        assert got['connections'] == 2

    def test_a_second_wire_into_an_analysis_warns_about_the_join_limit(self, ix):
        assert ix['connect_warnings']['analysis_fanin']['msg'].startswith('FANIN-ANALYSIS')

    def test_two_upstreams_into_a_source_warn_without_the_canvas_deciding_the_mode(self, ix):
        """The canvas must not hold a second opinion about which crawl can be fed — the
        one fixed message carries both outcomes instead of consulting the capability
        matrix here."""
        assert ix['connect_warnings']['source_fanin']['msg'].startswith('FANIN-SOURCE')

    def test_a_wire_into_an_upload_is_reported_as_ignored_from_the_first(self, ix):
        got = ix['connect_warnings']['upload_ignore']
        assert got['msg'].startswith('FANIN-IGNORE'), got
        assert got['toggles'] == ['conn_dismiss_fanin_ignore']

    def test_a_wire_into_a_name_node_is_reported_as_refused(self, ix):
        assert ix['connect_warnings']['name_refused']['msg'].startswith('FANIN-NAME')

    def test_undo_takes_the_second_wire_back_and_reports_it_removed(self, ix):
        """The whole point of "written then explained": if the consequence is not what
        the user wanted, the undo button must leave the canvas as it was."""
        got = ix['connect_warnings']['undo']
        assert got['after'] == got['before'] == 1, got
        assert got['lastToast'] == 'CONN-REMOVED'

    def test_dismissing_a_warning_mutes_only_that_category_for_the_session(self, ix):
        got = ix['connect_warnings']['dismiss']
        assert got['muted'] is True
        assert got['afterThird'] == got['afterDismiss'], 'a silenced category adds no dialog'

    def test_the_first_branch_out_explains_the_snapshot_once(self, ix):
        """A fan-out is safe — every branch gets the same full copy — so it is explained
        at the moment the first split happens and never repeated for a third branch."""
        got = ix['connect_warnings']
        assert got['fanout_first_silent'] is True
        assert got['fanout_shown']['msg'].startswith('FANOUT')
        assert got['fanout_third_silent'] is True


class TestTouchGestures:
    """A finger drives the same gestures a mouse does — wire, pan, drag — because canvas.js
    and makeDraggable/makeResizable now listen to Pointer events, not mouse. The harness
    dispatches pointerdown/pointermove/pointerup with pointerType:'touch' to prove the
    tablet path works, which is the whole point of the Pointer migration (a tablet has no
    right button to pan with under the old mouse-only code)."""

    def test_a_finger_drag_between_ports_wires_them(self, ix):
        assert ix['touch_gestures']['wireFromFingerDrag'] is True

    def test_a_finger_drag_on_the_background_pans_the_camera(self, ix):
        assert ix['touch_gestures']['backgroundPanByFinger'] is True

    def test_a_finger_drag_on_a_node_header_moves_the_node(self, ix):
        assert ix['touch_gestures']['nodeMovedByFinger'] is True

    def test_the_pinch_base_is_the_two_fingers_landing_positions(self, ix):
        """A pinch must remember where the two fingers first touched, or a single spread
        would read as no zoom at all (the base would be the already-moved position)."""
        assert ix['touch_gestures']['pinchBaseCaptured'] is True

    def test_two_fingers_spread_apart_zoom_in(self, ix):
        pinch = ix['touch_gestures']['pinchZoomIn']
        assert pinch['zoomedIn'] is True, 'a wider gap between two fingers must scale the canvas up'
        assert pinch['status'] == '250%', 'the readout follows the pinch, not a hidden state'

    def test_two_fingers_slide_together_pans_without_changing_the_scale(self, ix):
        """The other half of a tablet gesture: moving both fingers the same way pans the
        canvas, and a pinch whose spread never changes must not creep the zoom."""
        slide = ix['touch_gestures']['twoFingerSlide']
        assert slide['panned'] is True
        assert slide['zoomUnchanged'] is True

    def test_a_pinch_that_lifts_to_one_finger_keeps_the_pan_then_releases_cleanly(self, ix):
        """Lifting a finger mid-pinch must not drop the pan the moment it is a single
        finger (a tablet user finishing a pinch and continuing to drag), and lifting the
        last finger must clear all gesture bookkeeping so the next touch starts fresh."""
        assert ix['touch_gestures']['stillPanningWithOneFinger'] is True
        assert ix['touch_gestures']['gestureReleased'] is True


class TestWheel:
    """A two-finger trackpad scroll and a pinch arrive as wheel events; the canvas must
    tell them apart (Chrome reports a trackpad pinch as a ctrlKey wheel) and keep the
    plain mouse wheel zooming, since a desktop wheel carries no horizontal travel."""

    def test_two_finger_scroll_pans_the_canvas(self, ix):
        """A scroll with a horizontal delta (a trackpad) pans the surface with the gesture
        and leaves the scale alone — this is the two-finger “移动画布”."""
        trackpad = ix['wheel']['trackpad']
        assert (trackpad['panX'], trackpad['panY']) == (-80, -20)
        assert trackpad['zoom'] == 1, 'a plain two-finger scroll must never zoom'

    def test_ctrl_or_pinch_wheel_zooms_in(self, ix):
        """Holding Ctrl (a trackpad pinch in Chrome/Edge, or a deliberate ctrl-wheel)
        scales up about the cursor and updates the readout."""
        pinch = ix['wheel']['ctrlPinch']
        assert pinch['zoom'] > 1
        assert pinch['status'] == '111%'

    def test_a_plain_mouse_wheel_still_zooms(self, ix):
        """A desktop wheel has no horizontal delta and no modifier — it keeps the long-
        standing zoom (down = out), so the mouse users' muscle memory is unchanged."""
        assert ix['wheel']['mouseWheel']['zoom'] < 1


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

    def test_wires_on_one_centreline_are_drawn_flat(self, ix):
        """rA→rB→rC sit at equal height on one line: the honest rendering is flat.

        A ' C ' here is the old always-bezier behaviour — every wire bowed by a
        hair even when the geometry promised a straight run.
        """
        ds = ix['repaint']['wire_ds']
        assert len(ds) == 2, ds
        for d in ds:
            assert ' L ' in d and ' C ' not in d, d

    def test_a_backwards_wire_keeps_its_curve(self, ix):
        """The flat rule must exclude exactly what it claims to: a wire drawn back
        leftward cannot be flat without cutting through the source box."""
        assert ' C ' in ix['repaint']['back_edge_d'], ix['repaint']['back_edge_d']

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

    def test_reset_view_keeps_a_cluster_that_already_fits_at_one_hundred(self, ix):
        """A graph smaller than the window must NOT loom larger: fit re-centres it
        at its own size. panX stays the old 650, but panY drops to 304 because the
        band the menu does not cover starts below the 48px bar, not at y=0."""
        assert ix['reset_view']['zoom'] == 1
        assert ix['reset_view']['status'] == '100%'
        assert (ix['reset_view']['panX'], ix['reset_view']['panY']) == (650, 304)

    def test_reset_view_on_an_empty_canvas_moves_nothing(self, ix):
        assert ix['reset_view_no_nodes'] == {'panX': 0, 'panY': 0, 'zoom': 1}

    def test_reset_view_shrinks_a_cluster_wider_than_the_window_into_view(self, ix):
        """The bug 适应 is for: a node off the right/bottom edge. After fit EVERY
        projected box must sit inside the 1920x1080 stub viewport below the menu,
        and the readout must match the shrunk zoom (±1 for the JS/Python .5 tie)."""
        fit = ix['reset_view_fit']
        assert 0.2 <= fit['zoom'] < 1
        assert abs(int(fit['status'][:-1]) - fit['zoom'] * 100) <= 1
        for box in fit['boxes']:
            assert box['left'] >= 0 and box['right'] <= 1920
            assert box['top'] >= 0 and box['bottom'] <= 1080


class TestAutoLayout:
    def test_the_layout_respects_the_wiring_order(self, ix):
        laid = ix['auto_layout']['positions']
        assert ix['auto_layout']['dependencyOrderPreserved'] is True
        # noOverlap is a RECTANGLE test now, and the head node measures 340×300:
        # the old fixed 280×120 lattice put the next rank inside it, which is the
        # wide-node collision the user reported, invisible to distinct-coordinate
        # checks while every stub box was 220 wide.
        assert ix['auto_layout']['noOverlap'] is True
        assert ix['auto_layout']['persisted'] == laid, 'a layout that is not saved is lost on reload'

    def test_a_chain_of_unequal_heights_draws_flat_wires(self, ix):
        """120 / 300 / 120 ranks: centre-aligned placement puts every port pair on
        one shared line, so both wires must be ' L '. Under the old equal-TOPS rule
        the middle node's centre sat 90px off and both wires bowed (' C ' → red)."""
        ds = ix['auto_layout_straight']['wire_ds']
        assert len(ds) == 2, ds
        for d in ds:
            assert ' L ' in d and ' C ' not in d, d

    def test_two_unconnected_components_are_stacked_not_piled(self, ix):
        assert ix['auto_layout_two_components']['separated'] is True

    def test_layout_order_sets_the_vertical_stack(self, ix):
        """排布顺序 overrides creation order: a LOWER number stacks HIGHER, and a blank
        name node falls below every numbered one."""
        r = ix['auto_layout_order']
        assert r['numbered_flip'] is True, r['tops']
        assert r['numbered_above_blank'] is True, r['tops']

    def test_a_blank_layout_order_keeps_creation_order(self, ix):
        assert ix['auto_layout_order_default']['a_above_b'] is True


class TestOutline:
    """The right-side outline: a flat map of every node; a row jump selects + centred the camera."""

    def test_it_lists_every_node_in_creation_order_with_its_label(self, ix):
        o = ix['outline']
        assert o['count'] == 3
        assert o['labels'] == ['Workflow Name', 'Data Source', 'Visualize']
        assert o['tags'] == ['NAM', 'SRC', 'VIZ']
        assert o['rowIds'] == ['node-1', 'node-2', 'node-3']
        assert o['rows'] == 3, 'the DOM list must match the data the sidebar renders from'

    def test_a_disabled_node_is_listed_but_flagged_off(self, ix):
        o = ix['outline']
        # Still on the map (it is a canvas overview, not a run preview), just dimmed.
        assert o['disabledId'] in o['rowIds']
        assert o['offIds'] == [o['disabledId']]

    def test_focusing_a_row_selects_the_node_and_zooms_in(self, ix):
        """The jump frames the target WITH its neighbours, so it must ZOOM IN past 100% —
        the whole reason it is not 适应 (fit-all), which shrinks every box to a thumbnail
        once the graph is large."""
        o = ix['outline']
        assert o['focusSelected'] == 'node-2'
        assert o['focusMoved'] is True, 'a node off-screen must be brought into view'
        assert o['focusZoomInRange'] is True, 'clamped to [50%, 150%]'
        assert o['focusZoomPast100'] is True, 'the outline jump enlarges the node, never shrinks it'
        assert o['statusZoom'] == f'{o["focusZoomPct"]}%', 'the status bar must follow the camera'

    def test_it_collapses_and_persists_like_the_palette(self, ix):
        o = ix['outline']
        assert o['collapsedOnce'] is True and o['persistedOnce'] == '1'
        assert o['collapsedTwice'] is False and o['persistedTwice'] == '', 'toggle twice returns to expanded'

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

    def test_paste_is_offered_only_when_something_is_on_the_clipboard(self, ix):
        """The action itself refuses silently, so an always-visible item was a menu
        entry that did nothing — reads as broken, not as "nothing copied yet"."""
        assert ix['context_menu']['pasteVisible'] == 'none', ix['context_menu']
        assert ix['context_menu']['paste_after_copy'] == 'block'

    def test_the_menu_closes_as_it_acts(self, ix):
        assert ix['context_menu']['fold_action']['stillOpen'] is False
        assert ix['context_menu']['delete_action']['menuClosed'] is True

    def test_the_fold_item_folds_the_right_node(self, ix):
        assert ix['context_menu']['fold_action']['folded'] is True
        assert ix['context_menu']['fold_action']['nodes'] == 1

    def test_a_folded_node_offers_the_other_half_of_the_action(self, ix):
        """The row changes its mind with the node: a menu that keeps saying 「折叠」
        after the node is folded offers an action that does nothing visible, which
        reads as a broken item rather than as a toggle."""
        got = ix['context_menu']['on_folded']
        assert got['foldAction'] == 'ctxUnfoldNode', got
        assert got['foldLabel'] == 'UNFOLD', got

    def test_the_menu_is_clamped_by_its_own_measured_box(self, ix):
        """400×300 window, a 260×180 menu: only its real size says where the right
        edge is. The old constant margin parked the menu off-screen in one language
        and stopped it 100 px early in another."""
        assert ix['context_menu']['clamped']['position'] == ['132px', '112px'], ix['context_menu']['clamped']

    def test_the_delete_item_deletes_the_right_node(self, ix):
        assert ix['context_menu']['delete_action']['nodes'] == 0

    def test_a_new_node_lands_where_the_menu_was_opened(self, ix):
        created = ix['context_menu']['new_node']
        assert created['count'] == 1
        assert created['at'] == [['190px', '260px']], 'a random position hides the node behind the menu'

    def test_a_click_outside_the_menu_closes_it(self, ix):
        assert ix['context_menu']['outside_click_closes'] is False


class TestNodeResizeRepaint:
    """A wire's `d` holds LITERAL coordinates measured at paint time, while the
    port dot it must meet is CSS (`top: 50%`) and follows the box forever. Two
    boot steps resize every box AFTER the first paint — the webfont lands late,
    and CustomSelect collapses a node's raw <select> (an EXPANDED list until
    enhanced) — and a resize fires no event: the user's wires ended beside their
    ports until a drag happened to re-measure."""

    def test_a_box_that_grew_after_the_paint_redraws_its_wires(self, ix):
        """The harness holds both boxes at 120 while the first paint runs, then
        says 220: the port centres really move, so the frozen numbers are now
        provably wrong for this page — and the observer is what fixes them."""
        got = ix['resize_repaint']
        assert got['wire_before'] == 'M 220 60 L 400 60', got
        assert got['wire_after'] == 'M 220 110 L 400 110', got

    def test_the_repaint_runs_in_the_callback_not_a_deferred_frame(self, ix):
        """A ResizeObserver callback lands after this frame's layout and before
        its paint — measuring THERE is guaranteed fresh. Relying on a queued rAF
        instead re-measures a stale box, which is exactly how the fonts.ready
        fix still missed the CustomSelect step."""
        assert ix['resize_repaint']['no_frame_needed'] is True

    def test_the_resize_repaint_touches_neither_history_nor_draft(self, ix):
        """The page merely loading must not become an undo step or a save."""
        assert ix['resize_repaint']['no_history_growth'] is True
        assert ix['resize_repaint']['no_draft_rewrite'] is True


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


class TestCommentNodeForm:
    """The 评论 node's form is written by hand in workflow.js, so nothing above it checked it.

    That is how 重新采集 came to be missing on every platform's comment node while the matrix
    said the field exists: the panel builds this form field by field rather than from the
    matrix, and no test had ever rendered it. The knobs are asserted by what they WRITE — a
    checkbox whose ``onchange`` does not name the parameter would be decoration.
    """

    def test_the_form_renders_with_its_own_knobs(self, ix):
        html = ix['comment_form']
        assert "'comment_limit'" in html and "'per_article_file'" in html and "'keep_parts'" in html, html[:400]

    def test_the_comment_form_offers_to_recollect_what_its_ledger_would_skip(self, ix):
        """A comment walk dedupes through the same ledger a source walk does, so the way back
        has to be on this form too — with the hint that says what ticking it costs."""
        html = ix['comment_form']
        assert "'recrawl',this.checked" in html, f'no recrawl checkbox on the comment form: {html[:600]}'
        assert 'settings.recrawl' in html or '重新采集' in html, html[:600]
        assert 'settings.recrawlHint' in html or '默认关闭' in html, 'a costly switch with no explanation'

    def test_an_untouched_comment_node_starts_with_the_ledger_in_force(self, ix):
        """Default off: re-collecting everything is the expensive reading of an empty box."""
        assert ix['comment_form'], 'the form did not render at all'
