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
    """Three independent wheel roles that never grab one another: a pinch (Chrome reports
    it as a ctrlKey wheel) zooms; a trackpad two-finger scroll pans the surface following
    the fingers; a plain mouse-wheel notch zooms. Because a purely-vertical trackpad swipe
    and a mouse notch are indistinguishable in one event on Windows/Chrome, the classifier
    reads the STREAM — a horizontal delta, a fractional value, or a changing delta upgrades
    the whole burst to a pan, so the brief horizontal-zero moment of a diagonal cannot
    steal one axis."""

    def test_two_finger_scroll_pans_the_canvas(self, ix):
        """A scroll with a horizontal delta (a trackpad) pans the surface FOLLOWING the
        fingers — the wheel delta is negated, so a leftward swipe drags the canvas left —
        and leaves the scale alone. This is the two-finger “移动画布”."""
        trackpad = ix['wheel']['trackpad']
        assert (trackpad['panX'], trackpad['panY']) == (80, 20), (
            'the pan must follow the fingers (wheel delta negated), not run against them'
        )
        assert trackpad['zoom'] == 1, 'a plain two-finger scroll must never zoom'

    def test_a_vertical_trackpad_swipe_pans_instead_of_grabbing_a_zoom(self, ix):
        """A purely VERTICAL fractional swipe is a scroll: it pans following the fingers and
        must not touch the scale."""
        swipe = ix['wheel']['verticalTrackpadSwipe']
        assert (swipe['panX'], swipe['panY']) == (0, 37.5), 'a vertical swipe must pan, following the fingers'
        assert swipe['zoom'] == 1, 'a two-finger scroll that happens to be vertical must not zoom'

    def test_ctrl_or_pinch_wheel_zooms_in(self, ix):
        """Holding Ctrl (a trackpad pinch in Chrome/Edge, or a deliberate ctrl-wheel)
        scales up about the cursor and updates the readout."""
        pinch = ix['wheel']['ctrlPinch']
        assert pinch['zoom'] > 1
        assert pinch['status'] == '111%'

    def test_a_mouse_wheel_notch_zooms_and_does_not_pan(self, ix):
        """A lone integer, pure-vertical notch with no trackpad evidence is a mouse wheel:
        it zooms (down = out) — the scale moves, which is what separates it from a trackpad
        scroll (whose scale stays 1). Zooming about the cursor also shifts the pan, as it
        must, so the scale is the assertion, not the pan."""
        wheel = ix['wheel']['mouseWheel']
        assert wheel['zoom'] < 1, 'a downward mouse wheel (deltaY > 0) must zoom out'

    def test_a_diagonal_scroll_never_locks_an_axis(self, ix):
        """The regression: a two-finger diagonal whose horizontal delta flickers to 0 on
        one event (with the vertical delta momentarily unchanged, so only the sticky
        stream can rescue it) must pan through every event, never split into a zoom. The
        negated sums prove all three panned: X -(12+0+9), Y -(6+6+4), scale untouched."""
        diag = ix['wheel']['diagonalNoLock']
        assert (diag['panX'], diag['panY']) == (-21, -16), 'the horizontal-zero event stole an axis'
        assert diag['zoom'] == 1, 'a trackpad diagonal must never zoom mid-scroll'


class TestCameraAnimation:
    """适应 (resetView) and the outline jump (centerOnNode) must GLIDE the camera, not
    teleport it — while still committing the final state synchronously, and cancelling
    the glide the instant the user takes over with a scroll."""

    def test_fit_arms_a_camera_glide_and_commits_its_target(self, ix):
        assert ix['view_anim']['resetArmsGlide'] is True, '适应 set no transform transition to ease along'
        assert ix['view_anim']['resetCommittedTarget'] is True, '适应 did not commit a clamped zoom synchronously'

    def test_the_outline_jump_arms_the_same_glide(self, ix):
        assert ix['view_anim']['focusArmsGlide'] is True, 'the outline jump did not ease the camera'

    def test_a_manual_scroll_cancels_the_glide(self, ix):
        """A user gesture wins over an in-flight animation: the transition is removed
        so panning tracks the state immediately instead of rubber-banding behind it."""
        assert ix['view_anim']['gestureCancelsGlide'] is True, 'a scroll left the camera glide running'

    def test_zero_duration_snaps_without_arming_a_glide(self, ix):
        """The reduced-motion path (0 ms) applies the target but sets no transition."""
        snap = ix['view_anim']['instantSnap']
        assert snap['animating'] is False, 'a 0 ms camera move armed a glide'
        assert (snap['panX'], snap['zoom']) == (120, 1), 'the instant path did not apply the target synchronously'


