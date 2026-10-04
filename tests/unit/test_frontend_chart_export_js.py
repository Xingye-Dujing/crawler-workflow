"""Saving a drawn chart as a PNG — ``savePreviewImage`` / ``saveDashboardImage`` in workflow.js.

The studio could already put its picture on disk; the preview panel and the dashboard
cells could not, which meant the only way to get 图23 out of the app was to redraw it in
another tool. These cases run the two added paths against the REAL page markup (cut out of
``index.html``, so the button the page offers and the function the sandbox calls are the
shipped pair — AGENTS.md's rule that a wrapper installed in another file is not the
function your harness loads), and read the toast back from ``#toast`` where the product's
own ``showToast`` writes.

What is pinned, in order of the harm each avoids:

* the export is named after the chart on screen, and a second preview retargets it — an
  export called ``chart-preview`` cannot be matched back to 图23;
* ECharts is asked for a PNG at ``pixelRatio: 2`` on a white ground, because a transparent
  picture pasted into a document reads as a broken export;
* a Matplotlib preview already IS a data URL and is saved as it stands (no instance exists
  to ask);
* nothing drawn sends NO request and says the reason, so an idle button is not mistaken for
  a broken one;
* a server refusal is reported as a failure and returns no filename;
* rebuilding the board twice leaves exactly one live instance per cell, and saving then
  still delivers the current picture rather than a stale one.

Wording is compared against ``I18n.t(...)`` evaluated inside the same sandbox, never
against a pasted sentence.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
INDEX = REPO / 'backend' / 'static' / 'index.html'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_chart_export.mjs'


def _panel_markup() -> str:
    """The ``#chart-preview-panel`` element from index.html, braces balanced.

    Read from the page rather than copied here: the fixture's point is that the panel the
    product saves from is the panel the product ships.
    """
    src = INDEX.read_text(encoding='utf-8')
    start = src.index('<div id="chart-preview-panel">')
    opens, closes = re.compile(r'<div\b'), re.compile(r'</div>')
    pos, depth = start, 0
    while True:
        opened, closed = opens.search(src, pos), closes.search(src, pos)
        if opened and (not closed or opened.start() < closed.start()):
            depth += 1
            pos = opened.end()
        elif closed:
            depth -= 1
            pos = closed.end()
            if depth == 0:
                break
        else:
            break
    return src[start:pos]


@pytest.fixture(scope='module')
def saved(tmp_path_factory) -> dict:
    markup = tmp_path_factory.mktemp('markup') / 'panel.html'
    markup.write_text(_panel_markup(), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR), str(markup))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


class TestPreviewSave:
    def test_an_echarts_preview_is_saved_as_a_png_named_after_its_chart(self, saved):
        case = saved['preview_echarts']
        assert case['drawn'] == 1, 'the preview did not reach an instance, so this proves nothing'
        assert case['asked'] == 1
        assert case['url'] == '/api/studio/save-image'
        assert case['name'] == '图23 发酵期 每日热度与情感强度'
        assert case['image'] == 'data:image/png;base64,FROMINSTANCE'

    def test_the_picture_is_asked_at_double_size_on_a_white_ground(self, saved):
        spec = saved['preview_echarts']['spec']
        assert spec['type'] == 'png'
        assert spec['pixelRatio'] == 2, 'a 1x PNG is unreadable once it is in the paper'
        assert spec['backgroundColor'] == '#ffffff', 'a transparent chart disappears on white paper'

    def test_a_matplotlib_preview_saves_the_picture_the_server_already_sent(self, saved):
        case = saved['preview_matplotlib']
        assert case['drawn'] == 0, 'that engine has no instance, and the code must not need one'
        assert case['image'] == 'data:image/png;base64,MATPLOTLIBPICTURE'
        assert case['filename'] == 'tu23-a1b2c3.png'

    def test_a_second_preview_moves_the_name_with_it(self, saved):
        assert saved['preview_retargeted_name']['name'] == '图24 爆发期'

    def test_saving_nothing_drawn_asks_nothing_and_says_why(self, saved):
        case = saved['preview_nothing_drawn']
        assert case['asked'] == 0, 'a click with no chart must not produce a file'
        assert case['filename'] is None
        assert case['toast']['text'] == saved['catalog']['saveNothing']
        assert case['toast']['shown'] is True

    def test_a_refusal_is_reported_as_a_failure_not_as_a_filename(self, saved):
        case = saved['preview_server_refused']
        assert case['asked'] == 1
        assert case['filename'] is None
        assert case['toast']['text'].startswith(saved['catalog']['saveFailed'])
        assert 'image too large' in case['toast']['text'], 'the server reason reaches the user'


class TestDashboardSave:
    def test_an_echarts_cell_saves_its_own_picture_under_its_own_title(self, saved):
        case = saved['dashboard_echarts']
        assert case['instances'] == 1
        assert case['image'] == 'data:image/png;base64,FROMINSTANCE'
        assert case['name'] == '图15 主题流向'

    def test_a_matplotlib_cell_saves_the_image_the_cell_is_showing(self, saved):
        case = saved['dashboard_matplotlib']
        assert case['images'] == 1 and case['instances'] == 0
        assert case['image'] == 'data:image/png;base64,MATPLOTLIBPICTURE'

    def test_rebuilding_the_board_twice_keeps_one_live_cell_and_saves_that_one(self, saved):
        """A refresh replaces the grid; the bookkeeping must follow it, not accumulate.

        An instance left behind a discarded cell is resized on every window resize for the
        life of the page, and a stale data URL in ``_images`` would be exported as though it
        were the chart the board now shows.
        """
        case = saved['dashboard_after_rebuild']
        assert case['after_first_rebuild'] == 1
        assert case['after_second_rebuild'] == 1, 'the board leaked an instance per refresh'
        assert case['images'] == 0, 'this cell renders live, so no picture may be banked'
        assert case['asked'] == 1
        assert case['image'] == 'data:image/png;base64,FROMINSTANCE'


class TestPageMarkupAgreesWithTheCode:
    def test_the_preview_panel_offers_the_button_and_the_function_exists(self, saved):
        markup = saved['panel_markup']
        assert markup['save_button'] is True, 'index.html lost the 存为图片 button'
        assert 'chart.saveImage' in markup['keys']
        assert 'savePreviewImage()' in markup['onclicks']

    def test_the_labels_the_page_stamps_are_in_the_loaded_catalog(self, saved):
        """A data-i18n key the catalog does not hold renders as the key itself."""
        catalog = saved['catalog']
        assert catalog['saveNothing'].startswith('Nothing to save yet')
        assert '{path}' in catalog['saved'], 'the saved toast has to carry the file name'
