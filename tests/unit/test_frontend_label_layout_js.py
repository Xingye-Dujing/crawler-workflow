"""The graph label solver's reserved band, run against the REAL ``workflow.js``.

``harness_label_layout.mjs`` loads the shipped file into a node ``vm`` and calls the solver the
page installs. What is asserted here is the part no Python test can reach: a label that touches
no other label may still be pushed into the chart title or the cluster legend column, and the
series' own ``left``/``top``/``right``/``bottom`` is the only thing that says where those are.

Nothing is asserted about a specific pixel: each case hands the solver a box, reads the box back,
and checks it against the band that case declared. A solver that hid every label would pass the
``inside`` flags alone, so each case also reports whether the label survived at all.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_label_layout.mjs'


@pytest.fixture(scope='module')
def placed() -> dict:
    proc = run_node(str(HARNESS), str(JS_DIR / 'workflow.js'))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


class TestSolverKeepsItsBand:
    def test_a_label_inside_the_band_is_left_where_it_was(self, placed):
        case = placed['left_alone']
        assert case['inside'] is True
        # Only the node bubble may move it, never the canvas edge.
        assert abs(case['got']['x'] - case['asked']['x']) <= 6

    def test_a_label_dropped_in_the_legend_column_is_pulled_back(self, placed):
        case = placed['legend_column']
        assert case['hidden'] is False, 'the solver hid a label that had room to move'
        assert case['inside'] is True

    def test_a_label_above_the_title_band_is_pulled_down(self, placed):
        case = placed['title_band']
        assert case['hidden'] is False
        assert case['inside'] is True

    def test_a_percentage_inset_is_a_length_not_a_zero(self, placed):
        """``'10%'`` read as a number is NaN→0, the clamp quietly disappears, and the only
        symptom is a term printed over the legend on a wide screen."""
        case = placed['percent_insets']
        assert case['hidden'] is False
        assert case['inside'] is True

    def test_two_labels_on_one_spot_do_not_print_on_each_other(self, placed):
        case = placed['siblings']
        assert case['apart'] is True or case['hidden'] is True

    def test_a_series_that_declares_no_band_is_clamped_to_the_canvas_only(self, placed):
        """Inventing a reserve here would move labels a plain chart never needed to move —
        the series says where its own drawing box is, and nothing else decides."""
        case = placed['no_bands']
        assert case['hidden'] is False
        assert case['inCanvas'] is True

    def test_apply_echarts_option_hands_the_solver_the_instance_it_measures(self, placed):
        case = placed['wired_to_instance']
        assert case['installed'] is True, 'applyEchartsOption no longer installs the resolver'
        assert case['hidden'] is False
        assert case['inside'] is True, 'the solver measured a different canvas than the instance it drew on'
