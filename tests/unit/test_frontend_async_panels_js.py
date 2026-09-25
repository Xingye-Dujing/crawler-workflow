"""Panels whose content arrives after an await, driven in node.

Three rules, each of which used to be broken in a way the user could only see as
"nothing happened":

* a request must be answered into the element the page holds NOW, not the one that
  existed when the request started (`renderResumeSettings`, `dashboard._renderCell`,
  `runsManager.detail` — the last is pinned in `test_frontend_js.py`);
* an answer with nowhere to go must also leave its bookkeeping alone: registering a
  chart instance for a cell that is gone leaves it resized on every window resize and
  never disposed;
* a switch in the request body is READ (`boolParam`), not tested for truthiness —
  `!!'false'` is true, and the settings panel wrote that text for a cleared box.

Each case is measured twice, calm and raced: a guard that refused everything would pass
a file that only ever tests the refusal.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_async_panels.mjs'


@pytest.fixture(scope='module')
def panels() -> dict:
    proc = run_node(str(HARNESS), str(JS_DIR / 'workflow.js'), str(JS_DIR / 'canvas.js'))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


class TestResumeDropdown:
    def test_the_two_selects_appear_when_the_panel_is_left_alone(self, panels):
        assert panels['resume']['calm']['drawn'] is True, 'the ordinary case regressed'

    def test_they_still_appear_when_a_redraw_lands_mid_flight(self, panels):
        """Editing any field of this node rewrites the form while the run list is in
        flight, and the holder the request started with is off the page by the answer.
        The lookup now happens after the await, so the dropdown is drawn into what the
        user is looking at instead of into an orphan.
        """
        raced = panels['resume']['raced']
        assert raced['asked'] == 2, f'the scenario did not redraw mid-flight: {raced}'
        assert raced['drawn'] is True, 'the answer went to a holder nobody displays'
        assert raced['holderNode'] == 'res-1', raced


class TestDashboardCells:
    def test_a_chart_is_drawn_when_its_cell_is_still_on_the_board(self, panels):
        calm = panels['dash']['calm']
        assert calm['inits'] == 1, calm
        assert calm['instances'] == 1, calm

    def test_a_cell_replaced_mid_flight_is_neither_painted_nor_registered(self, panels):
        """`echarts.init` on a detached cell shows nothing and keeps the instance
        forever, so the honest answer is to do neither.
        """
        raced = panels['dash']['raced']
        assert raced['inits'] == 0, f'a chart was initialised off the page: {raced}'
        assert raced['instances'] == 0, 'the instance was kept for a cell that no longer exists'


class TestSwitchInTheRequestBody:
    """What the chart request carries for each spelling of the tokenize box."""

    @pytest.mark.parametrize(
        ('stored', 'expected'),
        [
            ('"false"', False),
            ('"true"', True),
            ('""', False),
            ('false', False),
            ('true', True),
        ],
    )
    def test_the_text_grammar_and_the_boolean_grammar_agree(self, panels, stored, expected):
        assert panels['sent'][stored] is expected, (stored, panels['sent'])

    def test_a_cleared_box_is_not_a_request_to_tokenize(self, panels):
        """`''` means "never touched", and this switch has no default but off — the two
        spellings of off must not disagree, or the chart shows something the preview
        button did not ask for.
        """
        assert panels['sent']['""'] is False
        assert panels['sent']['"false"'] is False
