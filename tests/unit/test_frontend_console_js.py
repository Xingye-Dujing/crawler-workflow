"""Behaviour tests for the real run-console poller (workflow.js `pollStatus`).

The console is the only place a running job is visible, and every rule in it has
already broken once — see tests/frontend/harness_console.mjs for the list. This
module drives those rules: which lines land in the DOM after each poll answer, and
what the user is told when the run ends unfinished.

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
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_console.mjs'


@pytest.fixture(scope='module')
def console():
    proc = run_node(str(HARNESS), str(JS_DIR / 'workflow.js'), str(JS_DIR / 'stats.js'))
    assert proc.returncode == 0, f'console harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestConsoleCursor:
    def test_the_first_answer_renders_every_line_offered(self, console):
        assert console['firstBatch'] == ['a1', 'a2', 'a3']

    def test_a_second_answer_appends_only_what_has_not_been_seen(self, console):
        assert console['secondBatch'] == ['a4', 'a5'], 'the console must not replay the first three lines'

    def test_a_second_run_is_rendered_instead_of_silently_ignored(self, console):
        """The freeze. The server clears its buffer when a new run starts, so the
        total drops BELOW the index already consumed; slicing from that index used
        to answer 'nothing new' for the rest of the run."""
        assert console['afterRestart'] == ['b1', 'b2'], 'a restarted buffer must be read from the start'

    def test_past_the_truncation_cap_the_delta_comes_from_the_total(self, console):
        """The endpoint ships the last 200 lines and the true total (250 here);
        the first poll must show the held tail, the next only the line that is
        new — the bug this replaced believed a truncated array was the whole log."""
        assert console['cappedFirst'] == 200
        assert console['cappedDelta'] == ['line-251']

    def test_clearing_shows_the_next_line_and_does_not_replay_the_buffer(self, console):
        # After a clear the user wants what comes next, not the held 200 again.
        assert console['afterClear'] == ['line-252']

    def test_switching_away_and_back_keeps_what_the_view_had_shown(self, console):
        """The user's complaint, stated as a rule: 切换工作流标签页 must not read as
        "the console was cleared".

        The server only ever ships the tail of the whole run, so a view cannot be
        rebuilt from a later answer — the browser has to remember what it showed.
        And the cursor must stay where it was: a switch that also reset it would
        replay the entire held tail on the next poll.
        """
        switched = console['afterTabSwitch']
        assert switched['kept'] == 1, switched
        assert switched['same'] is True, 'the lines returned by the switch are not the ones that went in'
        assert switched['next'] == ['only-one'], f'the next poll must append only the new line: {switched["next"]}'

    def test_a_view_that_never_ran_opens_empty_rather_than_borrowing_another(self, console):
        assert console['blankOnUnknownTab'] == 0, 'an unknown tab has no history to paint'


class TestRunEndReporting:
    def test_the_cookie_expiry_toast_shouts_once_per_run(self, console):
        """Polling is once a second: the same sentence every second would bury the
        console it is supposed to draw attention to."""
        assert console['expiryToasts'] == ['COOKIE-EXPIRED']

    def test_a_run_that_left_nodes_broken_says_so_and_offers_the_continue(self, console):
        assert console['endedFailed']['toasts'] == ['WORKFLOW-ENDED 2/3']
        assert console['endedFailed']['resumeRefreshed'] is True

    def test_a_clean_completion_claims_itself_and_promises_nothing_more(self, console):
        assert console['endedCompleted']['toasts'] == ['WORKFLOW-COMPLETED']
        assert console['endedCompleted']['resumeRefreshed'] is False, 'there is nothing to continue'

    def test_a_refused_definition_is_not_reported_as_a_finished_run(self, console):
        assert console['endedRejected']['toasts'] == ['WORKFLOW-REJECTED']
        assert console['endedRejected']['statusNodes'] == 'progress 0/0'
        assert console['endedRejected']['resumeRefreshed'] is False

    def test_a_stopped_run_says_stopped(self, console):
        assert console['endedInterrupted']['toasts'] == ['WORKFLOW-STOPPED']
        assert console['endedInterrupted']['resumeRefreshed'] is True, 'a stopped run is exactly what to continue'

    def test_the_status_bar_keeps_the_progress_ratio_and_drops_the_clock(self, console):
        """The bar used to show the canvas node count at the exact moment the
        reader wanted the finished/planned ratio, and copied the last console line
        including its [HH:MM:SS] prefix — the same sentence twice on one screen."""
        bar = console['statusBarDuringRun']
        assert bar['nodes'] == 'progress 1/3'
        assert bar['text'] == 'Executing node: 抓取 #node-1'

    def test_the_parallel_view_offers_one_tab_per_workflow(self, console):
        assert console['tabCount'] == 3, 'all + the two workflows'

    def test_a_workflow_tab_shows_only_its_own_lines(self, console):
        """Each tab keeps its own history, and no line is shown twice.

        ``tabBOnOpen`` is the part a per-tab cursor alone cannot give: workflow 乙's
        tab had never been visible when its lines arrived, and opening it must show
        them rather than wait for the next line — which for a finished run is never.
        """
        assert console['parallelFirst'] == ['shared'], 'the 全部 tab shows the run as one stream'
        assert console['tabBOnOpen'] == ['b-only'], 'a tab must not open blank on lines it already received'
        assert console['tabB'] == ['b-two'], 'only the line new to that tab may be appended'
        assert console['allAfterB'] == ['shared'], "乙's lines must not have leaked into 全部"

    def test_a_stop_that_has_not_landed_prints_no_verdict(self, console):
        """The gap between the Stop request and the worker's verdict is the whole
        reason the record used to look frozen: the poller must keep reading and
        keep its mouth shut until the run has actually spoken."""
        case = console['settlingThenSettled']
        assert case['toasts'] == ['WORKFLOW-STOPPED'], 'the settling tick announced an outcome it did not have'
        assert case['stillPolling'] == [True, False], 'the poller gave up before the settle, or never stopped'

    def test_pressing_stop_says_stopping_not_stopped(self, console):
        """停止 is a request; the toast may only claim what the request did."""
        case = console['stopPress']
        assert case['toasts'] == ['STOPPING-TOAST'], case['toasts']
        assert case['statusText'] == 'STOPPING'

    def test_the_run_panel_is_kept_current_through_the_settling_window(self, console):
        """The row a user is watching is the run record, not the console.

        Refreshing the panel only while the server said `running` is what made a
        stopped run look ignored for half a minute: the record had already been
        flipped to 正在停止 by the Stop request, and nothing re-read it until the
        worker's verdict happened to land while a poll was looking.
        """
        settling = console['settlingTick']
        assert settling['refreshed'] == 1, 'the settling tick did not ask the panel to re-read'
        assert settling['toasts'] == [], 'the settling tick announced a verdict it did not have'
        assert settling['stillPolling'] is True
        settled = console['settledTick']
        assert settled['toasts'] == ['WORKFLOW-STOPPED'], settled['toasts']
        assert settled['stillPolling'] is False, 'the poller outlived the verdict'

    def test_the_record_being_stopped_has_its_own_word(self, console):
        """`stopping` is a status the record really holds; falling through to
        已完成 would print the opposite of the truth for the seconds it lasts, and
        the panel would offer 丢弃 on a run whose rows are still being written."""
        assert console['stoppingChip'] == 'runsMgr.status.stopping'
        assert console['stoppingIsAwaited'] is True
        assert console['settledIsNotAwaited'] is False

    def test_running_out_of_settle_budget_admits_it_instead_of_guessing(self, console):
        """Past the budget the poller stops reading — but the worker was still
        unwinding, and `outcome` was the empty string. Inferring a verdict from that
        blamed the user's own button press on their workflow."""
        case = console['budgetExhausted']
        assert case['toasts'] == ['STILL-SETTLING'], case['toasts']
        assert case['statusText'] == 'STOPPING', 'the bar moved off 正在停止 without a verdict'
        assert case['stillPolling'] is False
        assert case['resumeRefreshed'] == 0, 'a continue offer was made for a run that had not settled'


