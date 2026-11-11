"""The 采集校验 panel and the 反向筛选 block, as a real browser renders them.

The two features decide their roles by CONNECTION ORDER. The Python side proves that order is
honoured (``tests/unit/analysis/test_anti_join.py``, ``test_verify_node.py``); only the rendered
page can prove the user is TOLD which wired table fills which role — and that the card follows
a ``swap_tables`` edit instead of describing the opposite question from the run.

See tests/frontend/harness_verify_panel.mjs.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

from services.analysis.matching import COUNT_MODES, KEEP_MODES, MATCH_MODES

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[3]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_verify_panel.mjs'


@pytest.fixture(scope='module')
def panel() -> dict:
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, f'harness failed: {proc.stderr[-3000:]}'
    return json.loads(proc.stdout)


class TestTheAuditPanelSaysWhatItCompares:
    def test_the_type_is_named_with_a_word_not_a_key(self, panel):
        assert panel['verify_type_word'] not in ('nodeType.verify', '')
        assert panel['verify_header_uses_word'] is True
        assert panel['verify_raw_key'] is False

    def test_both_wired_tables_are_named_with_their_roles(self, panel):
        assert panel['verify_role_line'] is True, panel['verify_role_words']
        assert panel['verify_names_p1'] is True
        assert panel['verify_names_p2'] is True

    def test_the_recommended_way_to_build_the_two_tables_is_on_the_panel(self, panel):
        """The post table → comment table pairing is the workflow this node exists for; a
        panel that only offered two column boxes would leave the user to invent it."""
        assert panel['verify_hint_shown'] is True
        assert panel['verify_values'] == [True, True, True]

    def test_the_card_names_the_parents_and_flips_when_the_tables_are_swapped(self, panel):
        assert panel['verify_summary_names_p1'] is True
        assert panel['verify_summary_names_p2'] is True
        assert panel['verify_swap_flips'] is True

    def test_one_wire_is_a_refusal_the_panel_states(self, panel):
        assert panel['verify_needs_two'] is True

    def test_a_number_edit_repaints_the_panel(self, panel):
        assert panel['verify_edit_lands'] is True
        assert panel['verify_edit_repaints'] is True

    def test_the_connection_warning_has_its_own_two_wire_sentence(self, panel):
        """The generic "only the first table is used" warning would be wrong here."""
        assert panel['verify_conn_category'] == 'fanin_verify'


class TestTheExcludeStepSaysWhatItFilters:
    def test_the_two_roles_are_named_on_the_panel(self, panel):
        assert panel['anti_role_line'] is True, panel['anti_role_words']
        assert panel['anti_names_p1'] is True
        assert panel['anti_names_p2'] is True

    def test_the_question_and_its_modes_are_spelled_out(self, panel):
        assert panel['anti_hint_shown'] is True
        assert panel['anti_mode_options'] is True

    def test_the_card_names_the_filtered_table_and_the_basis(self, panel):
        assert panel['anti_summary_names'] is True
        assert panel['anti_summary_uses_word'] is True

    def test_the_panels_mode_lists_are_the_backend_lists(self, panel):
        """A second copy of the vocabulary in the panel is a choice the run would not honour."""
        assert panel['match_modes'] == list(MATCH_MODES)
        assert panel['count_match_modes'] == list(COUNT_MODES)
        assert panel['keep_modes'] == list(KEEP_MODES)
