"""A missing front-end bundle has to be visible on screen, not merely absent.

Runs the real ``workflow.js`` in node twice — once with an ECharts stub and once with no ECharts at
all, which is what a missing ``<script>`` leaves behind — and drives the four surfaces that draw a
figure (preview panel, full-screen window, dashboard cell, history panel) plus the vector export and
the two basemap paths.

What is pinned, and why each matters:
* every surface names the file that is missing, and none of them throws: a blank panel reads as
  "this node produced no chart", which is a different fact;
* the vector export sends NO request — an empty ``.svg`` on disk is a file that claims to be a
  figure, and the user pastes it into a paper;
* a preview without the painter still offers its LaTeX: the server-side source is real;
* a basemap that will not register is refused ON THE FIGURE (the drawn option is the sentence), so
  the exported PNG carries the reason instead of an empty frame;
* the refusal names the file and the HTTP status, and the failure is retried instead of cached.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

REPO = Path(__file__).resolve().parents[3]
JS_DIR = REPO / 'backend' / 'static' / 'js'
INDEX = REPO / 'backend' / 'static' / 'index.html'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_missing_assets.mjs'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]


def _extract_div(src: str, marker: str) -> str:
    start = src.index(marker)
    opens, closes = re.compile(r'<div\b'), re.compile(r'</div>')
    pos, depth = start, 0
    while True:
        next_open = opens.search(src, pos + 1)
        next_close = closes.search(src, pos + 1)
        if next_close is None:
            raise AssertionError('unbalanced markup fixture')
        if next_open and next_open.start() < next_close.start():
            depth += 1
            pos = next_open.start()
            continue
        depth -= 1
        pos = next_close.start()
        if depth == 0:
            return src[start : pos + len('</div>')]


@pytest.fixture(scope='module')
def results(tmp_path_factory):
    src = INDEX.read_text(encoding='utf-8')
    markup = tmp_path_factory.mktemp('markup') / 'panels.html'
    markup.write_text(
        _extract_div(src, '<div id="chart-preview-panel">')
        + '\n'
        + _extract_div(src, '<div id="chart-fullscreen-panel">'),
        encoding='utf-8',
    )
    proc = run_node(str(HARNESS), str(JS_DIR), str(markup))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


class TestAnAbsentChartLibrary:
    def test_the_preview_names_the_file_instead_of_showing_a_box(self, results):
        case = results['preview_without_library']
        assert case['hasLibrary'] is False
        assert case['note'] == case['expected']
        assert '/vendor/echarts.min.js' in case['note']
        assert case['instances'] == 0, 'no instance was created, so nothing is resized or leaked'

    def test_the_preview_still_offers_its_latex_source(self, results):
        case = results['preview_without_library']
        # The option and the LaTeX came back from the server; only the browser-side painter is gone.
        assert case['optionKept'] is True
        assert case['latexBarOffered'] is True

    def test_a_preview_with_the_library_draws_and_prints_no_note(self, results):
        case = results['preview_with_library']
        assert case['note'] == ''
        assert case['instances'] == 1
        assert case['drawn'] == 1

    def test_the_fullscreen_window_says_the_same_thing_and_keeps_its_option(self, results):
        case = results['fullscreen_without_library']
        assert 'echarts.min.js' in case['note']
        assert case['optionKept'] is True
        assert case['instances'] == 0

    def test_a_dashboard_cell_that_cannot_paint_says_why(self, results):
        case = results['dashboard_without_library']
        assert case['names_library'] is True, case['text']
        assert case['instances'] == 0

    def test_the_vector_export_refuses_by_name_and_asks_the_server_for_nothing(self, results):
        case = results['vector_without_library']
        assert case['filename'] is None
        assert case['toast'] == case['expected']
        assert case['export_requests'] == 0, 'a saved .svg with no figure in it would be a file that lies'


class TestABasemapThatWillNotLoad:
    def test_the_refusal_names_the_file_and_the_status(self, results):
        case = results['map_refusal_names_the_file']
        assert case['has_file'] is True
        assert case['has_status'] is True
        assert case['refusal'], 'the loader answers with the sentence the figure draws'

    def test_a_failed_read_is_retried_on_the_next_figure(self, results):
        case = results['map_refusal_names_the_file']
        assert case['retried'] is True, 'a broken file that fixes itself should not need a page reload'
        assert case['redrawn'] is True

    def test_the_map_is_refused_on_the_figure_rather_than_drawn_empty(self, results):
        case = results['map_refusal_names_the_file']
        assert case['drawn_is_refusal'] is True, 'the exported PNG must carry the reason, not a blank frame'

    def test_a_readable_basemap_registers_and_the_real_option_is_drawn(self, results):
        case = results['map_registers_and_draws']
        assert case['refusal'] == ''
        assert case['registered'] == ['china']
        assert case['drawn_has_series'] is True

    def test_a_basemap_this_build_does_not_ship_is_named(self, results):
        case = results['unknown_basemap_is_refused']
        assert 'mars' in case['refusal']
        assert case['asked'] == 0, 'an unknown name must not fetch a path nobody declared'