class TestNewWorkflow:
    """「新建」 is a fresh canvas, not the old one with its nodes deleted: the outline sidebar
    must empty immediately (it is otherwise rebuilt only at saveState, which a bare 新建 never
    runs) and the camera must reset to 100% instead of inheriting the last zoom/pan."""

    def test_the_outline_empties_at_once(self, ix):
        new = ix['newfile']
        assert new['rowsBefore'] == 2, 'the scenario did not start with a populated outline'
        assert new['rowsAfter'] == 0, '新建 left the previous canvas rows on screen'
        assert new['emptyShown'] is True, 'the sidebar did not switch to its empty state'

    def test_the_camera_resets_to_one_hundred_percent(self, ix):
        new = ix['newfile']
        assert new['zoomAfter'] == 1, '新建 kept the previous zoom'
        assert new['statusAfter'] == '100%', 'the readout did not reset with the camera'
        assert new['panAfter'] == [0, 0], '新建 kept the previous pan'
        assert new['nodesAfter'] == 0 and new['selectedAfter'] is None


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

    def test_deselecting_the_graph_clears_the_sidebar_highlight(self, ix):
        """Clicking empty canvas (no node selected) must not leave the last row lit."""
        assert ix['outline_deselect']['activeAfterDeselect'] == 0

    def test_a_multi_selection_lights_every_selected_row(self, ix):
        """The sidebar must agree with the graph: canvas.js highlights the whole group, so the
        outline lights every selected row, not only the last-clicked anchor."""
        m = ix['outline_multi']
        assert m['activeIds'] == m['selected'], 'the outline lit only the anchor, not the group'
        assert len(m['activeIds']) == 2, 'both selected nodes must be highlighted'

    def test_the_outline_filters_to_matching_rows(self, ix):
        """setFilter narrows the list by label/type/tag; clearing restores the whole map.

        Matching the type abbreviation (not just the label) is deliberate: a Chinese canvas
        still answers "src"/"SRC", so a finder written in one language is not stranded.
        """
        f = ix['outline_filter']
        assert f['unfiltered'] == 3, 'the scenario did not start with three nodes'
        assert f['filtered'] == [f['disabledId']], 'only the visualize node should match "viz"'
        assert f['inputCleared'] == 3, 'clearing the finder must restore every row'

    def test_the_finder_is_driven_by_the_real_input_event(self, ix):
        """The filter is wired to the box's own 'input' listener (Outline.init), not only to
        setFilter: a keystroke routed through that listener narrows to the one source node."""
        assert ix['outline_filter']['inputDriven'] == 1, 'typing "source" in the box did not filter to the source row'

    def test_an_impossible_query_shows_no_match_not_no_nodes(self, ix):
        """A filter matching nothing must say NO-MATCH, not reuse the empty-canvas NO-NODES
        wording — otherwise "every node filtered out" is indistinguishable from "no nodes"."""
        assert ix['outline_filter']['noMatchText'] == 'NO-MATCH'

    def test_ctrl_f_reveals_the_finder_without_stealing_the_selection(self, ix):
        """Ctrl/Cmd+F expands a collapsed sidebar and leaves the selection intact — it is the
        finder, not the fold (the fold stays on plain `f`, covered by the canvas fold tests)."""
        f = ix['outline_filter']
        assert f['panelExpanded'] is True, 'Ctrl+F did not reveal a collapsed outline'
        assert f['ctrlLeftSelected'] is True, 'Ctrl+F changed the selection'

    def test_selecting_a_node_on_the_canvas_lights_its_sidebar_row(self, ix):
        # The selection sync must be bidirectional: a graph click drives the sidebar highlight too.
        assert ix['outline_reselect']['activeIds'] == ['node-1']

    def test_an_empty_canvas_survives_the_request(self, ix):
        assert ix['auto_layout_empty']['survived'] is True


