"""Behaviour tests for the real application state layer (app.js).

These objects decide what the server is told and what the page looks like when it
loads. Until now `LLMSettings.payload()` — the function that builds the LLM part of
every run request — was *stubbed* in every harness that needed to start a run, so
the code that picks which provider's model travels, and whether the API key travels
at all, had never been executed. See tests/frontend/harness_app_state.mjs for the
list of rules this pins.

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

JS_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_app_state.mjs'


@pytest.fixture(scope='module')
def st():
    proc = run_node(
        str(HARNESS),
        str(JS_DIR / 'canvas.js'),
        str(JS_DIR / 'workflow.js'),
        str(JS_DIR / 'app.js'),
    )
    assert proc.returncode == 0, f'app-state harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestLlmPayload:
    """`payload()` is the request body; a wrong field here is a run that pays for
    the wrong model, or a key sent somewhere it should not go."""

    def test_a_first_run_sends_the_local_defaults_and_no_key(self, st):
        assert st['payload_defaults'] == {
            'provider': 'ollama',
            'model': '',
            'api_key': '',
            'batch_size': 10,
            'max_chars': 600,
            'workers': 3,
        }

    def test_openrouter_sends_its_own_model_and_its_key(self, st):
        sent = st['payload_openrouter']
        assert sent['provider'] == 'openrouter'
        assert sent['model'] == 'catalog:free'
        assert sent['api_key'] == 'sk-secret'

    def test_an_ollama_run_never_carries_the_openrouter_key(self, st):
        """The key belongs to a different transport; sending it along with a local
        run puts a paid credential on the wire for nothing."""
        sent = st['payload_ollama']
        assert sent['model'] == 'local-tag'
        assert sent['api_key'] == ''

    def test_the_active_providers_model_is_the_only_one_that_travels(self, st):
        """Both blocks are stored, so a run that read the wrong one would answer
        with a plausible model id the daemon has never heard of."""
        assert st['payload_ollama']['model'] == 'local-tag'
        assert st['payload_openrouter']['model'] == 'catalog:free'

    def test_an_unknown_provider_normalises_to_the_local_one(self, st):
        """The backend treats every non-OpenRouter value as Ollama; a panel that
        kept 'openai' would desync the two."""
        assert st['payload_unknown_provider']['provider'] == 'ollama'
        assert st['payload_unknown_provider']['api_key'] == ''

    def test_a_pre_split_draft_is_migrated_into_the_openrouter_block(self, st):
        """The flat model/api_key pair only ever appeared while OpenRouter was
        selected, so that is the block it belongs to."""
        assert st['migrated_legacy_shape']['loaded']['openrouter']['model'] == 'legacy:free'
        assert st['migrated_legacy_shape']['payload']['api_key'] == 'sk-legacy'

    def test_saving_drops_the_flat_keys(self, st):
        """Leaving them behind let a cleared catalog id resurface after a reload."""
        assert st['save_drops_flat_keys']['hasFlatModel'] is False
        assert st['save_drops_flat_keys']['hasFlatKey'] is False

    def test_a_corrupt_draft_still_answers_with_usable_settings(self, st):
        assert st['corrupt_storage']['threw'] is False
        assert st['corrupt_storage']['payload']['provider'] == 'ollama'

    def test_patching_one_provider_leaves_the_other_block_intact(self, st):
        after = st['save_provider_patch']['after']
        assert after['ollama']['model'] == 'keep-me'
        assert after['openrouter']['model'] == 'new:free'
        assert st['save_provider_patch']['payload']['model'] == 'new:free'


class TestLlmPanel:
    def test_saved_values_are_mirrored_back_into_their_own_inputs(self, st):
        panel = st['apply_to_panel']
        assert panel['ollamaModel'] == 'local-tag'
        assert panel['routerModel'] == 'cat:free'
        assert panel['key'] == 'sk'
        assert (panel['batch'], panel['maxChars']) == (7, 900)

    def test_choosing_ollama_hides_the_openrouter_rows(self, st):
        assert st['provider_rows'] == {'ollamaShown': '', 'routerHidden': 'none'}

    def test_switching_to_openrouter_swaps_which_rows_show(self, st):
        assert st['provider_rows_after_switch'] == {'ollamaShown': 'none', 'routerHidden': ''}

    def test_the_model_placeholder_is_the_servers_default(self, st):
        """A hardcoded copy silently drifts when OLLAMA_MODEL changes."""
        assert st['llm_async']['placeholder'] == 'qwen-pulled:7b'

    def test_the_placeholder_is_pulled_once_not_on_every_open(self, st):
        assert st['llm_async']['pulledOnce'] is True
        assert st['llm_async']['requested'] == ['/api/config']

    def test_the_ollama_address_shown_is_the_one_the_server_has(self, st):
        """'connection refused' against localhost is unreadable when the configured
        address is something else."""
        assert st['llm_async']['withValue'] == 'http://10.0.0.9:11434'

    def test_a_missing_address_falls_back_to_the_documented_default(self, st):
        assert st['llm_async']['fallsBack'] == 'http://localhost:11434'


class TestRunState:
    def test_a_switch_is_stored_written_and_the_menu_refreshed(self, st):
        assert st['run_state']['afterSet'] == {'parallel': False, 'headless': True}
        assert st['run_state']['persisted']['parallel'] is False
        assert st['run_state']['refreshed'] == 1

    def test_toggling_flips_and_persists(self, st):
        assert st['run_state']['toggled'] == {'headless': False, 'refreshed': 2}

    def test_running_state_republishes_without_writing_a_draft(self, st):
        """`running` is a fact about the server, not a user preference; persisting
        it would make a reload claim a run is in progress."""
        assert st['run_state']['running'] == {'running': True, 'menuRefreshed': 3}

    def test_a_non_boolean_value_is_coerced_not_stored_verbatim(self, st):
        assert st['run_state']['coerces_to_boolean'] is True

    def test_running_off_accepts_a_falsy_value(self, st):
        assert st['run_state']['running_off'] is False

    def test_the_switch_works_before_the_menu_object_exists(self, st):
        """The early calls happen during start-up; a guard-less TopMenu.refresh()
        would break the very first click."""
        assert st['run_state']['works_without_menu'] is True


class TestSettingsDraft:
    def test_the_draft_records_what_the_page_actually_is(self, st):
        saved = st['settings_saved']
        assert saved['parallel'] is False
        assert saved['headless'] is False
        assert saved['menuPinned'] is True
        assert saved['zoom'] == 2.5
        assert saved['bg'] == 'bg-grid'

    def test_applying_a_draft_restores_every_setting_it_covers(self, st):
        applied = st['settings_applied']
        assert applied['languageTag'] == 'zh'
        assert applied['background'] == ['bg-grid']
        assert (applied['parallel'], applied['headless']) == (False, False)
        assert applied['menuPinned'] is False
        assert applied['pinPressed'] == 'false', 'the button must announce its state to a screen reader'
        assert applied['radiusToken'] == '9px'
        assert (applied['slider'], applied['label']) == (9, '9px')

    def test_applying_translates_the_page_through_the_real_dictionary(self, st):
        """`[data-i18n]` stamping is what a language switch visibly does; asserting
        on the shipped dict means this cannot drift from it."""
        assert st['settings_applied']['stampedLabel'] == '中文'
        assert st['settings_applied']['stampedTitle']
        assert st['settings_applied']['englishLabel'] == 'EN'

    def test_a_first_run_gets_the_documented_defaults(self, st):
        assert st['settings_first_run']['load']['parallel'] is True
        assert st['settings_first_run']['load']['radius'] == 2
        assert st['settings_first_run']['parallelDefault'] is True

    def test_a_corrupt_draft_does_not_stop_the_page_from_loading(self, st):
        """The bug this pins: apply() runs from DOMContentLoaded, so a hand-edited
        draft used to throw there and leave a blank canvas behind."""
        assert st['settings_corrupt_draft']['threw'] is False

    def test_the_menu_is_pinned_until_the_user_says_otherwise(self, st):
        assert st['pinned_default'] is True


class TestServerSettingsPanel:
    def test_pulling_the_server_settings_fills_every_field(self, st):
        pulled = st['app_settings']['pulled']
        assert pulled['driver'] == 'D:\\chromedriver.exe'
        assert pulled['pageload'] == 40
        assert pulled['values']['cookie_confirm_before_run'] is True

    def test_a_checkbox_is_stamped_on_checked_not_on_value(self, st):
        """Writing `.value` on a checkbox changes nothing, so the panel would show a
        box that is not what the server has."""
        assert st['app_settings']['pulled']['confirmChecked'] is True

    def test_a_key_the_server_does_not_have_leaves_the_field_empty(self, st):
        assert st['app_settings']['pulled']['missingKeyLeftAlone'] == ''

    def test_reopening_the_panel_does_not_refetch_and_lose_unsaved_edits(self, st):
        assert st['app_settings']['second_pull_requested'] == 0

    def test_an_explicit_refresh_does_refetch(self, st):
        assert st['app_settings']['forced_requested'] == 1

    def test_saving_with_nothing_changed_says_so_and_sends_nothing(self, st):
        no_change = st['app_settings']['no_change']
        assert no_change['requested'] == 0
        assert no_change['toasts'], 'silence would read as "saved"'

    def test_the_save_button_is_disabled_only_while_writing(self, st):
        assert st['app_settings']['button_disabled_while_writing'] is True
        assert st['app_settings']['save']['button_released'] is True

    def test_only_the_staged_fields_are_sent(self, st):
        body = st['app_settings']['save']['body']
        assert list(body['settings']) == ['driver_path', 'ollama_host']

    def test_a_saved_draft_is_cleared_so_the_next_save_is_not_a_replay(self, st):
        assert st['app_settings']['save']['draft_cleared'] == 0

    def test_a_refused_save_is_reported_and_keeps_the_old_values(self, st):
        rejected = st['app_settings']['rejected']
        assert any('disk full' in toast for toast in rejected['toasts']), rejected
        assert rejected['values_unchanged'] == 'D:\\chromedriver.exe'

    def test_a_save_that_warned_shows_the_warning(self, st):
        assert any('驱动版本偏旧' in toast for toast in st['app_settings']['warned']), st['app_settings']['warned']


class TestFloatingConversion:
    def test_a_class_anchored_panel_is_pinned_to_its_computed_box(self, st):
        """`el.style` cannot see a class-driven `right`, so the conversion has to
        read computed style or the panel jumps when it is detached."""
        converted = st['convert']
        assert converted['rightReleased'] is True
        assert converted['pinnedLeft'] == '0px'
        assert converted['topPinned'] == '0px'

    def test_an_unanchored_element_is_left_alone(self, st):
        assert st['convert']['untouched_when_not_anchored'] is True
