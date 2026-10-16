"""The 定时任务 dock: its own logic under node, and the wiring only the page can prove.

Two halves, and neither is visible to the other.

* ``harness_schedules.mjs`` drives the REAL ``schedules.js`` (with the real ``workflow.js`` and
  ``app.js``): the table is painted from ONE server payload, a status token becomes a catalogue word
  while an unknown token stays itself, the editor asks exactly what the server will be asked (a
  stored canvas that is no longer on the list shows AS ITSELF, a canvas that may not be scheduled
  carries the server's own reason), a save posts only the keys the chosen kind means, a refusal
  is quoted rather than paraphrased, and a 立即执行 that really started takes the live console up
  while a queued fire leaves it alone.
* The static half is what a page boot needs, and every missing piece there is silent: a dock with no
  resize handle cannot be grown, a panel absent from ``DOCKED_PANELS`` stacks on top of the console,
  a dock that app.js does not wire has a handle that does nothing, and a panel left out of the
  language fan-out keeps the old language after a switch. The panel is checked to be in the dock
  matrix (``harness_panels.mjs``) as well — a new dock belongs in that list.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
STATIC_DIR = REPO / 'backend' / 'static'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_schedules.mjs'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]


@pytest.fixture(scope='module')
def results():
    proc = run_node(
        str(HARNESS),
        str(JS_DIR / 'workflow.js'),
        str(JS_DIR / 'app.js'),
        str(JS_DIR / 'schedules.js'),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ─── The panel, driven ───


class TestTheTable:
    def test_it_is_painted_from_the_payload_verbatim(self, results):
        """Every word a task carries is the server's — a task is not re-described in the browser."""
        painted = results['painted']
        assert '每天早八' in painted
        assert '红果短剧' in painted
        assert results['header'] == ['任务', '画布', '时间', '下次运行', '最近一次', '']
        # The trigger sentence, the moment in the TASK's zone, its last outcome and its note.
        assert '每天 08:00' in painted
        assert '2026-10-16 08:00 (Asia/Shanghai)' in painted
        assert '被拒绝' in painted and '2026-10-15 08:00 (Asia/Shanghai)' in painted
        assert '画布需要模型' in painted
        assert '错过 2 次' in painted
        assert results['rows'] == 2, 'one header row and one task'

    def test_the_operator_line_says_which_box_and_what_it_calls_now(self, results):
        assert results['statusLine'] == (
            '服务器时间 2026-10-15 20:00 · 服务器时区 中国标准时间 UTC+08:00 · 调度线程正在运行'
        )

    def test_a_row_carries_the_five_things_a_user_can_do(self, results):
        assert results['rowButtons'] == ['停用', '立即执行', '编辑', '日志', '删除']

    def test_a_token_becomes_a_word_and_an_unknown_token_stays_itself(self, results):
        words = results['words']
        assert '已启动' in words, 'the started token was not worded'
        assert 'weird' in words, 'an unknown status was dressed up as a known one instead of shown'

    def test_no_task_yet_is_an_empty_state_next_to_the_clock(self, results):
        empty = results['empty']
        assert empty['rows'] == 0
        assert '还没有定时任务' in empty['html']
        assert '调度线程正在运行' in empty['html'], 'the clock line vanished with the table'

    def test_a_server_that_refuses_is_quoted_not_paraphrased(self, results):
        """A refused READ carries no payload at all (the server answers 200 with one; this is an
        unreachable box or an error page), so only the reason can be shown — never an empty table,
        which would say the user has no schedules."""
        refused = results['refused']
        assert '时间格式无法识别：25:00' in refused
        assert '还没有定时任务' not in refused, 'a failed read was shown as "no tasks"'

    def test_a_refused_write_still_repaints_from_the_payload_that_came_with_it(self, results):
        refused = results['refusedPost']
        assert refused['posts'] == [{'url': '/api/schedules/toggle', 'body': {'id': 'kept', 'enabled': False}}]
        assert refused['toasts'] == ['需要模型，不能定时'], 'the refusal was not shown as the server worded it'
        assert '留下的任务' in refused['html'], 'the table kept a task the server had just refused'
        # A write refusal DOES carry the payload, so the clock line comes from it too — here the
        # server said the thread is down, and the panel marks it rather than repeating the old word.
        assert '调度线程没有运行' in refused['html']
        assert 'sched-status-off' in refused['html']

    def test_a_hostile_id_cannot_break_out_of_its_attribute(self, results):
        """Task names and ids are user data; the row buttons go through ``attrJsArg`` for this."""
        hostile = results['hostile']
        assert hostile['breaksOut'] is False, 'a quote in a task id closed the onclick attribute'
        assert "onmouseover=\\'" in hostile['raw'], 'the escaping that makes the above true is gone'
        assert hostile['buttons'] == 5, 'the markup fell apart into a different number of buttons'
        assert hostile['wired'] == 4, 'four buttons call schedulesManager; the fifth opens the run log'
        assert 'runLogViewer.open(' in hostile['raw']


