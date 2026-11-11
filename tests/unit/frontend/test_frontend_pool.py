"""The saved-logins dock with the account/exit pool switched on, run under node.

With the feature off the dock must be byte-for-byte the table it was. With it on, the state
and exit columns come from the server's numbers (a browser-side clock must never decide that
a cooldown has expired), a lever posts the pair of the ROW it was pressed on, and the exit
inventory arrives without its credential.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = pytest.mark.unit

JS_DIR = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_pool.mjs'


@pytest.fixture(scope='module')
def panel():
    if shutil.which('node') is None:
        pytest.skip('node not on PATH')
    proc = run_node(HARNESS, JS_DIR / 'workflow.js')
    assert proc.returncode == 0, f'harness failed: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


def test_with_the_feature_off_the_dock_is_unchanged(panel):
    case = panel['featureOff']
    assert case['tabs'] == 0, case
    assert case['headerCells'] == [
        'cookies.colPlatform',
        'cookies.colAccount',
        'cookies.colEntries',
        'cookies.colSavedAt',
        'cookies.colActions',
    ], case
    assert case['firstRowCells'] == 5, case
    assert case['firstRowButtons'] == ['cookies.renameOne', 'cookies.deleteOne'], case


def test_the_state_comes_from_the_server_and_says_until_when(panel):
    case = panel['featureOn']
    assert case['headerCells'][4:6] == ['pool.colState', 'pool.colExit'], case
    cooling = case['coolingRow']
    assert 'pool.state.cooling' in cooling[4], cooling
    assert '2026-11-11 20:00' in cooling[4], cooling
    assert cooling[5] == '', 'no exit is bound yet, so the cell shows the automatic choice'


def test_each_row_offers_the_levers_of_its_own_state(panel):
    case = panel['featureOn']
    assert 'pool.resetOne' in case['coolingButtons'], case
    assert 'pool.disableOne' in case['coolingButtons'], case
    assert 'pool.resetOne' not in case['healthyButtons'], case
    assert case['coolingBinding'] == ['', 'p_1'], case
    assert case['healthyBinding'] == ['', 'p_1'], case


def test_a_lever_posts_the_row_it_was_pressed_on(panel):
    assert panel['resetRow']['posted'] == [{'platform': 'weibo', 'account': 'work'}], panel['resetRow']
    assert panel['resetRow']['toasts'] == ['UNFROZEN'], panel['resetRow']
    assert panel['disableRow']['posted'] == [{'platform': 'weibo', 'account': 'home', 'disabled': True}], panel[
        'disableRow'
    ]


def test_the_exit_tab_names_addresses_and_never_a_credential(panel):
    case = panel['exits']
    assert case['hasCredentialField'] is False, case
    assert case['rows'][0][0] == 'hk03', case
    assert '10.0.0.1:8080' in case['rows'][0][1], case
    assert 'pool.exit.save' in case['saveButton'], case


def test_the_record_tab_renders_the_audit_rows(panel):
    assert panel['events'][0][0] == '2026-11-11 18:00:00', panel['events']
    assert 'pool.reason.loginWall' in panel['events'][0][1], panel['events']
    assert 'work' in panel['events'][0][2], panel['events']
