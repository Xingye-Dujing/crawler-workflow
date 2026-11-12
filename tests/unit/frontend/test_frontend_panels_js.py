"""Tests for the bottom-docked panel trio (console / 运行记录 / 导出产物).

Loads the real workflow.js + app.js in node and drives their toggles. Pinned:

* opening any one of the three closes the other two **and clears their inline
  height** — a panel closed by dropping `.open` alone stays visually expanded,
  because the resize handle's inline height beats the CSS `height: 0`, and two
  panels then overlap in the same slot;
* the export panel really carries a resize handle (it is docked like the other
  two, so it has to be resizable too);
* the cookie dialog's resize ceiling follows the viewport. It used to be a fixed
  500×500 px, while the dialog's content is far taller than that — so dragging
  the handle snapped the panel shorter and then refused to grow, hiding content
  behind an unremovable cap.
"""

import re
import shutil
from pathlib import Path

import pytest
from frontend_catalogue import with_catalogue
from node_runner import run_node

REPO = Path(__file__).resolve().parents[3]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_panels.mjs'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]


@pytest.fixture(scope='module')
def results():
    proc = run_node(
        str(HARNESS),
        *with_catalogue(
            [
                JS_DIR / 'workflow.js',
                JS_DIR / 'app.js',
                JS_DIR / 'schedules.js',
                # The real settings panel: its dock rule (closeDockedPanels + height reset)
                # is exactly what this matrix exists to prove, and a stub cannot prove it.
                JS_DIR / 'panels' / 'settings-panel.js',
            ]
        ),
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


PANELS = [
    'console-panel',
    'runs-panel',
    'exports-panel',
    'dataset-panel',
    'workflows-panel',
    'cookies-panel',
    'lexicon-panel',
    'schedules-panel',
    'processes-panel',
    'biblio-panel',
    'settings-panel',
]


@pytest.mark.parametrize('target', PANELS)
def test_opening_one_panel_leaves_only_it_open(results, target):
    import json

    out = json.loads(results)
    assert out[target]['opened'] == [target], f'{target} did not take the slot exclusively'


@pytest.mark.parametrize('target', PANELS)
def test_a_closed_panel_loses_its_inline_height(results, target):
    """The CSS hides a docked panel with `height: 0`; a leftover inline height
    overrides it, which is the whole reason two panels could overlap."""
    import json

    out = json.loads(results)
    assert out[target]['staleHeights'] == []


def test_the_export_panel_can_be_resized(results):
    import json

    assert json.loads(results)['exportHandle'] is True


@pytest.mark.parametrize('handle', ['datasetHandle', 'workflowsHandle', 'lexiconHandle'])
def test_a_docked_panel_without_a_handle_cannot_be_grown(results, handle):
    """The CSS hides a dock with `height: 0`; the handle is the only way to give a
    panel a real height, so a panel added to the dock list without one is stuck."""
    import json

    assert json.loads(results)[handle] is True


def test_the_matrix_names_exactly_the_panels_the_dock_closes():
    """A panel added to ``DOCKED_PANELS`` but not here is a dock nobody drives."""
    workflow = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
    block = workflow.split('var DOCKED_PANELS', 1)[1].split('];', 1)[0]
    docked = set(re.findall(r"'([^']+)'", block))
    assert docked == set(PANELS), f'dock matrix drifted: {sorted(docked ^ set(PANELS))}'


def test_the_dock_helper_is_reachable(results):
    import json

    assert json.loads(results)['dockedList'] == 'helper present'


def test_the_cookie_dialog_is_bounded_by_the_viewport_not_fixed_pixels(results):
    import json

    assert json.loads(results)['cookieBounds'] == 'viewport bounds', (
        'a fixed maxH clips the six-platform cookie guidance with no way to grow'
    )


def test_the_lexicon_search_box_keeps_focus_across_a_filter_keystroke(results):
    """render() rebuilds the toolbar on every character; without re-focusing the NEW box the
    caret fell to <body> after one key and the rest of the typing hit canvas shortcuts."""
    import json

    box = json.loads(results)['lexiconFilter']
    assert box['focused'] is True, 'the rebuilt search box did not take focus back'
    assert box['value'] == 'a', 'the filter value did not reach the rebuilt box'
