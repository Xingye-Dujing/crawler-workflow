"""The cloud-deployment switch, run against the REAL app.js + workflow.js.

``python app.py cloud`` is the server's own fact and the page learns it from
``/api/config.cloud_mode``. What the page then does is JS — which transport is offered,
which credential the run body carries, which word the process node prints — so the
Python suite cannot see any of it without executing the shipped files.

A desktop boot is asserted in the same breath as a cloud one on purpose: a flag that
only ever removes things is equally broken if it removes them when it should not, and
the half of this feature that must NOT change is the local machine's whole AI panel.

Skipped when node is not on PATH, like every other frontend harness.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
JS_DIR = ROOT / 'backend' / 'static' / 'js'
HARNESS = ROOT / 'tests' / 'frontend' / 'harness_cloud.mjs'


@pytest.fixture(scope='module')
def booted():
    if shutil.which('node') is None:
        pytest.skip('node not on PATH')
    proc = run_node(HARNESS, JS_DIR / 'canvas.js', JS_DIR /
                    'workflow.js', JS_DIR / 'app.js')
    assert proc.returncode == 0, f'harness failed: {proc.stderr[-2000:]}'
    return json.loads(proc.stdout)


class TestDesktopBootKeepsEverything:
    def test_both_transports_are_still_offered(self, booted):
        assert booted['desktop']['providers'] == [
            'ollama', 'openrouter'], booted['desktop']

    def test_a_stored_local_transport_stays_the_local_one(self, booted):
        """The normalization that moves a stored provider runs the other way on a machine
        that can serve it — otherwise this flag would silently switch a desktop user's
        runs to an API they never configured."""
        assert booted['desktop']['active'] == 'ollama', booted['desktop']
        assert booted['desktop']['payload'] == 'ollama', booted['desktop']

    def test_the_label_names_both_transports(self, booted):
        assert 'Ollama' in booted['desktop']['label'], booted['desktop']

    def test_the_flag_costs_no_extra_request(self, booted):
        """It rides the /api/config read the page already made at boot: a second fetch of
        the same payload is a second answer to keep in sync."""
        assert booted['desktop']['configAsked'] == 1, booted['desktop']


class TestCloudBoot:
    def test_the_page_says_what_it_was_told(self, booted):
        assert booted['cloud']['flag'] is True
        # CSS keys off this attribute, so it is the one thing that makes the hidden
        # controls hidden; a flag that lives only in JS hides nothing.
        assert booted['cloud']['dataCloud'] == '1', booted['cloud']

    def test_the_local_transport_is_taken_out_of_the_select(self, booted):
        """Not merely styled away: a hidden ``<option>`` is still a value the element can
        be asked for by keyboard, by a restore, or by an autofill."""
        assert booted['cloud']['providers'] == ['openrouter'], booted['cloud']

    def test_a_stored_local_transport_becomes_the_one_that_can_run(self, booted):
        cloud = booted['cloud']
        assert cloud['active'] == 'openrouter', cloud
        # The run body is the fact that matters: a body still naming 「ollama」 would be
        # refused by the server, and the user would see a refusal about a control they
        # were never shown.
        assert cloud['payloadProvider'] == 'openrouter', cloud

    def test_the_credential_that_travels_is_the_chosen_transports(self, booted):
        """Both halves at once: the OpenRouter key goes, and the Ollama tag does not.

        Normalising the transport without re-reading the model would have sent the local
        tag 「q:1」 to OpenRouter — a request that fails somewhere else's API with a
        message about a model id nobody typed there.
        """
        cloud = booted['cloud']
        assert cloud['payloadKey'] == 'sk-stored-here', cloud
        assert cloud['payloadModel'] == 'deepseek:free', cloud
        assert cloud['payloadModel'] != 'q:1', cloud

    def test_the_ollama_rows_are_re_applied_when_the_flag_lands(self, booted):
        """The panel is painted from localStorage before /api/config answers, so the flag
        has to trigger a re-apply — asserting an empty list here would pass on a page
        that never rendered the rows at all, hence the one-row expectation."""
        assert booted['cloud']['ollamaRowDisplay'] == ['none'], booted['cloud']

    def test_the_flag_also_turns_the_page_back_on(self, booted):
        """Every control here is a switch the server can be moved off of; a one-way flag
        would leave a desktop boot stripped after any config read that said cloud."""
        assert booted['turnsBack'] == {
            'flag': False, 'dataCloud': '0'}, booted['turnsBack']


class TestTheWordFollowsTheLanguage:
    def test_no_language_names_a_transport_the_host_lacks(self, booted):
        labels = booted['labels']
        for lang in ('zh', 'en'):
            assert 'Ollama' not in labels[f'{lang}_cloud'], labels
            assert 'Ollama' in labels[f'{lang}_desktop'], labels
        # Both cloud wordings still say what WILL be called, or the option becomes an
        # unexplained blank the user cannot choose between.
        assert 'OpenRouter' in labels['zh_cloud'] and 'OpenRouter' in labels['en_cloud'], labels


class TestTheChromeIsMarked:
    """The parts of this that are HTML and CSS rather than behaviour."""

    def test_the_controls_a_cloud_host_cannot_serve_are_marked(self):
        html = (JS_DIR.parent / 'index.html').read_text(encoding='utf-8')
        # The login-browser button and the Ollama address field carry the marker class…
        for needle in ('cookies.generate', 'set-ollamahost'):
            site = html.index(needle)
            assert 'cloud-hide' in html[site - 260: site +
                                        20], f'{needle} is not marked for a cloud boot'
        # …and the headless switch is NOT, because TopMenu.sync() rewrites that button's
        # className wholesale. It is hidden by id instead; a marker class here would be
        # erased on the first state change and the test would still look green.
        headless = html[html.index(
            'id="btn-headless"') - 200: html.index('id="btn-headless"') + 40]
        assert 'cloud-hide' not in headless, headless
        assert 'btn-headless' in headless

    def test_the_stylesheet_hides_the_marker_the_headless_switch_and_the_local_rows(self):
        css = (JS_DIR.parent / 'css' / 'style.css').read_text(encoding='utf-8')
        block = css[css.index('html[data-cloud="1"]')                    : css.index('html[data-cloud="1"]') + 320]
        for needle in ('.cloud-hide', '#btn-headless', '.ai-only-ollama'):
            assert needle in block, f'{needle} is not covered by the cloud rule: {block}'

    def test_the_process_node_asks_the_flag_instead_of_hardcoding_a_word(self):
        source = (JS_DIR / 'workflow.js').read_text(encoding='utf-8')
        assert 'llmModeLabel()' in source, 'the mode option went back to a fixed catalogue key'
        assert "I18n.t('mode.llm')" not in source, (
            'a label built straight from mode.llm names Ollama on a host that cannot run it'
        )

    def test_the_cloud_wording_exists_in_both_browser_catalogues(self):
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        assert app.count(
            "'mode.llmCloud'") == 2, 'both catalogues must carry the cloud wording'
        assert 'CloudMode' in app, 'the flag stopped being read from /api/config'


class TestTheFirstEntryNotice:
    """What a stranger on a shared server is told, and what their answer means."""

    def test_a_desktop_boot_never_shows_it(self, booted):
        """The person in front of a desktop IS the machine's owner; 「your cookies live on
        this disk」 is not news to them, and a dialog that appears where it explains nothing
        trains the user to dismiss the one that matters."""
        assert booted['desktop']['dialogs'] == [], booted['desktop']

    def test_the_first_cloud_visit_is_told_once(self, booted):
        dialogs = booted['firstVisit']['dialogs']
        assert len(dialogs) == 1, dialogs
        # Asserted as "a word, not a key" rather than as the English text: this harness
        # loads app.js's REAL dictionary, so pinning the sentence would make the test
        # track translations, while a raw `privacy.*` on screen is the defect.
        for label in dialogs[0]['labels']:
            assert label and not label.startswith(
                'privacy.'), f'the button printed a key: {label}'
        # The button values are the contract: 「不再提醒」 is the only one that writes an ack,
        # and the ordinary close resolves null. A `value` on the close button would make
        # dismissing the notice silently mean "never ask me again".
        assert dialogs[0]['values'] == ['never', 'null'], dialogs

    def test_the_message_names_both_places_things_are_kept(self, booted):
        """Not a generic privacy note: it has to say which half is on the server's disk and
        which half stays in this browser, because that is the asymmetry the user cannot
        infer from the interface."""
        message = booted['firstVisit']['dialogs'][0]['message']
        for needle in ('server', 'Cookie', 'OpenRouter', 'browser'):
            assert needle in message, f'{needle} missing from the notice: {message}'

    def test_an_acked_browser_is_not_asked_again(self, booted):
        assert booted['ackedBrowser']['dialogs'] == [], booted['ackedBrowser']
        assert booted['ackedBrowser']['storage'] == '1', booted['ackedBrowser']

    def test_only_no_more_reminders_writes_the_ack(self, booted):
        """The notice is dismissed by 知道了 / the backdrop / Esc all the same way: this
        visit ends, next visit is asked again."""
        assert booted['firstVisit']['afterGotIt'] is None, booted['firstVisit']
        assert booted['afterNeverAgain']['stored'] == '1', booted['afterNeverAgain']
        assert booted['afterNeverAgain']['acked'] is True, booted['afterNeverAgain']

    def test_a_second_config_answer_does_not_stack_a_second_notice(self, booted):
        assert booted['secondLanding']['dialogs'] == [
        ], booted['secondLanding']

    def test_the_notice_text_exists_in_both_languages(self):
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        # Count the CATALOGUE entries (a key followed by a colon), not every mention of
        # the string: the call site `I18n.t('privacy.body')` also names the key.
        for key in ('privacy.body', 'privacy.gotIt', 'privacy.never'):
            assert app.count(
                f"'{key}':") == 2, f'{key} must be in the English and the Chinese catalogue'
