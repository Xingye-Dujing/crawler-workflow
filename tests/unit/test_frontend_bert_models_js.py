"""The bert-mode model picker, driven from the real ``workflow.js`` renderer.

``/api/models`` hands the browser friendly NAMES for fine-tuned models (「网暴模型」), and
``renderBertField`` turns that list into a name→path ``<select>`` above the raw path box.
The contract lives in the browser and the backend cannot see it, so each case is run
against the actual code:

  * a registered model's option VALUE is its PATH (what the run loads), the LABEL is the
    NAME (what the user reads);
  * a stored path that matches a registered model shows that option selected;
  * a stored path that matches NOTHING shows itself as 「不是可选项」, never reverting to
    the first model (the repo's standing "a stored value off the list is not option #0"
    rule);
  * a blank stored path selects the placeholder, not the first real model;
  * an empty or malformed registry draws NO picker at all — just the path box.
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

NB_PATH = 'C:\\models\\netbully'
OTHER_PATH = 'C:/models/second'
CUSTOM_PATH = 'D:\\somewhere\\else'


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
            {
                'id': 'blank',
                'models': [
                    {'name': '网暴模型', 'path': NB_PATH, 'desc': '六分类立场'},
                    {'name': 'second', 'path': OTHER_PATH},
                ],
                'params': {'bert_model': ''},
            },
            {
                'id': 'matches',
                'models': [{'name': '网暴模型', 'path': NB_PATH, 'desc': 'x'}, {'name': 'second', 'path': OTHER_PATH}],
                'params': {'bert_model': NB_PATH},
            },
            {
                'id': 'custom',
                'models': [{'name': '网暴模型', 'path': NB_PATH, 'desc': 'x'}],
                'params': {'bert_model': CUSTOM_PATH},
            },
            {'id': 'empty', 'models': [], 'params': {'bert_model': NB_PATH}},
            {'id': 'malformed', 'models': 'malformed', 'params': {'bert_model': CUSTOM_PATH}},
        ],
    )


def _selected(result):
    picked = [o for o in result['picker'] if o['selected']]
    assert len(picked) == 1, f'expected exactly one selected option, got {[o["value"] for o in result["picker"]]}'
    return picked[0]


class TestRegisteredPicker:
    def test_option_value_is_the_path_and_label_is_the_name(self, results):
        """The two halves of the picker, kept distinct: the run needs the path, the
        user reads the name. Swapping them would hand a friendly word to the loader."""
        by_value = {o['value']: o for o in results['blank']['picker']}
        assert NB_PATH in by_value, list(by_value)
        assert by_value[NB_PATH]['label'] == '网暴模型'
        assert by_value[OTHER_PATH]['label'] == 'second'

    def test_a_blank_path_selects_the_placeholder_not_the_first_model(self, results):
        """Defaulting a blank to option #0 would show 网暴模型 as chosen while bert_model
        is empty, and the run would refuse (an empty bert_model is refused by name)."""
        assert _selected(results['blank'])['value'] == ''

    def test_a_matching_stored_path_shows_its_own_option_selected(self, results):
        assert _selected(results['matches'])['value'] == NB_PATH

    def test_picking_a_name_fills_the_path_box_with_the_path(self, results):
        """The path box mirrors bert_model, so selecting a name is a shortcut to the
        value a hand-typed path would have produced — one field, not two opinions."""
        assert results['matches']['pathBoxValue'] == NB_PATH


class TestUnregisteredAndEmpty:
    def test_a_stored_path_that_is_not_registered_still_shows_itself(self, results):
        """selectOptionTags appends an unknown value as 「不是可选项」; a custom path the
        registry never heard of must remain the selection, never fall back to model #0."""
        assert _selected(results['custom'])['value'] == CUSTOM_PATH

    def test_the_unregistered_value_is_flagged_not_silently_reverted(self, results):
        """Beyond the selection: the appended option carries the unknownOption wording,
        so a stale path is visibly stale rather than pretending to be a live model."""
        unknown = [o for o in results['custom']['picker'] if o['value'] == CUSTOM_PATH]
        assert len(unknown) == 1
        assert 'settings.unknownOption' in unknown[0]['label']

    def test_an_empty_registry_draws_no_picker_but_keeps_the_path_box(self, results):
        """No named models is a complete answer: the picker disappears, the raw path box
        stays and still holds the stored path."""
        assert results['empty']['picker'] is None
        assert results['empty']['hasPathBox'] is True
        assert results['empty']['pathBoxValue'] == NB_PATH

    def test_a_malformed_payload_degrades_to_no_picker_not_a_crash(self, results):
        """BertModels.load() reads a payload with no ``models`` array as an empty list,
        so a bad registry can never take the settings panel down."""
        assert results['malformed']['picker'] is None
        assert results['malformed']['bertList'] == []