class TestPaletteKeyboardAdd:
    """A drag is mouse-only; these are the keyboard/pointer routes into the canvas."""

    def test_a_palette_item_is_a_real_button(self, ix):
        """Each item carries role=button, is focusable (tabindex 0) and names the key that
        adds it — the affordance a keyboard user needs to find the route at all."""
        a = ix['palette_keyboard']['attrs']
        assert a['role'] == 'button', 'a palette item is not announced as a button'
        assert a['tabindex'] == 0, 'a palette item cannot be reached by Tab'
        assert a['title'] == 'ADD-HINT', 'the item does not advertise its keyboard action'

    def test_enter_adds_the_node_and_selects_it(self, ix):
        p = ix['palette_keyboard']
        assert p['addedByEnter'] == 1, 'Enter on a palette item added no node'
        assert p['enterIsSource'] is True, 'the added node is not the source type the item names'
        assert p['toastEnter'] == 'Data Source added', 'adding did not toast the node type'

    def test_space_and_a_plain_click_add_through_the_same_route(self, ix):
        """Space is the other key on a button, and a click is the pointer equivalent of that
        press — all three must land one node, and a blank type must add none."""
        p = ix['palette_keyboard']
        assert p['addedBySpace'] == 1, 'Space added no node'
        assert p['addedByClick'] == 1, 'a click on a palette item added no node'
        assert p['emptyTypeNull'] is True, 'an empty palette type must be a no-op, not a node'


class TestClipboardDragToCanvas:
    """A clipboard NODE row drags onto the canvas the way a palette item does — through
    the SAME paste funnel, so a dragged node comes out byte-identical to a clicked paste,
    lands at the drop point, and never turns a text row into a node."""

    def test_a_node_row_is_draggable(self, ix):
        assert ix['clip_drag_to_canvas']['rowDraggable'] == 'true', 'a node row cannot be dragged'

    def test_the_drag_hands_the_entry_id_to_a_private_mime(self, ix):
        assert ix['clip_drag_to_canvas']['dragWroteClipId'] is True

    def test_dropping_pastes_one_node_carrying_params_and_name(self, ix):
        c = ix['clip_drag_to_canvas']
        assert c['pastedOne'] is True, 'the drag-drop pasted a different number of nodes'
        assert c['pastedKeyword'] == 'DRAGME', 'the dropped node lost its params'
        assert c['pastedTitle'] == '源Z', 'the dropped node lost its name'

    def test_the_palette_route_still_adds_a_node_of_that_type(self, ix):
        """Widening the drop handler must not break what was already there."""
        c = ix['clip_drag_to_canvas']
        assert c['paletteAddedOne'] is True
        assert c['paletteIsOutput'] is True

    def test_a_drop_carrying_nothing_adds_nothing(self, ix):
        assert ix['clip_drag_to_canvas']['emptyAddsNothing'] is True

    def test_a_text_row_is_not_draggable_and_drags_no_node(self, ix):
        c = ix['clip_drag_to_canvas']
        assert c['textRowNotDraggable'] is True, 'a text row must not advertise itself as draggable'
        assert c['textDragWroteNothing'] is True, 'dragging a text row must put nothing on the canvas'


class TestNodeClipboardShortcuts:
    """Ctrl+C / Ctrl+V / arrow-nudge — the keyboard routes that the copy/paste menu already
    served. They must reach the SAME shared methods, so a pasted node comes out identical
    whichever door it entered."""

    def test_ctrl_c_copies_the_selected_nodes_type_name_and_params(self, ix):
        c = ix['node_clipboard']['clip']
        assert c == {'type': 'source', 'title': '源A', 'keyword': 'KEEPME'}, c
        assert ix['node_clipboard']['copyToast'] == 'COPIED'

    def test_ctrl_v_pastes_an_offset_copy_carrying_the_name_and_params(self, ix):
        c = ix['node_clipboard']
        assert c['addedByPaste'] == 1, 'Ctrl+V added no node'
        assert c['pasted']['title'] == '源A', 'the copy lost the name the source was given'
        assert c['pasted']['keyword'] == 'KEEPME', 'the copy did not carry the source params'
        assert c['pasted']['leftDelta'] == 24, 'the copy must land a cascade step off the original'
        assert c['pasteToast'] == 'PASTED'

    def test_arrow_keys_nudge_the_selected_node(self, ix):
        c = ix['node_clipboard']
        assert c['nudgeStep'] == 10, 'ArrowRight must move the node 10px'
        assert c['fineStep'] == 1, 'Shift+Arrow must move the node 1px (fine)'

    def test_the_shortcuts_refuse_when_there_is_nothing_to_act_on(self, ix):
        c = ix['node_clipboard']
        # Ctrl+C with no selection must not overwrite the clipboard...
        assert c['clipUntouchedWithNoSelection'] is True
        # ...and Ctrl+V with an empty clipboard must add no node.
        assert c['emptyPasteAddsNothing'] is True


