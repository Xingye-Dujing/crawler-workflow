"""Behaviour tests for the real durable run-log viewer (workflow.js).

The live console only ships a 200-line tail and is wiped when the next run starts, so the
after-the-fact viewer reads the persisted ``run_log`` instead. This harness drives the shipped
``runLogViewer`` against a recorded fetch and asserts the parts a user depends on — that a
line is escaped, that the filters ride into the request, that 「加载更早」 walks backward,
that the download names the same endpoint, and that the row button carries only the id.

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

JS = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js' / 'workflow.js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_runlog.mjs'


@pytest.fixture(scope='module')
def ix():
    proc = run_node(str(HARNESS), str(JS))
    assert proc.returncode == 0, f'runlog harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestOpenAndRender:
    def test_opening_pulls_one_page_of_the_persisted_log(self, ix):
        assert ix['firstGet'].startswith('/api/runs/r1/log')
        assert ix['firstHasLimit'] is True

    def test_a_saved_line_is_escaped_not_parsed(self, ix):
        """Log text is data. A traceback that contains ``<b>`` must render literally, or an
        attacker who controls a crawled field controls the viewer's DOM."""
        assert ix['escapedLine'] is True

    def test_levels_are_marked_so_the_css_colors_them(self, ix):
        assert ix['errorClassShown'] is True


class TestFilters:
    def test_the_level_filter_reaches_the_request(self, ix):
        assert 'level=error' in ix['levelGet']

    def test_workflow_tabs_are_discovered_from_the_loaded_rows(self, ix):
        # 「全部」 (empty) plus the two workflows the first page mentioned.
        assert ix['wfOptions'] == ['', '0', '1']

    def test_the_workflow_filter_reaches_the_request(self, ix):
        assert 'wf=1' in ix['wfGet']

    def test_the_search_text_reaches_the_request_url_encoded(self, ix):
        assert 'q=%E4%B8%89%E4%BA%9A' in ix['qGet']

    def test_every_filter_stacks_into_one_request(self, ix):
        assert 'level=error' in ix['qGet'] and 'wf=1' in ix['qGet'] and 'q=' in ix['qGet']


class TestPagingAndDownload:
    def test_load_older_walks_back_from_the_smallest_seq_shown(self, ix):
        assert 'before=2' in ix['olderGet']

    def test_older_lines_are_prepended_in_order(self, ix):
        """The merged view stays oldest→newest, so the run reads top-to-bottom like it ran."""
        assert ix['mergedOrder'] == ['older-1', '慢', 'hello <b>x</b>', '抓取失败']

    def test_download_names_the_same_filtered_endpoint(self, ix):
        assert ix['downloadUrl'].startswith('/api/runs/r1/log.txt?')
        assert 'level=warning' in ix['downloadUrl'] and 'wf=1' in ix['downloadUrl'] and 'q=' in ix['downloadUrl']


class TestMount:
    def test_the_run_row_grew_a_viewer_button(self, ix):
        assert ix['hasLogButton'] is True

    def test_the_button_carries_only_the_run_id(self, ix):
        # The id is hex we minted; a workflow name is user text and one double quote in it
        # would close the onclick attribute. The name must not reach the handler at all.
        assert ix['buttonCarriesId'] is True
        assert ix['nameNotInHandler'] is True

    def test_close_hides_the_overlay(self, ix):
        assert ix['closed'] is True
