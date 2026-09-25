"""Behaviour tests for the workflow-file panel (#115).

The panel is the only way to open a saved canvas by name, so two mistakes here are
user-visible data events rather than cosmetics: a row that does not say which file
is currently open invites 打开 over the user's own unsaved edits, and a stem with a
double quote in it would close the ``onclick="…"`` attribute the table is built with
and turn the rest of the name into markup — which is why the run panel's buttons
carry only a hex id. Names cannot, so they go through one escaper that satisfies the
JS literal *and* the HTML attribute.

The harness runs the real ``wfFiles.render`` in node; the page/CSS wiring it depends
on is checked statically below, because the harness stubs the DOM and cannot see
index.html at all.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

REPO = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_wfmgr.mjs'
STATIC = REPO / 'backend' / 'static'
WORKFLOW_JS = STATIC / 'js' / 'workflow.js'
INDEX_HTML = STATIC / 'index.html'
STYLE_CSS = STATIC / 'css' / 'style.css'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]


@pytest.fixture(scope='module')
def rendered() -> dict:
    proc = run_node(str(HARNESS), str(WORKFLOW_JS))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestRenderedTable:
    def test_the_open_file_is_marked_and_others_are_not(self, rendered):
        assert '日报 <span class="runs-mgr-cur">open</span>' in rendered['current']
        assert rendered['escaped'].count('runs-mgr-cur') == 1  # the broken chip, nothing else

    def test_node_count_and_modified_column_render(self, rendered):
        assert '>3<' in rendered['current']
        assert '2025-10-09 16:53' in rendered['current']

    def test_empty_list_renders_the_empty_state(self, rendered):
        assert rendered['empty'] == '<div class="runs-mgr-empty">EMPTY</div>'
        assert rendered['noRowsKey'] == ''

    def test_an_unknown_mtime_reads_as_nothing_not_the_epoch(self, rendered):
        assert rendered['when'] == {'stamped': '2025-10-09 16:53', 'unknown': '', 'garbage': ''}

    def test_a_broken_file_stays_deletable_but_cannot_be_opened(self, rendered):
        row = rendered['brokenRow']
        assert row == {'opens': False, 'renames': True, 'removes': True, 'chip': True}


class TestQuoting:
    def test_the_argument_handed_to_open_is_the_name_on_disk(self, rendered):
        assert rendered['quotedRow']['openArg'] == "it's <img src=x onerror=alert(1)>"

    def test_a_name_is_text_never_a_tag(self, rendered):
        assert rendered['quotedRow']['imgElement'] is False

    def test_a_double_quote_does_not_close_the_attribute(self, rendered):
        # `intact` is a regex over ONE attribute value; an unescaped quote in the
        # name truncates the capture and the pattern stops matching.
        assert rendered['ampRow'] == {'present': True, 'once': True, 'intact': True}


class TestLanguageSwitch:
    def test_a_closed_panel_neither_fetches_nor_repaints(self, rendered):
        closed = rendered['closedRepaints']
        assert closed['fetches'] == 0
        assert 'runs-mgr-cur' in closed['html']

    def test_an_open_panel_repaints_from_the_rows_it_holds(self, rendered):
        opened = rendered['openRepaints']
        assert opened['fetches'] == 0, 'a language switch must not re-read the disk'
        assert opened['currentChip'] is True


class TestPageWiring:
    """The panel is built by JS into a container that only index.html provides."""

    def test_the_panel_containers_exist_in_the_page(self):
        page = INDEX_HTML.read_text(encoding='utf-8')
        for element_id in ('workflows-panel', 'workflows-resize-handle', 'workflows-mgr-body', 'btn-workflows'):
            assert f'id="{element_id}"' in page, element_id

    def test_both_openers_call_the_global_toggler(self):
        page = INDEX_HTML.read_text(encoding='utf-8')
        assert page.count('toggleWorkflowsPanel()') == 3, 'the menu, the status button and the panel close'
        assert 'wfFiles.refresh()' in page, 'the header button must re-read the list'
        source = WORKFLOW_JS.read_text(encoding='utf-8')
        assert re.search(r'function toggleWorkflowsPanel\(\)\s*\{\s*wfFiles\.toggle\(\);', source)

    def test_the_panel_is_a_docked_mutual_exclusive_one(self):
        source = WORKFLOW_JS.read_text(encoding='utf-8')
        docked = re.search(r'var DOCKED_PANELS = \[(.*?)\];', source, re.S).group(1)
        assert "'workflows-panel'" in docked

    def test_the_css_sized_for_the_other_docks_covers_it_too(self):
        css = STYLE_CSS.read_text(encoding='utf-8')
        for selector in (
            '#workflows-panel',
            '#workflows-panel.open',
            '#workflows-resize-handle',
            '#workflows-mgr-body',
        ):
            assert re.search(re.escape(selector) + r'[,{\s]', css), selector