class TestClearConsoleBeforeRun:
    """#177 — the option clears the console for a new run, and it must clear the
    TABS and their retained histories too, not just the visible line list."""

    def test_the_reset_drops_every_tab_and_history_and_moves_the_active_tab_back(self, console):
        reset = console['resetForNewRun']
        assert reset['wfTabCount'] == 0, 'per-workflow tabs survived the reset'
        assert reset['allSeen'] == 0 and reset['allLines'] == 0, 'the 全部 cursor/history survived'
        assert reset['tabsHtml'] == '', 'the tab bar markup survived, so the old run still shows its tabs'
        assert reset['outputHtml'] == '', 'the console body was not emptied'
        assert reset['activeTab'] == 'all', 'the reset left a now-nonexistent workflow tab active'

    def test_the_gate_only_clears_when_the_user_asks(self, console):
        # Absent settings (never pulled) and an explicit off must both leave the console
        # alone; only an explicit true clears. Absence is "follow the default", not "clear".
        assert console['clearDefaultFalse'] is True, 'an unpulled AppSettings must not force a clear'
        assert console['clearOnTrue'] is True, 'clear_console_before_run=true must clear'
        assert console['clearUnsetFalse'] is True, 'a valueless settings object must not clear'


class TestConsoleReconnect:
    """A refreshed page takes the console back up — 「页面一刷新，控制台信息就丢失了」.

    Nothing used to start the poll except the Run button, so F5 mid-run left an empty box
    over a crawl that was still writing. The server holds the lines (LOG_KEEP of them) and
    the run never noticed the tab go away, so the page asks for what it lost. Each case
    below is one way that answer could still be wrong.
    """

    def test_a_live_run_comes_back_whole_and_the_next_tick_adds_only_the_new_line(self, console):
        back = console['reconnectLive']
        assert back['painted'] == 200, f'the replay painted {back["painted"]} of the 200 the server shipped'
        assert (back['first'], back['last']) == ('L51', 'L250'), 'the wrong slice came back'
        assert back['seen'] == 250, 'the cursor did not reach the reported total, so the next poll replays'
        assert back['next'] == ['L251'], f'a reconnection must not reprint the tail it already showed: {back["next"]}'
        assert back['panelOpen'] is True, 'the log came back but the box that shows it stayed shut'
        assert back['running'] is True, 'the status bar must not still say 就绪 over a live run'
        assert back['polling'] is True, 'a refreshed page never took the stream up again'
        assert back['toast'] == ['RECONNECTED'], 'the panel opening by itself has to say why'

    def test_an_empty_buffer_opens_nothing(self, console):
        """Between runs the buffer is empty and no run is live. Painting an empty box and
        popping the panel open would read as a crash — this page has nothing to show."""
        idle = console['reconnectIdle']
        assert idle['painted'] == 0 and idle['panelOpen'] is False, idle
        assert idle['polling'] is False, 'a page with no run behind it must not poll every second'
        assert idle['running'] is False, 'the Run state was invented out of an empty buffer'

    def test_a_run_that_finished_while_the_page_was_closed_is_shown_not_re_announced(self, console):
        """The buffer outlives the run and is only cleared by the NEXT one claiming the
        slot, so 「刚才那次跑了什么」 is still answerable after a refresh. But the finish
        line — its toast, its resume offer — belongs to the tab that watched it end:
        reprinting it would offer a resume on every reload."""
        done = console['reconnectFinished']
        assert done['painted'] == 1, done
        assert done['statusText'] == 'completed' and done['statusNodes'] == 'progress 3/3', done
        assert done['polling'] is False, 'a finished run has nothing left to poll'
        assert done['toasts'] == [], f'the reconnect must not re-fire the ending: {done["toasts"]}'
        assert done['running'] is False, done
        assert done['panelOpen'] is False, (
            'work that ended an hour ago does not get to take over the screen on every load — '
            'the lines are painted and waiting, the panel stays where the user left it'
        )

    def test_a_parallel_reconnect_rebuilds_every_tab_and_keeps_each_history(self, console):
        """The tab bar is built by the poller, which a reconnected page has not started —
        so a parallel run came back as one shared box with no way to reach a workflow's
        own lines. Every view is loaded from the replay, including the tab nobody is on."""
        par = console['reconnectParallel']
        assert par['tabs'] == 3, f'expected 全部 + the two workflows, saw {par["tabs"]}'
        assert par['bSeen'] == 1 and par['bLines'] == ['b1'], 'the hidden tab had nothing to show when opened'
        assert par['allSeen'] == 2, par
        assert par['next'] == ['b2', 'b3'], f'the next poll replayed B: {par["next"]}'

    def test_two_boot_steps_cannot_start_two_readers_of_one_console(self, console):
        """The reason the poller now has one owner. Two intervals append the same line
        twice and the cursor cannot tell them apart, because both reads are valid."""
        twice = console['reconnectTwice']
        assert twice['painted'] == twice['afterFirst'] == 1, twice
        assert twice['lines'] == ['once'], f'the second reconnect duplicated the console: {twice["lines"]}'
