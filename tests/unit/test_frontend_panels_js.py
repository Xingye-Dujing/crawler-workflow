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

import shutil
from pathlib import Path

import pytest
from node_runner import run_node

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_panels.mjs'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]


@pytest.fixture(scope='module')
def results():
    proc = run_node(str(HARNESS), str(JS_DIR / 'workflow.js'), str(JS_DIR / 'app.js'))
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


PANELS = ['console-panel', 'runs-panel', 'exports-panel']


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


def test_the_dock_helper_is_reachable(results):
    import json

    assert json.loads(results)['dockedList'] == 'helper present'


def test_the_cookie_dialog_is_bounded_by_the_viewport_not_fixed_pixels(results):
    import json

    assert json.loads(results)['cookieBounds'] == 'viewport bounds', (
        'a fixed maxH clips the six-platform cookie guidance with no way to grow'
    )
