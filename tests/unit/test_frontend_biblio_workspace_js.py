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
from frontend_catalogue import catalog_keys as _catalog_keys
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

    def test_two_doors_open_it_and_both_use_the_one_toggle(self):
        """Status bar and the panel's own Close — the top bar's duplicate was removed on request.
        A Close wired to something else is a panel that opens twice, and the dock matrix cannot
        see it because it drives the toggler."""
        assert len(re.findall(r'onclick="toggleBiblioPanel\(\)"', _markup())) == 2
        assert 'id="btn-biblio-dock"' in _markup()
        assert 'id="btn-biblio"' not in _markup(), 'the top-bar duplicate is gone'

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
        # The keys the panel ASKS for come from its call sites; whether each is declared is asked of
        # the whole browser dictionary (app.js's remainder plus every js/i18n/<domain>.js). A name
        # ending in '.' is a composition root (`'biblioWs.shape.' + kind`), not a word of its own.
        used = {key for key in re.findall(r"'(biblioWs\.[\w.]+)'", _js('workflow.js')) if not key.endswith('.')}
        assert used, 'the panel has no catalogue words'
        keys = _catalog_keys()
        missing = [f'{key} in {lang}' for key in sorted(used) for lang in ('en', 'zh') if key not in keys[lang]]
        assert missing == [], f'the dock asks for words no catalogue defines: {missing}'


# ─── what the panel prints (driven against the real workflow.js) ───────────


class TestServerAnswersAreNotInvented:
    def test_no_recorded_run_says_so_and_asks_only_the_two_lists(self, placed):
        case = placed['empty']
        assert case['saidSo'] is True
        assert case['asked'] == ['/api/biblio/runs', '/api/biblio/projects'], 'what did the dock ask for?'
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

    def test_a_newly_shipped_shape_gets_its_word_without_a_second_list(self, placed):
        """`variation` was added to the server without touching the panel's own literal copy of
        the known shapes, and the copy is what decided whether the chip said 结构变异表 or
        「输出形态未知」. The panel now reads the same list the settings select does."""
        assert placed['shape']['variation'] is True

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


class TestCapturesAndDiff:
    def test_a_capture_that_cannot_happen_is_refused_before_it_is_sent(self, placed):
        """No project chosen → the button is dead AND says why, and nothing was POSTed.
        A disabled control with no reason beside it reads as a broken panel."""
        case = placed['captureBlocked']
        assert case['disabled'] is True
        assert case['reason'] is True
        assert case['sent'] == 0, 'the panel sent a capture it knew would be refused'

    def test_with_a_project_the_button_lives_and_the_kept_captures_are_listed(self, placed):
        case = placed['captureReady']
        assert case['enabled'] is True
        assert case['listsSnapshots'] is True
        assert case['paramsWords'] is True, 'verified / not-verified is the server claim about provenance'
        assert case['compareDisabledWithoutBaseline'] is True

    def test_the_create_button_is_an_element_and_not_swallowed_text(self, placed):
        """An `onclick` whose quote never closed turned the rest of the bar into a text node —
        the panel looked intact to the DOM stub and was broken in Chrome."""
        case = placed['captureReady']
        assert case['createButton'] is True
        assert case['noStrayMarkup'] is True

    def test_setting_a_baseline_enables_the_other_capture_and_prints_the_diff(self, placed):
        case = placed['diff']
        assert case['compareEnabled'] is True
        assert case['title'] is True
        assert case['askedUrl'] == '/api/biblio/compare?a=s-1&b=s-2'
        assert case['paramsLine'] is True, 'the parameter that moved is the headline, not a footnote'
        assert case['nodesLine'] is True
        assert case['changedCell'] is True
        assert case['capped'] is True, '31 added links with one listed must say so'
        assert case['hidden'] is True

    def test_an_identical_pair_says_so_without_empty_headings(self, placed):
        case = placed['diffQuiet']
        assert case['saidSo'] is True
        assert case['noHeadings'] is True


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


class TestColumnHeaders:
    """A header is interface text; the name on disk is a separate fact the user still needs."""

    def test_no_header_prints_its_catalogue_key(self, placed):
        assert placed['headers']['rawKey'] is False

    def test_every_header_is_the_word_this_language_holds_for_that_column(self, placed):
        assert placed['headers']['agreed'] == [True] * len(placed['headers']['pairs']), placed['headers']

    def test_a_column_this_build_has_no_word_for_keeps_its_stored_name(self, placed):
        """Inventing a heading, or printing 「biblio.col.cluster_id」, both describe a column the
        export does not have."""
        assert placed['headers']['unknownKept'] is True

    def test_the_stored_name_survives_as_the_tooltip(self, placed):
        """The word replaces the name on screen, so the name — what the CSV/GraphML header says —
        has to stay reachable or the table cannot be matched back to the file."""
        assert [name for name, _word in placed['headers']['pairs']] == [
            'map',
            'source',
            'weight',
            'x',
            'y',
            'label',
            'cluster_id',
        ]


class TestTypingFields:
    def test_both_typing_fields_are_marked_for_the_repaint(self, placed):
        assert placed['fields']['marked'] is True

    def test_only_the_marked_field_inside_the_panel_is_asked_about(self, placed):
        assert placed['fields']['askedInside'] is True
        assert placed['fields']['askedOutside'] is True
        assert placed['fields']['askedUnmarked'] is True

    def test_the_caret_is_put_back_in_the_field_that_replaced_it(self, placed):
        """The repaint destroys the element the user was typing in; a focus() without the caret
        lands it at position 0, so the next character arrives in the middle of the word."""
        assert placed['fields']['restore'] == ['[data-biblio-keep="search"]', 'focus', [2, 2]]

    def test_the_rebuilt_pickers_are_handed_to_custom_select(self, placed):
        """A native <select> is OS-drawn: white in a dark panel. Waiting for the body-level
        observer means a frame of un-themed control every keystroke, so the panel scans its own
        subtree — and the scan has to be pointed AT that subtree, not at the whole document."""
        assert placed['fields']['scans'] == 1
        assert placed['fields']['scannedRoot'] == 'panel'

    def test_the_stylesheet_themes_the_panels_own_fields(self):
        """These inputs carry no .settings-input class, so without a rule of their own they are
        UA-painted: a white box with black text on the dark panel."""
        css = (STATIC / 'css' / 'style.css').read_text(encoding='utf-8')
        block = css[css.index('.biblio-bar select,') :]
        rule = block[: block.index('}')]
        for declaration in ('background: transparent', 'color: var(--text)', 'border: 1px solid var(--line)'):
            assert declaration in rule, f'{declaration} missing from the field rule:\n{rule}'
        assert '.biblio-bar input::placeholder {' in css, 'the placeholder has no themed colour'
