"""The multi-model BERT picker, driven from the real ``workflow.js`` renderer.

``renderBertField`` turns ``/api/models`` into a CHECKBOX per registered model, and
``toggleBertModel`` writes the chosen set as a sorted comma-joined ``bert_models``. The contract
lives in the browser and the backend cannot see it, so each case runs against the actual code:

  * one checkbox per registered model — LABEL is the friendly name, the value written is the PATH;
  * the stored ``bert_models`` echoes back (only paths in it come checked);
  * ≥2 checked reveals the tidy-table hint, so the row-count change is not a surprise;
  * an empty / malformed registry draws NO checkbox group — only the raw path box remains;
  * a single stored ``bert_model`` (a pre-multi-model canvas) still shows in the path box;
  * ``toggleBertModel`` de-dupes and SORTS, so click order cannot change the fingerprint.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_bert_models.mjs'

TWO = [{'name': 'M1', 'path': 'p1'}, {'name': 'M2', 'path': 'p2'}]


def _run(tmp_path: Path, scenarios: list) -> dict:
    file = tmp_path / 'scenarios.json'
    file.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR / 'canvas.js'), str(JS_DIR / 'workflow.js'), str(file))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


@pytest.fixture(scope='module')
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('bert-models')
    return _run(
        tmp,
        [
            {'id': 'empty', 'models': [], 'bert_model': ''},
            {'id': 'one', 'models': TWO, 'bert_models': 'p1'},
            {'id': 'two', 'models': TWO, 'bert_models': 'p1,p2'},
            {'id': 'echo_stored', 'models': [], 'bert_model': 'x/custom'},
            {
                'id': 'toggle_sort',
                'models': TWO,
                'bert_models': '',
                'toggle': [{'path': 'p2', 'checked': True}, {'path': 'p1', 'checked': True}],
            },
            {
                'id': 'toggle_remove',
                'models': TWO,
                'bert_models': 'p1,p2',
                'toggle': [{'path': 'p1', 'checked': False}],
            },
            {'id': 'malformed', 'models': 'malformed'},
        ],
    )


class TestCheckboxGroup:
    def test_one_box_per_model_with_the_friendly_name_as_label(self, results):
        assert results['one']['checkboxCount'] == 2
        assert results['one']['hasGroup'] is True

    def test_the_stored_selection_is_echoed_back_checked(self, results):
        assert results['one']['checkedNames'] == ['M1'], 'only p1 is in bert_models'
        assert results['two']['checkedNames'] == ['M1', 'M2']

    def test_two_checked_reveals_the_tidy_table_hint(self, results):
        assert results['one']['hasMultiHint'] is False, 'a single model keeps the old wide shape'
        assert results['two']['hasMultiHint'] is True

    def test_the_raw_path_box_is_always_present(self, results):
        assert results['one']['hasPathBox'] is True


class TestEmptyAndLegacy:
    def test_an_empty_registry_draws_no_group_but_keeps_the_path_box(self, results):
        assert results['empty']['hasGroup'] is False
        assert results['empty']['checkboxCount'] == 0
        assert results['empty']['hasPathBox'] is True

    def test_a_malformed_payload_degrades_to_the_empty_state_not_a_crash(self, results):
        assert results['malformed']['hasGroup'] is False

    def test_a_single_stored_bert_model_still_shows_in_the_path_box(self, results):
        # A canvas written before multi-model holds its path in bert_model; the picker must not
        # drop it (the raw box mirrors it), never silently reset to option #0 or blank.
        assert results['echo_stored']['pathBoxValue'] == 'x/custom'


class TestToggleWritesSorted:
    def test_click_order_is_normalised_into_a_sorted_string(self, results):
        # checked p2 then p1 — the stored value is SORTED, so one model set is one fingerprint.
        assert results['toggle_sort']['toggled'][-1] == 'p1,p2'

    def test_unchecking_removes_only_that_path(self, results):
        assert results['toggle_remove']['toggled'][-1] == 'p2'
