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

    def test_switching_tabs_re_renders_the_view_being_entered(self, console):
        """The DOM is emptied on a tab switch, so the entered view has to be
        re-rendered from what the server holds — 'all' used to reset nothing and
        come back blank while a per-workflow tab re-rendered fine."""
        assert console['afterTabSwitch'] == 1


class TestRunEndReporting:
    def test_the_cookie_expiry_toast_shouts_once_per_run(self, console):
        """Polling is once a second: the same sentence every second would bury the
        console it is supposed to draw attention to."""
        assert console['expiryToasts'] == ['COOKIE-EXPIRED']

    def test_a_run_that_left_nodes_unfinished_does_not_claim_completion(self, console):
        toasts = console['endToastPartial']
        assert toasts == ['WORKFLOW-ENDED 2/3'], toasts
        assert 'WORKFLOW-COMPLETED' not in toasts

    def test_the_parallel_view_offers_one_tab_per_workflow(self, console):
        assert console['tabCount'] == 3, 'all + the two workflows'

    def test_a_workflow_tab_shows_only_its_own_lines(self, console):
        assert console['tabB'] == ['b-only', 'b-two']