class TestNodeJsonShare:
    """Copy a node to a JSON snippet on the OS clipboard, and add one back — cross-canvas
    share. Import reuses the in-canvas paste path, so a snippet must come out identical to a
    hand-copy, and a malformed snippet must refuse (no broken node, no silent DONE)."""

    def test_copy_writes_the_node_as_a_roundtrippable_json_snippet(self, ix):
        c = ix['node_json']['copy']
        assert c['ok'] is True
        assert c['wrote'] == 1, 'clipboard.writeText was not called exactly once'
        assert c['parsed'] == {'type': 'process', 'title': '处理源', 'params': {'operation': 'keyword'}}, c['parsed']
        assert c['toast'] == 'JSON-COPIED'

    def test_import_adds_a_node_carrying_the_snippets_type_name_and_params(self, ix):
        imp = ix['node_json']['imp']
        assert imp['added'] == 1, 'importing a valid snippet added no node'
        assert imp['madeNode'] is True
        assert imp['node'] == {'type': 'source', 'title': '导入源', 'keyword': 'IMP'}, imp['node']

    def test_garbage_json_is_refused_and_adds_no_node(self, ix):
        bad = ix['node_json']['bad']
        assert bad['added'] == 0 and bad['nullReturn'] is True
        assert bad['toast'] == 'JSON-INVALID'

    def test_an_unknown_node_type_is_refused_not_minted(self, ix):
        ut = ix['node_json']['unknownType']
        assert ut['added'] == 0, 'a made-up node type must not create a broken node'
        assert ut['nullReturn'] is True
        assert ut['toast'] == 'JSON-INVALID'

    def test_cancelling_the_import_dialog_adds_nothing(self, ix):
        cancel = ix['node_json']['cancelled']
        assert cancel['added'] == 0 and cancel['nullReturn'] is True


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

    def test_a_node_is_a_named_group_for_the_screen_reader(self, ix):
        """Every node box announces as a group whose name is its visible title, so Tab
        reaching it says "Data Source", not a run of unlabeled buttons."""
        created = ix['rename']['created']
        assert created['role'] == 'group', 'the node box has no ARIA role'
        assert created['aria'] == 'Data Source', 'the accessible name is not the type label'

    def test_the_accessible_name_follows_a_rename(self, ix):
        assert ix['rename']['typed']['aria'] == '我的爬虫', 'aria-label still says the old name after rename'

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
        entry that did nothing — reads as broken, not as "nothing copied yet". And the
        batch clipboard is a SECOND shape: a multi-select copy lands on _clipboardNodes
        and clears _clipboardData, so the item must check both shapes or it hides itself
        right after a copy that pastes perfectly well by Ctrl+V."""
        assert ix['context_menu']['pasteVisible'] == 'none', ix['context_menu']
        assert ix['context_menu']['paste_after_copy'] == 'block'
        assert ix['batch_clipboard_shape'] == {'nodes': True, 'data': False}, (
            'a batch copy must land on the nodes clipboard, not the single one'
        )
        assert ix['paste_after_batch_copy'] == 'block', 'the menu hid its own paste after a multi-select copy'

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


class TestKeyboardConnect:
    """The wire is now reachable without a pointer. `connectNodes` is the one synchronous
    model mutation the drag path and the L link-mode share, so these assert both the seam
    (a connection created exactly once, self/duplicate refused, the tokenize↔visualize
    coupling preserved) and the keyboard gesture itself."""

    def test_connect_nodes_creates_once_and_refuses_self_and_duplicate(self, ix):
        made = ix['keyboard_connect']['direct']
        assert made['firstOk'] is True
        assert made['dupOk'] is True and made['selfOk'] is True
        assert made['count'] == 1, 'a duplicate or a self-edge must add no wire'

    def test_connect_nodes_keeps_the_tokenize_visualize_coupling(self, ix):
        """The output_mode rewrite moved into connectNodes with the extraction; if it had
        stayed only in finishConnection, the keyboard path would wire the pair and leave the
        tokenizer in a mode the visualizer cannot consume."""
        assert ix['keyboard_connect']['tokenizeCoupling']['mode'] == 'word_freq'

    def test_link_mode_arms_on_first_key_and_commits_on_the_second(self, ix):
        lm = ix['keyboard_connect']['linkMode']
        assert lm['armedFrom'] is True, 'the first L must remember the wire start'
        assert lm['armedToast'] == 'LINK-HINT', 'arming a wire needs a visible next step'
        assert lm['created'] is True
        assert lm['clearedAfter'] is True, 'a committed wire must leave no stuck mode'

    def test_link_key_without_a_selection_arms_nothing(self, ix):
        ns = ix['keyboard_connect']['linkNoSelection']
        assert ns['linkFrom'] is None
        assert ns['toast'] == 'LINK-NOSEL'

    def test_escape_clears_an_armed_link_start(self, ix):
        esc = ix['keyboard_connect']['linkEscapeClears']
        assert esc['armed'] is True
        assert esc['afterEscape'] is None, 'Escape must abandon a half-started wire'

    def test_re_pressing_the_key_on_the_same_start_cancels_without_wiring(self, ix):
        cancel = ix['keyboard_connect']['linkSameStartCancel']
        assert cancel['connections'] == 0
        assert cancel['linkFrom'] is None

    def test_a_cancelled_link_mode_can_be_started_again(self, ix):
        """Cancel must not leave a flag that makes the next L a no-op — otherwise the gesture
        silently dies after one abort."""
        assert ix['keyboard_connect']['linkRetriable']['armedAgain'] is True


class TestMinimap:
    """The corner overview. The geometry is pure (bounds/scale/click→world) and the drawing is
    an innerHTML string, so the harness checks both without a rendered canvas — and pins that
    clicking the minimap is a VIEW change that never touches the model or the undo history."""

    def test_an_empty_canvas_has_no_minimap(self, ix):
        m = ix['minimap']['empty']
        assert m['boundsNull'] is True
        assert m['cleared'] is True, 'nothing to draw must not leave stale boxes'

    def test_bounds_span_every_node(self, ix):
        b = ix['minimap']['bounds']
        assert (b['minX'], b['minY']) == (0, 0)
        assert (b['maxX'], b['maxY']) == (1200, 700), 'both boxes, sized, not just their corners'
        assert ix['minimap']['scale_positive'] is True

    def test_click_maps_back_to_the_world_point(self, ix):
        rt = ix['minimap']['click_roundtrip']
        assert rt['dx'] < 1e-6 and rt['dy'] < 1e-6, 'the draw map and the click inverse must agree'

    def test_the_map_draws_one_box_per_node_plus_a_viewport(self, ix):
        assert ix['minimap']['render'] == {'nodes': 2, 'view': 1}

    def test_a_disabled_node_shades_in_the_map(self, ix):
        assert ix['minimap']['disabled'] is True

    def test_clicking_recentres_without_moving_model_or_history(self, ix):
        c = ix['minimap']['centre']
        assert c['moved'] is True
        assert c['panX'] == 100, 'centring world x=500 in a 1200 box at zoom 1 puts panX at 600-500'
        assert c['stateUnchanged'] is True, 'a camera move must not enter the model'
        assert c['historyUnchanged'] is True, 'a camera move must not be an undo step'


class TestMultiSelect:
    """Shift-click / marquee selection and the batch operations that follow. Selection is a view
    concern (never in getState/history), so a multi-select must not become undo steps, and a batch
    delete is ONE edit with ONE toast."""

    def test_shift_click_accumulates_the_selection(self, ix):
        s = ix['multi_select']['shiftAdd']
        assert len(s['set']) == 2
        assert s['anchor'] == s['set'][-1]
        assert len(s['highlighted']) == 2, 'both boxes light, not just the last'

    def test_a_plain_click_resets_to_one(self, ix):
        assert len(ix['multi_select']['plainResets']['set']) == 1

    def test_batch_nudge_moves_every_selected_box(self, ix):
        n = ix['multi_select']['batchNudge']
        assert n['aLeft'] == 10 and n['bLeft'] == 410, 'both selected nodes moved +10'

    def test_batch_delete_is_one_edit_with_one_toast(self, ix):
        d = ix['multi_select']['batchDelete']
        assert len(d['remaining']) == 1, 'the two selected go, the third survives'
        assert d['toast'] == 'toast.nodesDeleted', 'the plural path, not the single-node one'
        assert d['setAfter'] == [], 'a deleted node leaves the selection set'

    def test_the_marquee_selects_the_nodes_it_overlaps(self, ix):
        m = ix['multi_select']['marquee']
        assert m['set'] == m['expected'] and len(m['set']) == 2

    def test_the_marquee_lights_nodes_as_it_covers_them_not_only_on_release(self, ix):
        """The band must answer while it is dragged, not only when the mouse is let go: a node
        the band has just swept over lights up mid-drag, and shrinking the band past a node
        un-lights it just as fast. The node outside the band (node-3) is never selected."""
        m = ix['multi_select']['marqueeLive']
        assert m['liveWide'] == m['coveredAB'], 'a node covered mid-drag must light before release'
        assert m['liveShrunk'] == m['onlyA'], 'shrinking the band must un-light the node it no longer covers'
        assert m['afterUp'] == m['onlyA'], 'the released set matches the live set at that point'
        assert m['untouchedC'] not in m['liveWide'], 'a node outside the band must never be selected'

    def test_a_background_click_that_never_moved_selects_nothing(self, ix):
        assert ix['multi_select']['clickNoDrag']['set'] == []

    def test_batch_copy_then_paste_adds_all_as_one_undo_step(self, ix):
        b = ix['multi_select']['batchPaste']
        assert b['clipLen'] == 2, 'copy of a 2-node selection must fill a 2-entry clipboard'
        assert b['copyToast'] == 'NODES-COPIED', 'the batch (not single) copy toast must fire'
        assert b['added'] == 2, 'pasting the batch must add both nodes'
        assert b['singleUndoStep'] == 1, 'a batch paste is ONE undo step, not one per node'
        assert b['selectedNew'] is True, 'the paste must select the new copies, not the originals'
        assert b['pasteToast'] == 'NODES-PASTED'

    def test_a_same_type_selection_writes_one_param_to_every_member(self, ix):
        a = ix['multi_select']['applyToAll']
        assert a['targets'] == 3
        assert a['all'] == ['群发到全部'] * 3, 'the panel write must land on all selected same-type nodes'

    def test_a_mixed_selection_does_not_write_the_param_onto_other_types(self, ix):
        m = ix['multi_select']['mixedSelection']
        assert m['targets'] == 0, 'multiEditTargets must refuse a mixed group'
        assert m['processGot'] == '只应落在处理节点'
        assert m['sourceUntouched'] is True, 'the source node must keep its own (absent) keyword'

    def test_dragging_a_selected_box_moves_the_whole_group(self, ix):
        """Pressing a member of a live group must move the group, not just the grabbed box —
        the batch-op contract that shift-click/marquee/nudge/delete all already honour. A rigid
        translation keeps every member's relative layout and persists every one."""
        d = ix['multi_select']['batchDrag']
        assert d['aLeft'] == 100 and d['aTop'] == 100, 'the grabbed box moved'
        assert d['bLeft'] == 500 and d['bTop'] == 100, 'its group-mate moved by the same delta'
        assert d['bLeft'] - d['aLeft'] == 400, 'the group keeps its 400px separation'
        assert d['persistedA'] == 100 and d['persistedB'] == 500, 'the whole move persists, not one box'


