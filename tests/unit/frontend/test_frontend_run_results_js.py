"""The loaded-run state behind 运行结果: which run a canvas is showing.

Node-side harness: ``harness_run_results.mjs`` loads the REAL ``workflow.js`` and
drives ``runResults`` against a fake server whose answers change between reads.
These assertions are about the three silent failures a screenshot cannot show —
the default is not the newest run, a preview payload forgot the run id (so the
server stitches each node's newest rows), or a live status tick overwrites the
historical record the user deliberately loaded.
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

JS_DIR = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_run_results.mjs'


@pytest.fixture(scope='module')
def rr():
    proc = run_node(str(HARNESS), str(JS_DIR / 'workflow.js'))
    assert proc.returncode == 0, f'run-results harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestDefaultSelection:
    def test_a_canvas_with_no_choice_loads_the_newest_run_and_its_verdicts(self, rr):
        """The user asked for the newest run on entry; "newest per node" is a
        different (and wrong) answer the server would otherwise give."""
        default = rr['defaultSelection']
        assert default['runId'] == 'r-live'
        assert default['rrRunId'] == 'r-live'
        assert default['selected']['node-1'] == {'status': 'done', 'row_count': 5, 'error': '', 'run_id': 'r-live'}
        assert default['selected']['node-2']['status'] == 'running'
        assert default['followLive'] is True, 'a live record must be followed, not frozen'

    def test_an_empty_canvas_clears_both_the_choice_and_the_badges(self, rr):
        empty = rr['emptyCanvas']
        assert empty['runId'] == ''
        assert empty['statuses'] == {}
        assert empty['applied'] == {}, 'the canvas kept the previous run’s marks'
        assert empty['payload'] == {'node_id': 'x'}, 'a cleared run must not pin an id'


class TestLoadingAHistoricalRun:
    def test_loading_replaces_the_map_and_pins_the_id_into_previews(self, rr):
        loaded = rr['loadOld']
        assert loaded['loaded'] == 'r-old' and loaded['rrRunId'] == 'r-old'
        assert loaded['selected']['node-1']['status'] == 'restored'
        assert loaded['selected']['node-2']['status'] == 'done'
        assert loaded['isLoaded'] is True
        assert loaded['previousNotLoaded'] is False, 'two records cannot both claim the screen'
        assert loaded['payloadRun'] == 'r-old', 'the preview would read the wrong attempt'
        assert loaded['toast'] == 'LOADED 2026-10-23T10:00:00'

    def test_live_ticks_do_not_yank_a_deliberately_loaded_record(self, rr):
        ignored = rr['liveIgnoredAfterHistoricalLoad']
        assert ignored['followLive'] is False
        assert ignored['status'] == 'restored', 'a running node overwrote the historical map'


class TestLiveFollow:
    def test_starting_a_run_clears_the_old_marks_before_the_first_tick(self, rr):
        begun = rr['beginLive']
        assert begun['followLive'] is True
        assert begun['runId'] == 'r-live'
        assert begun['applied'] == {}, 'the previous run’s green checks survived a new run'

    def test_two_nodes_can_run_at_once_and_a_tick_merges_instead_of_dropping(self, rr):
        """Parallel means SEVERAL nodes are yellow at the same moment; a status tick
        that only mentions node-1 must not erase node-2's spinner."""
        ticks = rr['liveTicks']
        assert ticks['bothRunning'] == ['running', 'running']
        assert ticks['merged'] == ['done', 'running']
        assert ticks['appliedBothRan'] is True

    def test_the_final_refresh_reads_the_settled_record_and_stops_following(self, rr):
        done = rr['finishLive']
        assert done['followLive'] is False
        assert done['runId'] == 'r-live'
        assert done['selected']['node-2'] == {'status': 'done', 'row_count': 2, 'error': '', 'run_id': 'r-live'}
        assert done['askedForWorkflow'] is True, 'the final map came from the last tick, not the ledger'


class TestRerunGate:
    def test_only_a_settled_node_with_rows_can_be_replayed_and_the_record_is_the_owner(self, rr):
        gate = rr['canRerun']
        assert gate['doneWithRows'] is True
        assert gate['runningNode'] is False
        assert gate['missingNode'] is False
        assert gate['zeroRows'] is False
        assert gate['ownerOfNode'] == 'r-live'
