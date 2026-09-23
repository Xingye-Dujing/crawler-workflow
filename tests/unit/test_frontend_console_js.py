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