class TestRightPressKeepsTheSelection:
    """pointerdown fires for the right button too, and used to reset a live multi-selection to
    the single pressed node before the menu even opened — so 复制/对齐 on a group was silently
    narrowed to one. The right button is the menu's gesture, never a drag."""

    def test_a_right_press_on_a_group_member_keeps_the_whole_group(self, ix):
        r = ix['right_press_on_group_member']
        assert r['setAfter'] == r['expected'], 'the right-press collapsed the multi-selection'
        assert r['startedDrag'] is False, 'a right-press must not start a drag'
        assert r['menuSetAfter'] == r['expected'], 'opening the menu changed the selection'

    def test_a_right_press_on_an_unselected_node_selects_just_it(self, ix):
        r = ix['right_press_on_unselected']
        assert r['set'] == [r['anchor']] and len(r['set']) == 1, 'a fresh right-press selects only itself'
        assert r['startedDrag'] is False


class TestClipboardDrawer:
    """The persisted clipboard board is a SECOND thing beside the working slots: a copy
    still sets `canvas._clipboardData`/`_clipboardNodes` (so Ctrl+V is unchanged), and only
    additionally appends one entry to a localStorage board. Paste from the board must funnel
    through the SAME `canvas._pasteAt` the keyboard/menu use — never a second paste body."""

    def test_a_single_copy_records_one_node_entry_without_stealing_the_toast(self, ix):
        s = ix['clipboard']['singleCopy']
        assert s['entries'] == 1 and s['kind'] == 'node'
        assert s['slotStillSet'] is True, 'the working slot must stay set (Ctrl+V unchanged)'
        assert s['toast'] == 'COPIED', 'Clipboard.add is silent — it must not overwrite the copy toast'

    def test_a_batch_copy_records_one_nodes_entry_sized_to_the_selection(self, ix):
        b = ix['clipboard']['batchCopy']
        assert b['entries'] == 1 and b['kind'] == 'nodes' and b['payloadLen'] == 2

    def test_pasting_a_board_entry_uses_the_shared_funnel_and_its_own_key(self, ix):
        p = ix['clipboard']['paste']
        assert p['added'] == 1, 'pasting a stored node adds exactly one node'
        assert p['keyword'] == 'ONLYCLIP', 'the paste must carry the copied param (one paste path)'
        assert p['historyGrew'] is True, 'a board paste is an undo step'
        assert p['boardKeySeparate'] is True, 'the board lives in crawler_clipboard, not the draft'

    def test_rename_pin_and_remove_mutate_the_board(self, ix):
        m = ix['clipboard']['mutations']
        assert m['renamed'] is True and m['pinned'] is True
        assert m['afterRemove'] == 0, 'remove takes the single entry out'

    def test_the_board_trims_to_the_cap(self, ix):
        assert ix['clipboard']['cap']['len'] == 50, 'CLIPBOARD_MAX bounds the history'

    def test_eviction_spares_a_pinned_entry(self, ix):
        e = ix['clipboard']['pinImmune']
        assert e['len'] == 50, 'still within the cap ...'
        assert e['keepSurvives'] is True, '... and an unpinned entry would have been evicted first'

    def test_search_filters_the_rendered_rows(self, ix):
        f = ix['clipboard']['filter']
        assert f['alphaShown'] is True and f['betaHidden'] is True

    def test_clear_all_empties_the_board_with_a_toast(self, ix):
        c = ix['clipboard']['clear']
        assert c['len'] == 0 and c['toast'] == 'CLIP-CLEARED'

    def test_add_text_records_a_text_entry(self, ix):
        a = ix['clipboard']['addText']
        assert a['entry'] is True and a['kind'] == 'text' and a['toast'] == 'CLIP-ADDED'

    def test_a_node_json_text_inserts_a_node(self, ix):
        i = ix['clipboard']['insertText']
        assert i['added'] == 1 and i['keyword'] == 'INS'

    def test_a_non_json_text_is_refused_by_name_and_mints_no_node(self, ix):
        b = ix['clipboard']['insertBad']
        assert b['added'] == 0 and b['nullReturn'] is True and b['toast'] == 'JSON-INVALID'

    def test_copy_text_writes_the_os_clipboard(self, ix):
        c = ix['clipboard']['copyText']
        assert c['wrote'] == 'to-os' and c['toast'] == 'CLIP-TEXT'

    def test_the_board_survives_a_reload_read(self, ix):
        p = ix['clipboard']['persist']
        assert p['same'] is True and p['reloadedLen'] == 1


