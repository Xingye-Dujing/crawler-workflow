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


class TestNodeModelBox:
    """The per-node Ollama model picker on an LLM process node."""

    def test_the_box_offers_the_daemon_tags_when_the_panel_is_left_alone(self, panels):
        calm = panels['model']['ollamaCalm']
        assert calm['hasSelect'] is True, 'a provider=ollama LLM node drew no model box'
        assert calm['asked'] == 1, calm
        assert calm['follow'] is True, 'the box lost its 跟随全局 default option'
        assert calm['filled'] is True, 'the daemon tags never reached the select'

    def test_the_tags_still_land_when_a_redraw_lands_mid_flight(self, panels):
        """Editing a field rewrites the form while the tag list is in flight; the
        loader re-looks the select up after the await, so it fills the box the user
        sees instead of the orphan it started with.
        """
        raced = panels['model']['ollamaRaced']
        assert raced['asked'] == 2, f'the scenario did not redraw mid-flight: {raced}'
        assert raced['filled'] is True, 'the tags were written into an off-page select'

    def test_a_stored_model_the_daemon_dropped_shows_as_itself(self, panels):
        """Never collapse an off-list value to option #0 (the AGENTS.md select rule):
        a tag the node was built with but the daemon no longer lists must survive.
        """
        off = panels['model']['ollamaOffList']
        assert off['kept'] is True, off
        assert off['follow'] is True, off

    def test_an_openrouter_run_gets_no_model_box(self, panels):
        """The override is Ollama-only; an OpenRouter run must not be offered a box
        whose value it would refuse at the daemon that has no such tag.
        """
        cloud = panels['model']['openrouter']
        assert cloud['hasSelect'] is False, 'an openrouter node offered an Ollama model box'
        assert cloud['asked'] == 0, 'the tag list was fetched for a run that cannot use it'


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


class TestStackPctPanel:
    """The 占比堆叠图 is generated like any other type — the board must offer it, draw its
    one extra box (the stacked column list), and forward that list, or the cell asks the
    service for a stacked field it never sent and the figure is an opaque refusal."""

    def test_the_panel_offers_the_share_chart_and_its_field_box(self, panels):
        assert panels['stack']['offersType'] is True, 'the type select never gained 占比堆叠图'
        assert panels['stack']['hasStackInput'] is True, 'selecting it drew no stack_fields input'

    def test_the_board_forwards_the_stacked_columns(self, panels):
        sent = panels['stack']
        assert sent['bodyChartType'] == 'stack_pct', sent
        assert sent['bodyStackFields'] == '积极占比, 中性占比, 消极占比', sent


class TestEmitLatexPanel:
    """The LaTeX export is two checkboxes on every visualize node — figure on by default,
    booktabs table off — and BOTH must ride out to the render request, or the board draws a
    chart but silently never files the .txt the user's paper needs."""

    def test_the_panel_offers_both_export_checkboxes(self, panels):
        got = panels['latex']
        assert got['panelHasEmitCheckbox'] is True, 'no emit_latex checkbox drawn'
        assert got['panelHasTableCheckbox'] is True, 'no emit_latex_table checkbox drawn'

    def test_the_defaults_reach_the_request(self, panels):
        got = panels['latex']
        assert got['bodyEmitLatex'] is True, f'figure should default on, saw {got["bodyEmitLatex"]!r}'
        assert got['bodyEmitTable'] is False, f'table should default off, saw {got["bodyEmitTable"]!r}'


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
