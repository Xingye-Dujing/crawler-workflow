"""Behaviour tests for the canvas-history tab and the Style-menu layout strategy.

The panel executes real workflow.js under node; the page/CSS wiring is checked
statically because the harness has no index.html. The decisions under test are the
ones a screenshot cannot show: what body a snapshot stores, whether restoring is one
undo step, whether a deleted snapshot clears the baseline it backed, and whether the
Layout button obeys the chosen strategy instead of always running the algorithm.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_wf_history.mjs'
STATIC = REPO / 'backend' / 'static'
WORKFLOW_JS = STATIC / 'js' / 'workflow.js'
CANVAS_JS = STATIC / 'js' / 'canvas.js'
MENU_JS = STATIC / 'js' / 'menu.js'
INDEX_HTML = STATIC / 'index.html'
STYLE_CSS = STATIC / 'css' / 'style.css'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]


@pytest.fixture(scope='module')
def wfh() -> dict:
    proc = run_node(str(HARNESS), str(WORKFLOW_JS), tz='Asia/Shanghai')
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


class TestTabs:
    def test_the_panel_opens_on_files_and_counts_saved_states(self, wfh):
        assert 'runs-tab active' in wfh['tabs']['html']
        assert 'Workflows' in wfh['tabs']['html']
        assert 'Canvas history (2)' in wfh['tabs']['html']
        assert wfh['tabs_history']['html'].count('active') == 1
        assert 'Canvas history (2)' in wfh['tabs_history']['html']

    def test_an_empty_history_says_so_instead_of_drawing_an_empty_table(self, wfh):
        assert 'EMPTY' in wfh['history_empty']['html']
        assert '<table' not in wfh['history_empty']['html']


class TestHistoryTable:
    def test_a_snapshot_row_names_the_state_and_its_source_workflow(self, wfh):
        html = wfh['history_render']['html']
        assert '手动存档' in html
        assert '日报' in html
        assert '>3 / 2<' in html
        assert 'Untitled snapshot' not in html

    def test_a_name_is_text_not_markup_and_keeps_its_action_callable(self, wfh):
        html = wfh['history_render']['html']
        assert '&lt;img' in html
        assert wfh['history_render']['img_elements'] == 0
        # The quote in the workflow name must not close the onclick attribute; ids,
        # not names, are what the action receives.
        assert re.search(r'onclick="wfFiles\.restoreSnapshot\(\'s1\'\)"', html)
        assert re.search(r'onclick="wfFiles\.deleteSnapshot\(\'s1\'\)"', html)
        assert re.search(r'onclick="wfFiles\.setBaseline\(\'s1\'\)"', html)
        assert 'q&quot;uote' in html

    def test_the_baseline_snapshot_is_the_only_one_tagged(self, wfh):
        html = wfh['history_render']['html']
        assert html.count('wf-snap-baseline') == 1
        assert html.count('baseline</span>') == 1


class TestSaving:
    def test_saving_posts_the_canvas_and_the_workflow_it_came_from(self, wfh):
        body = wfh['save']['body']
        assert body['label'] == '手动存档'
        assert body['workflow_name'] == '日报'
        assert body['workflow']['nodes'][0]['id'] == 'node-0'
        assert wfh['save']['tab'] == 'history'
        assert wfh['save']['toasts'] == ['SAVED']

    def test_a_cancelled_dialog_sends_nothing(self, wfh):
        assert wfh['save_cancelled'] == {'requests': 0, 'toasts': []}


class TestRestoring:
    def test_restore_reads_the_named_snapshot_and_rebuilds_it_as_one_step(self, wfh):
        assert wfh['restore']['gets'] == ['/api/workflow/history/get?id=s1']
        assert wfh['restore']['loaded_is_snapshot'] is True
        assert wfh['restore']['batch_calls'] == 1, 'a restore must be one undo step, not one per node'
        assert wfh['restore']['toasts'] == ['RESTORED']

    def test_declining_the_confirmation_reads_nothing(self, wfh):
        assert wfh['restore_cancelled'] == {'requests': 0, 'loaded': None, 'toasts': []}

    def test_a_live_run_refuses_before_the_dialog(self, wfh):
        assert wfh['restore_busy'] == {'requests': 0, 'loaded': None, 'toasts': ['BUSY']}


class TestDeleting:
    def test_delete_names_the_snapshot_and_reports_a_cleared_baseline(self, wfh):
        assert wfh['delete']['body'] == {'id': 's1'}
        assert wfh['delete']['toasts'] == ['DELETED (1 cleared)']
        assert wfh['delete']['history_reads'] == 1, 'the table must re-read after a delete'


class TestLayoutStrategy:
    def test_the_menu_reads_the_per_workflow_layout_and_paints_it(self, wfh):
        painted = wfh['layout_paint']
        assert painted['select'] == 'baseline'
        assert '排布基准' in painted['hint']
        assert painted['hint_missing'] is False
        assert painted['requests'] == ['/api/workflow/history/layout?workflow=%E6%97%A5%E6%8A%A5']

    def test_choosing_baseline_without_one_refuses_and_snaps_back(self, wfh):
        assert wfh['layout_no_baseline']['requests'] == 0
        assert wfh['layout_no_baseline']['toasts'] == ['NO-BASELINE']
        assert wfh['layout_no_baseline']['select'] == 'algorithm'

    def test_setting_the_strategy_sends_the_baseline_it_was_shown(self, wfh):
        assert wfh['layout_set_baseline_strategy']['body'] == {
            'workflow_name': '日报',
            'strategy': 'baseline',
            'snapshot_id': 's1',
        }
        assert wfh['layout_set_baseline_strategy']['toasts'] == ['BASELINE-SET']
        assert wfh['layout_set_baseline_strategy']['select'] == 'baseline'

    def test_an_unsaved_canvas_has_no_workflow_to_store_a_baseline_under(self, wfh):
        assert wfh['layout_no_file'] == {'requests': 0, 'toasts': ['SAVE-FIRST']}

    def test_baseline_layout_applies_saved_positions_and_leaves_unknown_nodes_alone(self, wfh):
        laid = wfh['baseline_layout']
        assert laid['handled'] is True
        assert [laid['left0'], laid['top0']] == ['10px', '20px']
        assert [laid['left1'], laid['top1']] == ['300px', '41px']
        assert laid['untouched'] == ''
        assert laid['batch_calls'] == 1
        assert laid['auto_options'] == {'silent': True}
        assert laid['reset_count'] == 1
        assert laid['toasts'] == ['LAYOUT-APPLIED']

    def test_algorithm_is_still_the_algorithm(self, wfh):
        assert wfh['algorithm_layout'] == {'handled': False, 'batch_calls': 0}

    def test_a_missing_baseline_refuses_by_name_instead_of_running_the_algorithm(self, wfh):
        assert wfh['missing_layout']['handled'] is True
        assert wfh['missing_layout']['batch_calls'] == 0
        assert wfh['missing_layout']['toasts'] == ['BASELINE-GONE']

    def test_the_layout_button_routes_through_the_strategy(self):
        canvas = CANVAS_JS.read_text(encoding='utf-8')
        assert re.search(r'async runAutoLayout\(\)', canvas)
        assert 'LayoutStrategy.layout()' in canvas
        assert "case 'autoLayout':\n                    this.runAutoLayout();" in canvas
        page = INDEX_HTML.read_text(encoding='utf-8')
        assert 'onclick="canvas.runAutoLayout()"' in page
        assert 'id="layout-strategy"' in page
        assert 'id="layout-baseline-hint"' in page
        menu = MENU_JS.read_text(encoding='utf-8')
        assert 'LayoutStrategy.refresh()' in menu

    def test_a_load_with_history_single_goes_through_the_batch(self, wfh):
        assert wfh['load_wrapper'] == {'batch_calls': 1, 'direct_calls': 2}
        source = WORKFLOW_JS.read_text(encoding='utf-8')
        assert "options.history === 'single'" in source
        assert 'canvas.batchHistory' in source

    def test_the_history_table_repaints_in_chinese_without_a_request(self, wfh):
        html = wfh['language']['html']
        assert '工作流文件' in wfh['language']['tabs']
        assert '画布历史' in wfh['language']['tabs']
        assert '手动存档' in html
        assert '恢复' in html and '删除' in html


class TestPageWiring:
    def test_the_history_containers_and_save_bar_exist(self):
        page = INDEX_HTML.read_text(encoding='utf-8')
        for element_id in ('workflows-tabs', 'workflows-history-bar'):
            assert f'id="{element_id}"' in page
        assert 'onclick="wfFiles.saveSnapshot()"' in page
        assert 'wfFiles.openHistory()' in page

    def test_the_tabs_share_the_run_panel_styles_and_the_bar_has_its_own(self):
        css = STYLE_CSS.read_text(encoding='utf-8')
        assert '#workflows-tabs' in css
        assert '.wf-history-bar' in css
        assert '.wf-snap-baseline' in css
        assert '.layout-baseline-hint' in css

    def test_every_new_word_exists_in_the_server_and_browser_catalogues(self):
        # The JS panel resolves through app.js; the refusals and labels around it also
        # exist server-side for the API's error bodies. A missing key would print the
        # key itself, which is how a computed-key audit found the last two.
        from i18n import _EN, _ZH

        keys = [
            'wfHistory.invalid',
            'wfHistory.labelTooLong',
            'wfHistory.workflowNameTooLong',
            'wfHistory.unserializable',
            'wfHistory.full',
            'wfHistory.missing',
            'wfHistory.corrupt',
            'wfHistory.workflowRequired',
            'wfHistory.badStrategy',
            'wfHistory.baselineRequired',
        ]
        for key in keys:
            assert key in _ZH, key
            assert key in _EN, key
        app = (STATIC / 'js' / 'app.js').read_text(encoding='utf-8')
        for key in (
            'wfHistory.tabHistory',
            'wfHistory.save',
            'wfHistory.restore',
            'wfHistory.baseline',
            'wfHistory.needSaved',
            'wfHistory.noBaseline',
            'wfHistory.openHistory',
            'style.layout',
            'style.layoutBaselineLabel',
            'style.layoutBaselineMissing',
        ):
            assert f"'{key}'" in app, key