class TestCanvasCycleRefusal:
    def test_closing_a_loop_is_refused_at_the_connect_seam(self, ix):
        c = ix['cycle']
        assert c['chain'] == {'abOk': True, 'bcOk': True}
        assert c['refused']['ok'] is False, 'a wire that forms a cycle must never be written'
        assert c['refused']['count'] == 2, 'the refusal writes nothing'
        assert c['refused']['toast'] == 'CONN-CYCLE'

    def test_the_reachability_helper_follows_directed_wires(self, ix):
        r = ix['cycle']['reaches']
        assert r['aToC'] is True and r['cToA'] is False

    def test_a_normal_connection_still_succeeds_after_a_refusal(self, ix):
        assert ix['cycle']['normalStillWorks'] is True


class TestCanvasAlign:
    def test_align_left_collapses_to_the_smallest_x_as_one_undo_step(self, ix):
        a = ix['align']
        assert a['leftResult'] is True and a['leftPositions'] == [0, 0, 0]
        assert a['historyOneStep'] == 1, 'one alignment must be one undo point'
        assert a['toast'] == 'ALIGN-APPLIED'

    def test_align_top_collapses_to_the_smallest_y(self, ix):
        assert ix['align']['topPositions'] == [0, 0, 0]

    def test_distribute_fixes_the_extremes_and_spaces_the_centres(self, ix):
        d = ix['align']['distribute']
        assert d['firstUnchanged'] is True and d['lastUnchanged'] is True and d['evenSpacing'] is True

    def test_fewer_than_two_selected_is_a_no_op(self, ix):
        assert ix['align']['singleNoop'] is True


