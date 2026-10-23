"""The 跨源融合 settings panel, as a real browser sees it.

The Python-side tests (`tests/unit/test_biblio_fuse.py`, `tests/api/test_fuse_api.py`) prove the
fold, the refusals and the run. They cannot see the panel at all, and the panel had two defects
that only the rendered markup shows: the type header printed the computed catalogue key
「nodeType.fuse」 because no browser word existed, and the node listed no output columns even
though the server answers for them — so a user could not see what the node would hand downstream.

See tests/frontend/harness_fuse_panel.mjs.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_fuse_panel.mjs'

#: The canonical record table a fusion node emits, in order (``biblio_fuse.OUTPUT_COLUMNS``).
COLUMNS = ['记录ID', '题名', '作者', '作者单位', '来源期刊', '年份', '关键词', '摘要', '参考文献', '来源']


@pytest.fixture(scope='module')
def panel() -> dict:
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


class TestTheHeaderSaysSomething:
    def test_the_type_is_named_with_a_word_not_a_key(self, panel):
        assert panel['type_word'] not in ('nodeType.fuse', ''), panel['type_word']
        assert panel['header_uses_word'] is True
        assert panel['raw_key_shown'] is False

    def test_an_unknown_type_reads_as_itself(self, panel):
        """A canvas stored by a newer build has a type with no word here. Printing the raw key
        claims to be a translation; printing the type is the file's own answer."""
        assert panel['unknown_type_shows'] == 'time_machine'
        assert panel['unknown_raw_key'] is False


class TestThePanelEditsWhatItShows:
    def test_every_candidate_column_field_is_labelled(self, panel):
        assert panel['labels_missing'] == []

    def test_every_stored_value_comes_back_out(self, panel):
        """A field that renders blank and writes its default on blur silently rewrites the canvas."""
        assert panel['values_missing'] == []

    def test_the_edit_lands_in_the_model_and_repaints_the_panel(self, panel):
        assert panel['edit_lands_in_model'] == '话题,标签'
        assert panel['edit_repaints'] is True

    def test_the_card_counts_the_columns_the_user_listed(self, panel):
        assert '5 candidate columns' in panel['summary_count'] or '5 个候选列' in panel['summary_count']
        assert '2 candidate columns' in panel['summary_after_edit'] or '2 个候选列' in panel['summary_after_edit']


class TestTheLineageIsVisible:
    def test_the_panel_and_the_server_agree_on_the_record_table(self):
        """The list below is the browser's expectation; the engine's is the fact. A rename on one
        side is a stale lineage line on the other, and only this comparison notices."""
        from services.biblio_fuse import OUTPUT_COLUMNS

        assert list(OUTPUT_COLUMNS) == COLUMNS

    def test_a_fusion_node_lists_the_columns_it_emits(self, panel):
        """The record table is a fixed contract, so hiding it costs the user the one thing a
        fusion node is for: knowing what downstream will read."""
        assert panel['lineage_shown'] is True
        missing = [c for c in COLUMNS if c not in panel['lineage_text']]
        assert missing == [], f'not named in the lineage line: {missing}'

    def test_an_unlisted_producer_stays_silent_rather_than_guessing(self, panel):
        assert panel['unknown_lineage'] is False
