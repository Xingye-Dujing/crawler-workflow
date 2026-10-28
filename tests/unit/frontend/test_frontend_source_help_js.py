"""The export guide: its static contract in the page, and its served behaviour under node.

Two halves, like the other JS panels. The overlay is markup plus CSS plus a toggle three places
call, and any of those can rot without a single behaviour changing (an unstyled overlay opens as
nothing; a fourth close button that forgets the class leaves the scrim up). The other half is the
harness: what the panel paints when the server answers, refuses to paint when it does not, and
how it escapes what it is handed.

Wording is compared against the catalogs themselves, never against a pasted sentence.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from frontend_catalogue import catalog_bodies as _catalog_bodies
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
STATIC = REPO / 'backend' / 'static'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_source_help.mjs'

#: Keys the guide paints from the page and from JS; each must exist in both languages.
GUIDE_KEYS = [
    'sourceHelp.title',
    'sourceHelp.close',
    'sourceHelp.button',
    'sourceHelp.loading',
    'sourceHelp.unavailable',
    'sourceHelp.groupLibrary',
    'sourceHelp.groupExchange',
]


@pytest.fixture(scope='module')
def placed() -> dict:
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


def _markup() -> str:
    return (STATIC / 'index.html').read_text(encoding='utf-8')


def _css() -> str:
    return (STATIC / 'css' / 'style.css').read_text(encoding='utf-8')


def _js(name: str) -> str:
    return (JS_DIR / name).read_text(encoding='utf-8')


class TestTheOverlayIsBuiltLikeTheOthers:
    def test_the_page_holds_the_shell_the_renderer_writes_into(self):
        markup = _markup()
        for holder in ('source-help-overlay', 'source-help-box', 'source-help-body'):
            assert f'id="{holder}"' in markup, f'{holder} is missing from the page'

    def test_the_only_door_is_the_upload_panel_and_the_header_closes_it(self):
        markup = _markup()
        # The top menu used to carry a second entry; it was removed on request, so the one
        # opener is the button beside the file picker (built in JS, not in the page).
        assert 'onclick="toggleSourceHelp()"' not in markup
        assert markup.count('onclick="closeSourceHelp()"') == 1, 'the header closes it'
        assert _js('panels/settings.js').count('onclick="toggleSourceHelp()"') == 1

    def test_the_closer_is_reachable_from_escape_and_from_the_scrim_only(self):
        canvas = _js('canvas.js')
        escape_block = canvas[canvas.index("if (e.key === 'Escape')") : canvas.index("if (e.key === 'Escape')") + 700]
        assert 'closeSourceHelp' in escape_block, 'Escape closes the cheat sheet; this overlay is the same kind'
        assert 'if (event.target === box) self.close();' in _js('panels/source-help.js'), (
            'a click inside the sheet must not close it'
        )

    def test_the_stylesheet_sizes_the_box_and_toggles_display_by_class(self):
        css = _css()
        for selector in (
            '#source-help-overlay {',
            '#source-help-overlay.open {',
            '#source-help-box {',
            '#source-help-body {',
        ):
            assert selector in css, f'{selector} is missing; an unstyled overlay opens as nothing'
        block = css[css.index('#source-help-overlay {') : css.index('#source-help-overlay.open {')]
        assert 'display: none' in block and 'inset: 0' in block
        assert 'display: flex' in css[css.index('#source-help-overlay.open {') : css.index('#source-help-box {')]
        # The toggle never writes the property that would outrank those rules.
        assert placed_display_free()

    def test_every_word_the_guide_uses_exists_in_both_languages(self):
        bodies = _catalog_bodies()
        for key in GUIDE_KEYS:
            for lang in ('en', 'zh'):
                assert key in bodies[lang], f'{key} missing from the {lang} catalogue'
        # A defined word nobody asks for is a dead key; a word asked for nobody defined is a
        # raw string on screen. Both directions are checked, from the same literal list.
        asked = (
            _js('workflow.js') + _js('panels/settings.js') + _js('panels/source-help.js') + _js('app.js') + _markup()
        )
        for key in GUIDE_KEYS:
            assert f"'{key}'" in asked or f'data-i18n="{key}"' in asked, f'{key} is defined but never asked for'
        # The group headings are a literal map, not a spliced key: the audits only see literals.
        assert "GROUP_KEYS = { library: 'sourceHelp.groupLibrary', exchange: 'sourceHelp.groupExchange' }" in _js(
            'panels/source-help.js'
        )

    def test_the_page_still_lists_the_bibliographic_extensions_before_any_request(self):
        markup = _markup()
        accept = re.search(r'id="dataset-file-input"\s*\n?\s*accept="([^"]+)"', markup)
        assert accept, 'the file input lost its accept attribute'
        offered = accept.group(1).split(',')
        for extension in ('.net', '.ris', '.bib', '.enw', '.nbib'):
            assert extension in offered, f'{extension} is readable but not selectable'


def placed_display_free() -> bool:
    """The toggle only adds/removes a class; a `style.display` write would outrank the stylesheet."""
    source = _js('panels/source-help.js')
    block = source[source.index('var sourceHelp = {') : source.index('function toggleSourceHelp()')]
    return 'style.display' not in block


class TestTheGuideDrawsWhatTheServerSaid:
    def test_opening_asks_once_and_shows_a_waiting_line_rather_than_a_guess(self, placed):
        before = placed['beforeLanding']
        assert before['asked'] == ['/api/biblio/sources'], before
        assert before['loading'] is True, 'an empty box reads as a broken panel, not a loading one'
        assert before['paintedSources'] is False, 'no source may be listed before the server answered'
        assert before['opened'] is True
        assert before['styleWritten'] is False

    def test_the_answer_arrives_and_the_sources_are_listed(self, placed):
        assert placed['afterLanding']['asked'] == 1, 'one request per open, not one per repaint'
        assert placed['afterLanding']['hasItems'] is True

    def test_groups_are_ordered_as_the_server_groups_them(self, placed):
        guide = placed['guide']
        assert guide['libraryFirst'] is True
        assert len(guide['groupOrder']) == 2, guide['groupOrder']

    def test_a_site_is_a_link_the_user_can_copy_and_that_opens_safely(self, placed):
        guide = placed['guide']
        assert guide['linkAttrs'] is True, 'href+target+rel="noopener noreferrer" or no anchor at all'
        assert guide['urlAsText'] is True, 'the visible text is the URL, so it survives a blocked popup'
        assert guide['noEmptyAnchor'] is True, 'a source without a site gets no empty link'
        assert guide['sitelessRendered'] is True, 'and it is still listed'

    def test_the_gaps_a_real_export_has_are_shown_as_the_server_words_them(self, placed):
        guide = placed['guide']
        assert guide['missingLine'] is True
        assert guide['steps'] >= 5, f'the served steps were not rendered: {guide["steps"]}'
        assert guide['extensionsShown'] is True, 'the file types come from the registry entry'

    def test_the_picker_offers_exactly_the_registry_list_plus_what_it_already_had(self, placed):
        accept = placed['accept']
        offered = accept['value'].split(',')
        assert accept['gained'] is True and accept['keepsOrdinary'] is True, offered
        assert len(offered) == len(set(offered)), f'a merged accept list duplicated an extension: {offered}'

    def test_a_refused_guide_names_the_reason_and_draws_nothing(self, placed):
        refused = placed['refused']
        assert refused['prefix'] is True, 'the sentence starts with the catalogue words for this case'
        assert refused['namesReason'] is True, 'the server own reason has to appear'
        assert refused['paintedSources'] is False

    def test_served_values_are_escaped_in_text_and_in_attribute(self, placed):
        escaped = placed['escaped']
        assert escaped['noRawScript'] and escaped['attributeClosed'] and escaped['purposeEscaped']
        assert escaped['escapedLabel'] is True
        assert escaped['quoteEscaped'] is True, 'a step containing quotes still cannot break out'

    def test_open_close_is_one_class_and_only_the_scrim_closes_it(self, placed):
        toggle = placed['toggle']
        assert toggle['closed'] is True and toggle['reopened'] is True
        assert toggle['backdropListeners'] == 1, 'bound once, however many times the guide opens'
        assert toggle['closedBySheet'] == 'kept-open/scrim-closed', toggle['closedBySheet']

    def test_a_language_switch_refetches_only_while_the_guide_is_open(self, placed):
        refetch = placed['refetch']
        assert refetch['whileClosed'] == refetch['seen'], 'a closed overlay has nobody waiting for it'
        assert refetch['whileOpen'] is True, 'the sentences are served per language'