class TestTheEditor:
    def test_it_asks_one_dialog_for_everything(self, results):
        editor = results['editor']
        assert editor['fields'] == [
            {'id': 'sched-name', 'value': '每天早八', 'type': 'text'},
            {'id': 'sched-canvas', 'value': '已经改名的画布', 'type': 'select'},
            {'id': 'sched-kind', 'value': 'daily', 'type': 'select'},
            {'id': 'sched-at', 'value': '08:00', 'type': 'text'},
            {'id': 'sched-weekday', 'value': '1', 'type': 'select'},
            {'id': 'sched-interval', 'value': '30', 'type': 'number'},
            {'id': 'sched-cron', 'value': '', 'type': 'text'},
            {'id': 'sched-zone', 'value': 'Asia/Shanghai', 'type': 'text'},
            {'id': 'sched-lang', 'value': 'zh', 'type': 'select'},
        ]
        assert editor['kindOptions'] == ['daily', 'weekly', 'interval', 'cron']
        assert editor['weekdayOptions'] == ['1', '2', '3', '4', '5', '6', '7']
        assert editor['toggles'] == [{'id': 'sched-enabled', 'label': '启用', 'checked': True}]
        assert editor['buttons'] == [
            {'label': '取消', 'value': None, 'collect': False, 'primary': False},
            {'label': '保存', 'value': 'save', 'collect': True, 'primary': True},
        ]
        assert editor['message'], 'the dialog explains what a scheduled run may not do'

    def test_a_stored_canvas_that_is_no_longer_on_the_list_shows_as_itself(self, results):
        """A ``<select>`` whose value is off its own list answers ``''`` — and then the save would
        refuse a task the user never touched."""
        options = results['editor']['canvasOptions']
        assert options[0] == ['已经改名的画布', '已经改名的画布']
        assert ['红果短剧', '红果短剧'] in options

    def test_a_canvas_that_may_not_be_scheduled_carries_the_server_reason(self, results):
        options = dict(results['editor']['canvasOptions'])
        assert options['要模型'] == '要模型 — 需要模型，不能定时'
        assert options['要模型'].split(' — ')[0] == '要模型', 'the value must stay the bare canvas name'

    def test_a_save_posts_only_the_keys_the_chosen_kind_means(self, results):
        posts = results['saved']['posts']
        assert len(posts) == 1
        assert posts[0]['url'] == '/api/schedules/save'
        assert posts[0]['body'] == {
            'name': '周三九点半',
            'workflow': '红果短剧',
            'timezone': 'Asia/Shanghai',
            'lang': 'zh',
            'enabled': False,
            'trigger': {'kind': 'weekly', 'at': '09:30', 'weekday': 3},
            'id': 'gone-id',
        }, 'a weekly rule carried the interval/cron boxes along, so its sentence could drift'
        assert results['saved']['toasts'] == ['已保存']

    def test_cancelling_writes_nothing(self, results):
        assert results['editor']['posted'] == 0


