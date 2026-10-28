"""Modal-dialog accessibility (workflow.js: showDialog): modal semantics, a Tab focus trap, and
the pre-existing Esc/backdrop dismissal. Esc already worked before U5; what is pinned here is the
new role/aria-modal/aria-labelledby and that Tab cannot escape the dialog while it is open. See
tests/frontend/harness_dialog_a11y.mjs.

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

JS_DIR = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_dialog_a11y.mjs'


@pytest.fixture(scope='module')
def d():
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, f'dialog-a11y harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestDialogA11y:
    def test_the_dialog_is_a_modal_for_screen_readers(self, d):
        assert d['open'] is True
        assert d['role'] == 'dialog'
        assert d['modal'] == 'true'
        assert d['labelledBy'] == 'dialog-message', 'the message is the dialog’s accessible name'

    def test_tab_stays_inside_the_dialog(self, d):
        assert d['tabAtLastFocused'] == 0, 'Tab on the last control must wrap to the first'
        assert d['shiftTabAtFirstFocused'] == 2, 'Shift+Tab on the first must wrap to the last'

    def test_escape_still_dismisses(self, d):
        assert d['dismissedByEsc'] is True, 'the trap must not swallow the pre-existing Esc dismissal'