class TestZoomAndHelpKeys:
    def test_plus_minus_and_zero_are_bound_to_zoom(self, ix):
        z = ix['zoom_help']
        assert z['zoomIn'] is True and z['zoomOut'] is True and z['fitKeeps100'] is True

    def test_question_mark_opens_help_and_escape_closes_it(self, ix):
        h = ix['zoom_help']['helpToggle']
        assert h['opened'] is True and h['closedOnEscape'] is True


class TestCrossTabClipboard:
    def test_a_storage_event_pulls_another_tabs_writes(self, ix):
        p = ix['crossTabClipboard']['pulledFromStorage']
        assert p['before'] == 0 and p['after'] == 1 and p['label'] == 'REMOTE'

    def test_an_unrelated_key_is_ignored(self, ix):
        assert ix['crossTabClipboard']['unrelatedKeyIgnored'] is True


class TestKeyboardNavigation:
    """W/A/S/D move the selection to the nearest node in that direction; arrows still
    nudge (pinned by the clipboard scenario). Enter opens the selected node's panel."""

    def test_wasd_moves_selection_to_the_nearest_node_in_that_direction(self, ix):
        n = ix['keyboard_navigation']
        ids = n['ids']
        assert n['afterD'] == ids['B'], 'from A, D selects the node to the right'
        assert n['afterA'] == ids['A'], 'from B, A returns left'
        assert n['afterS'] == ids['C'], 'from A, S selects the node below'
        assert n['afterW'] == ids['A'], 'from C, W returns up'

    def test_navigation_never_moves_a_node(self, ix):
        """Traversal is a selection change, not a position change — a node nudged by a
        stray W would silently rewrite the layout and cost an undo step."""
        assert ix['keyboard_navigation']['nudgedByWasd'] is False

    def test_enter_opens_the_selected_node_but_not_from_a_focused_button(self, ix):
        n = ix['keyboard_navigation']
        assert n['enterForNode'] == 1, 'Enter on a selected node opens its settings once'
        assert n['enterFromButton'] == 1, 'Enter while a button is focused must not also fire'

    def test_enter_toggles_the_panel_closed_on_the_canvas(self, ix):
        """The reported bug: Enter only opened. A second Enter on the same selected node must
        close it — editNode is the shared toggle the gear button already uses."""
        assert ix['keyboard_navigation']['enterClosesSecond'] is True

    def test_enter_inside_the_panel_closes_it_but_owns_enter_for_fields_that_need_it(self, ix):
        """A fresh open drops the caret into the first field, so the second Enter lands inside
        the panel; it closes there too — yet never steals Enter from a textarea (a newline) or
        a button (its own activation)."""
        n = ix['keyboard_navigation']
        assert n['reopenedForPanel'] is True
        assert n['panelFieldEnterCloses'] is True, 'Enter in a panel field did not close the panel'
        assert n['textareaKeepsOpen'] is True, 'Enter in a textarea must keep the panel open'
        assert n['panelButtonKeepsOpen'] is True, 'Enter on a panel button must keep the panel open'

    def test_wasd_with_nothing_selected_seeds_a_selection(self, ix):
        assert ix['keyboard_navigation']['seededFromEmpty'] is True

    def test_a_taller_node_in_the_same_row_is_not_mistaken_for_one_below(self, ix):
        """Down navigation is gated on box edges: a source node that shares the anchor's
        top but is taller has a lower centre, and centre distance alone would wrongly
        steer 'S' onto it instead of the node genuinely below."""
        assert ix['keyboard_navigation']['downToBelow'] is True
