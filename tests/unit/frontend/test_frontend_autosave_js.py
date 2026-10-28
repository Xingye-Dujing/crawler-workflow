"""Behaviour tests for the autosave + dirty-guard logic in the REAL workflow.js.

workflow.js owns the substantive code — `scheduleAutosave` (a debounce armed only when a
file is already open AND the canvas is dirty), `_autosaveToFile` (the silent POST that then
clears dirty), and `installDirtyGuard` (the beforeunload warning). app.js only wires the
guard; the browser integration tier verifies that wiring. The debounce needs a controllable
timer, which is why this harness replaces setTimeout rather than running on the shared
baseSandbox one. See tests/frontend/harness_autosave.mjs.

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
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_autosave.mjs'


@pytest.fixture(scope='module')
def ax():
    proc = run_node(str(HARNESS), str(JS_DIR / 'canvas.js'), str(JS_DIR / 'workflow.js'))
    assert proc.returncode == 0, f'autosave harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestArmedAutosave:
    def test_a_dirty_open_file_schedules_exactly_one_timer(self, ax):
        assert ax['fire']['pendingAfterSchedule'] == 1
        assert ax['fire']['dirtyBefore'] is True

    def test_the_timer_writes_the_open_file_once(self, ax):
        fire = ax['fire']
        assert fire['postCount'] == 1, 'a debounce that still saved twice would thrash the file'
        assert fire['postName'] == 'wfA', 'autosave must write the CURRENT file, not a new name'

    def test_the_save_is_silent(self, ax):
        """A background save that toasts every few seconds is noise, not feedback."""
        assert ax['fire']['silent'] is True

    def test_a_successful_save_clears_dirty(self, ax):
        assert ax['fire']['dirtyAfter'] is False, 'the file is on disk; the dirty dot must go away'

    def test_autosave_is_armed_by_the_save_state_chokepoint(self, ax):
        """A real mutation (addNode) runs saveState, which is what schedules the autosave —
        the gate is not only reachable by calling scheduleAutosave directly."""
        assert ax['chokepoint']['scheduledByMutation'] is True


class TestAutosaveGates:
    def test_no_open_file_means_no_autosave(self, ax):
        """An unnamed canvas must never be auto-created; autosave only keeps an OPEN file fresh."""
        assert ax['noFile']['pending'] == 0

    def test_a_clean_canvas_schedules_nothing(self, ax):
        assert ax['notDirty']['pending'] == 0

    def test_rapid_changes_debounce_to_one_timer(self, ax):
        assert ax['debounce']['pending'] == 1, 'the second schedule must cancel the first'


class TestDirtyGuard:
    def test_the_guard_registers_one_beforeunload_listener(self, ax):
        assert ax['guard']['listeners'] == 1

    def test_an_unsaved_close_is_warned_about(self, ax):
        guard = ax['guard']['dirtyTriggers']
        assert guard['prevented'] is True
        assert guard['returnValue'] == '', 'returnValue="" is the modern cross-browser way to prompt'

    def test_a_clean_close_is_not_blocked(self, ax):
        assert ax['guard']['cleanDoesNotTrigger']['prevented'] is False

    def test_installing_twice_does_not_stack_listeners(self, ax):
        """A soft re-entry must not attach a second identical handler."""
        assert ax['guard']['idempotent'] is True
