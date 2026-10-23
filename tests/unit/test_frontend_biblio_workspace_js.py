"""The Bibliometrics Workspace dock: its markup contract and its real behaviour under node.

Two halves, because two different mistakes are possible. The panel is a dock, so it has to be
built the way the other nine are (ids, handle, close buttons, CSS, the resize wiring) — a dock
whose element the stylesheet never sizes opens as an invisible strip. And it prints a server
answer, so the wording has to come from that answer — which is what the harness drives.

The harness assertions are all "the panel said exactly what the server said, in the interface's
own words", evaluated inside the same sandbox rather than against a pasted sentence.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
STATIC = REPO / 'backend' / 'static'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_biblio_workspace.mjs'


@pytest.fixture(scope='module')
def placed() -> dict:
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


# ─── the dock contract (markup / CSS / wiring) ─────────────────────────────


def _js(name: str) -> str:
    return (JS_DIR / name).read_text(encoding='utf-8')


def _markup() -> str:
    return (STATIC / 'index.html').read_text(encoding='utf-8')


class TestTheDock:
    def test_the_panel_the_js_paints_into_exists_in_the_page(self):
        for marker in (
            'id="biblio-panel"',
            'id="biblio-resize-handle"',
            'id="biblio-mgr-body"',
        ):
            assert marker in _markup(), marker

    def test_three_doors_open_it_and_all_three_use_the_one_toggle(self):
        """Top bar, status bar and the panel's own Close — a Close wired to something else is a
        panel that opens twice, and the dock matrix cannot see it because it drives the toggler."""
        assert len(re.findall(r'onclick="toggleBiblioPanel\(\)"', _markup())) == 3
        assert 'id="btn-biblio"' in _markup() and 'id="btn-biblio-dock"' in _markup()

    def test_the_page_loads_the_file_that_defines_the_toggler(self):
        assert 'function toggleBiblioPanel()' in _js('workflow.js')

    def test_the_stylesheet_docks_sizes_and_scrolls_it(self):
        css = (STATIC / 'css' / 'style.css').read_text(encoding='utf-8')
        for selector in (
            '#biblio-panel {',
            '#biblio-panel.open,',
            '#biblio-resize-handle,',
            '#biblio-mgr-body',
        ):
            assert selector in css, selector

    def test_a_disabled_paging_button_looks_disabled(self):
        """The panel sets `disabled` at the first and last page; a button that still reads as
        clickable is the one symptom a screenshot caught and no assertion would have."""
        css = (STATIC / 'css' / 'style.css').read_text(encoding='utf-8')
        assert '.runs-mgr-btn:disabled {' in css

    def test_the_handle_really_gets_a_resize_handler(self):
        assert "initDockResize('biblio-resize-handle', 'biblio-panel');" in _js('app.js')

    def test_the_language_switch_repaints_it(self):
        """Every word in the dock is built by its own render(), so `I18n.apply()` never reaches
        it — the same bug class the other JS-rendered docks had."""
        assert 'biblioWorkspace.onLanguageChange()' in _js('workflow.js')

    def test_both_languages_hold_the_panels_words(self):
        src = _js('app.js')
        used = set(re.findall(r"'(biblioWs\.[\w.]+)'", src))
        assert used, 'the panel has no catalogue words'
        for key in used:
            assert src.count(f"'{key}'") >= 2, f'{key} is missing from one language'


# ─── what the panel prints (driven against the real workflow.js) ───────────


class TestServerAnswersAreNotInvented:
    def test_no_recorded_run_says_so_and_asks_once(self, placed):
        case = placed['empty']
        assert case['saidSo'] is True
        assert case['asked'] == 1, 'the panel asked more than the run list'
        assert case['hasTable'] is False

    def test_the_pickers_list_exactly_what_the_server_listed(self, placed):
        case = placed['pickers']
        assert case['runOptions'] == [
            '|(choose a run)',
            'run-7|文献计量演示 · 2026-10-23 12:00 · run-7',
            'run-3|Untitled · 2026-10-22 09:00 · run-3',
        ]
        assert case['nodeOptions'] == [
            '|(choose a node)',
            'node-2|关键词图谱 · Done · 38',
            'node-8|作者图谱 · Done · 5',
        ]
        assert case['runSelected'] is True and case['nodeSelected'] is True
        assert case['tableAsked'] == 1, 'opening the dock loads the first node once'

    def test_an_unreadable_shape_is_admitted_as_unknown_not_guessed(self, placed):
        case = placed['shape']
        assert case['nodes'] is True and case['dual'] is True
        assert case['unknown'] is True
        assert case['notGuessed'] is True, 'a shape the server did not name must not print 节点表'

    def test_a_refusal_keeps_the_servers_words_and_paints_no_table(self, placed):
        case = placed['refusal']
        assert case['printed'] is True
        assert case['hasTable'] is False
        assert case['askedOnce'] is True

    def test_an_empty_stored_table_names_the_node(self, placed):
        case = placed['emptyTable']
        assert case['notePrinted'] is True
        assert case['noRowsPainted'] is True
        assert case['unknownAdmitted'] is True


class TestPagingAndFiltering:
    def test_the_paging_line_describes_the_whole_table(self, placed):
        case = placed['paging']
        assert case['line'] is True, '「第 1–200 行 / 共 500 行」 is the server total, not the page size'
        assert case['prevDisabledAtFirst'] is True
        assert case['prevEnabledAfter'] is True
        assert 'offset=200' in case['nextUrl'] and 'limit=200' in case['nextUrl']

    def test_a_table_that_fits_one_page_has_no_second_page(self, placed):
        """Measured in a real browser: a 164-row table with a 200-row page could still be pushed
        to offset 163 and show its last row alone."""
        case = placed['singlePage']
        assert case['nextDisabled'] is True
        assert case['noExtraRequest'] is True
        assert case['offsetUntouched'] is True

    def test_a_filter_reports_how_many_it_left_without_rewriting_the_total(self, placed):
        case = placed['filter']
        assert case['kept'] is True and case['dropped'] is True
        assert case['saidHowMany'] is True
        assert case['totalStillServers'] is True


class TestLocateAndArtefacts:
    def test_locating_a_node_the_canvas_lost_says_so(self, placed):
        assert placed['locate']['saidSo'] is True

    def test_locating_a_node_the_canvas_holds_centres_it(self, placed):
        assert placed['locate']['centred'] == 'node-2'

    def test_artefact_links_carry_the_name_the_server_resolved(self, placed):
        """The browser sends back the name it was given, percent-encoded — it never assembles a
        path, which is the same rule the export panel's download follows."""
        assert placed['files']['link'] is True
        assert placed['files']['noFilesSaidSo'] is True

    def test_switching_language_repaints_the_dock(self, placed):
        case = placed['language']
        assert case['changed'] is True
        assert case['otherWordInAfter'] is True
        assert case['otherWordNotInBefore'] is True
