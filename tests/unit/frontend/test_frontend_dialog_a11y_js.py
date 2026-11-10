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


class TestOneShellOnePendingAnswer:
    """A second ``showDialog`` may not leave the first promise unsettled, and may not steal a
    mandatory dialog's screen. Reproduced on the REAL shell because ``harness_accounts.mjs`` stubs
    ``showDialog`` — so the forced-password reopen guard, which resets in the promise's ``.then``,
    never met the code that used to strand it: once stranded, every later 403 returned early and the
    password debt could not be paid on that page at all."""

    def test_the_newcomer_paints_over_a_dismissable_dialog(self, d):
        assert d['replacedMessage'] == '第二个', 'the second dialog never reached the screen'
        assert d['replacedButtons'] == 1, 'the replaced dialog left its buttons standing'

    def test_a_replaced_dialog_is_answered_not_abandoned(self, d):
        assert d['superseded'] == ['gone', 'erased', 'c'], d['superseded']

    def test_a_mandatory_dialog_holds_the_shell(self, d):
        assert d['forcedStillOnScreen'] is True, 'the password debt was painted over'
        assert d['intruderAnswered'] == 'blocked', 'the displaced caller was left hanging'

    def test_answering_the_mandatory_dialog_frees_the_shell(self, d):
        assert d['forcedSettled'] == 'save'
        assert d['shellFreeAgain'] is True, 'the shell stayed locked after the debt was paid'


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
        assert d['dismissedByEsc'] is True

    def test_the_close_button_names_itself_in_the_ui_language(self, d):
        """The corner X used a hardcoded English ``aria-label`` and carried no tooltip, so a zh
        screen reader announced "Close" and a sighted user hovering it got nothing."""
        assert d['closeAriaLabel'] == 'Close dialog', d
        assert d['closeTitle'] == 'Close dialog', d
        assert d['closableAnswered'] is True

    def test_a_second_toast_is_not_hidden_by_the_first_ones_deadline(self, d):
        """Both messages share #toast; without cancelling the first timer the newer sentence
        vanished whenever the older one expired (300 ms later in the reported repro)."""
        assert d['toastPendingDeadlines'] == 1, "the first toast's timer was not cancelled"
        assert d['toastShownBeforeDeadline'] is True
        assert d['toastText'] == '第二条', 'the trap must not swallow the pre-existing Esc dismissal'