class TestTheButtons:
    def test_immediate_execution_says_which_of_the_two_things_happened(self, results):
        assert results['runToasts'] == ['已开始运行：每天早八', '服务器正忙，已排队运行：每天早八']

    def test_a_started_fire_attaches_the_console_but_a_queued_one_does_not(self, results):
        """The fire that really started owns a live console; the panel must take the stream up now
        (same attach the Run button and boot reconnect take), not make the user refresh. A queued
        fire has no console of its own yet, so it must leave the running one attached — one attach
        per fire, in the order 立即执行 was driven (started, then queued)."""
        assert results['runReconnect'] == [1, 0]

    def test_removing_asks_first_and_the_answer_decides(self, results):
        assert results['removeCancelled'] == 0, 'a cancelled delete still posted'
        assert results['removePosts'] == [{'url': '/api/schedules/delete', 'body': {'id': 'abc123'}}]


class TestTheDock:
    def test_opening_it_takes_the_slot_and_clears_a_stale_height(self, results):
        assert results['dock']['open'] == ['schedules-panel']
        assert results['dock']['staleHeights'] == []

    def test_closing_it_leaves_no_inline_height_behind(self, results):
        after = results['dock']['afterSecondToggle']
        assert after['open'] == []
        assert after['height'] == ''


# ─── The wiring only the page can prove ───


def _html():
    return (STATIC_DIR / 'index.html').read_text(encoding='utf-8')


def _js(name):
    return (JS_DIR / name).read_text(encoding='utf-8')


def _css():
    return (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')


def test_the_page_carries_the_panel_its_body_and_its_handle():
    html = _html()
    assert 'id="schedules-panel"' in html
    assert 'id="schedules-resize-handle"' in html
    assert 'id="schedules-mgr-body"' in html


def test_three_places_open_the_panel_and_each_one_is_an_opening():
    """The flat bar's Run group, the status bar's dock row, and the panel's own Close button."""
    assert _html().count('onclick="toggleSchedulesPanel()"') == 3


def test_the_panel_script_loads_after_the_two_files_it_borrows_from():
    """``schedules.js`` calls ``fetchJSON``/``showDialog``/``closeDockedPanels``/``attrJsArg`` and
    reads ``I18n`` — all declared by the files before it, so the order is the contract."""
    html = _html()
    after = html.index('/js/schedules.js')
    assert html.index('/js/workflow.js') < after
    assert html.index('/js/app.js') < after


def test_the_dock_list_holds_it_and_the_stylesheet_sizes_it():
    docked = re.search(r'var DOCKED_PANELS = \[([^\]]*)\]', _js('workflow.js'))
    assert docked is not None
    assert "'schedules-panel'" in docked.group(1), 'opening the panel would stack it on the console'
    css = _css()
    for selector in (
        '#schedules-panel {',
        '#schedules-panel.open {',
        '#schedules-resize-handle {',
        '#schedules-mgr-body',
    ):
        assert selector in css, selector


def test_the_handle_was_wired_to_the_dock_resizer():
    assert "initDockResize('schedules-resize-handle', 'schedules-panel')" in _js('app.js')


def test_a_language_switch_reaches_the_panel():
    """``I18n.apply()`` only re-stamps ``data-i18n`` nodes; every word in this table is built here,
    so the switch has to call the panel or the table keeps the old language."""
    assert "if (typeof schedulesManager !== 'undefined') schedulesManager.onLanguageChange();" in _js('workflow.js')


def test_the_dock_matrix_in_the_shared_harness_still_covers_every_panel():
    """``harness_panels.mjs`` is the one place that proves "opening a dock closes the others", so a
    panel added to ``DOCKED_PANELS`` without being added there is a panel nobody checks."""
    docked = re.search(r'var DOCKED_PANELS = \[([^\]]*)\]', _js('workflow.js'))
    ids = re.findall(r"'([\w-]+)'", docked.group(1))
    harness = (Path(__file__).resolve().parents[1] / 'frontend' / 'harness_panels.mjs').read_text(encoding='utf-8')
    listed = re.search(r'const ids = \[([^\]]*)\]', harness)
    assert listed is not None
    for panel_id in ids:
        assert f"'{panel_id}'" in listed.group(1), f'{panel_id} is docked but not in the dock matrix'
