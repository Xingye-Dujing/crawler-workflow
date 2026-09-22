"""Behaviour tests for the real top menu (menu.js).

menu.js held the state claims the bar shows — which toggle is on, what the Run
button says, whether Stop is pressable, which language and background swatch is
marked, what the radius slider reads — and until now no harness loaded the file at
all. Every "the bar said X while the app knew Y" bug lives here, as does the
dismissal rule for the three submenus. See tests/frontend/harness_menu.mjs.

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
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_menu.mjs'
FILES = ('canvas.js', 'workflow.js', 'stats.js', 'app.js', 'menu.js')


@pytest.fixture(scope='module')
def bar():
    proc = run_node(str(HARNESS), *[str(JS_DIR / name) for name in FILES])
    assert proc.returncode == 0, f'menu harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestStateRestatement:
    def test_the_parallel_and_headless_buttons_mirror_run_state(self, bar):
        assert bar['sync']['parallelClass'].endswith('toggle-on')
        assert bar['sync']['headlessClass'].endswith('toggle-on')
        assert bar['sync_off']['parallelClass'].endswith('toggle-off')
        assert bar['sync_off']['headlessClass'].endswith('toggle-off')

    def test_sync_rewrites_a_stale_class_rather_than_appending_to_it(self, bar):
        """The bar sets className outright; anything left over from a previous state
        would keep a switch painted the wrong way."""
        assert 'stale' not in bar['sync']['parallelClass']

    def test_the_run_button_is_never_disabled(self, bar):
        """Greying it out meant a second workflow had to wait for someone to come
        back and press it; the server queues the request now."""
        assert bar['execute_idle']['disabled'] is False
        assert bar['execute_running']['disabled'] is False

    def test_the_run_button_says_what_this_press_will_do(self, bar):
        assert bar['execute_idle']['label'] == 'Execute'
        assert bar['execute_running']['label'] == 'Queue this run'

    def test_stop_is_pressable_only_while_a_run_is_going(self, bar):
        assert bar['execute_idle']['stop'] is True
        assert bar['execute_running']['stop'] is False


class TestActiveMarkers:
    def test_the_active_language_button_is_the_one_the_page_is_showing(self, bar):
        assert bar['language_marker'] == ['en']
        assert bar['language_marker_zh'] == ['zh']

    def test_only_the_current_background_swatch_is_marked(self, bar):
        assert bar['background_marker'] == ['bg-dots']
        assert bar['background_marker_other'] == ['bg-void']


class TestRadiusDisplay:
    def test_the_slider_reads_the_token_the_stylesheet_uses(self, bar):
        assert bar['radius_shown'] == {'slider': 7, 'label': '7px'}

    def test_an_unset_token_shows_the_documented_default(self, bar):
        assert bar['radius_unset']['label'] == '2px'

    def test_setting_the_radius_writes_the_token_the_label_and_the_draft(self, bar):
        applied = bar['radius_applied']
        assert applied['token'] == '6px'
        assert applied['label'] == '6px'
        assert applied['draft'] == 6, 'a corner that resets on reload is a setting that was never saved'

    @pytest.mark.parametrize(
        'field, expected',
        [
            ('radius_clamped_high', '16px'),
            ('radius_clamped_low', '0px'),
            ('radius_unparseable_is_zero', '0px'),
            ('radius_blank_is_zero', '0px'),
        ],
    )
    def test_the_slider_cannot_push_the_token_out_of_range(self, bar, field, expected):
        """Every corner in the stylesheet derives from this one value, so an
        unbounded write distorts the whole page."""
        assert bar[field] == expected

    def test_a_corrupt_settings_draft_does_not_stop_the_corner_changing(self, bar):
        assert bar['radius_with_corrupt_draft']['threw'] is False
        assert bar['radius_with_corrupt_draft']['token'] == '5px'


class TestSubmenus:
    def test_opening_a_submenu_positions_it_at_its_own_button(self, bar):
        opened = bar['style_open']
        assert opened['style'] is True
        assert opened['styleBtn'] is True
        assert opened['bodyFlag'] is True, 'the outside-click guard needs to know one is open'
        assert opened['left'].endswith('px') and opened['top'].endswith('px')

    def test_pressing_the_same_button_closes_it_again(self, bar):
        assert bar['style_toggled_closed'] == {
            'style': False,
            'ai': False,
            'settings': False,
            'styleBtn': False,
            'aiBtn': False,
            'settingsBtn': False,
            'bodyFlag': False,
        }

    def test_only_one_submenu_is_open_at_a_time(self, bar):
        assert bar['ai_closes_style'] == {
            'style': False,
            'ai': True,
            'settings': False,
            'styleBtn': False,
            'aiBtn': True,
            'settingsBtn': False,
            'bodyFlag': False,
        }
        assert bar['settings_closes_ai']['ai'] is False
        assert bar['settings_closes_ai']['settings'] is True

    def test_a_click_inside_the_open_menu_keeps_it_open(self, bar):
        assert bar['style_survives_inside_click'] is True

    def test_a_click_on_its_own_button_keeps_it_open(self, bar):
        """That press is the toggle, and the document handler runs after it — treating
        it as "outside" would close the menu the user just opened."""
        assert bar['style_survives_its_own_button'] is True
        assert bar['ai_survives_its_own_button'] is True

    @pytest.mark.parametrize(
        'field',
        ['style_closed_by_outside_click', 'ai_closed_by_outside_click', 'settings_closed_by_outside_click'],
    )
    def test_a_click_elsewhere_closes_it(self, bar, field):
        assert bar[field] is True

    def test_escape_closes_all_three(self, bar):
        assert bar['escape_closed_everything'] == {
            'style': False,
            'ai': False,
            'settings': False,
            'styleBtn': False,
            'aiBtn': False,
            'settingsBtn': False,
            'bodyFlag': False,
        }

    def test_resizing_the_window_dismisses_them(self, bar):
        """An absolutely-positioned submenu keeps the viewport coordinates it was
        opened at, which a resize makes wrong."""
        closed = bar['resize_closed']
        assert closed['style'] is False and closed['ai'] is False

    def test_an_unrelated_key_stores_nothing_open(self, bar):
        assert bar['other_key_keeps_menu'] is True

    def test_a_toggle_called_without_an_event_does_not_throw(self, bar):
        """Keyboard activation reaches these with no event object at all."""
        assert bar['no_event_is_tolerated'] is True


class TestStartUp:
    def test_init_syncs_the_bar_and_installs_the_dismissal_listeners_once(self, bar):
        started = bar['init']
        assert started['synced'] is True
        assert started['listeners'] == {'click': 1, 'keydown': 1, 'resize': 1}

    def test_init_reads_the_saved_settings_and_the_local_model_default(self, bar):
        assert sorted(bar['init']['asked']) == ['/api/config', '/api/settings']
        assert bar['init']['stillLatched'] is True, 'the model list is pulled once, not on every open'

    def test_a_second_init_would_stack_the_listeners(self, bar):
        """Pinned rather than fixed: TopMenu.init() has exactly one call site
        (DOMContentLoaded), so this is a documented property of the function — if a
        second entry point is ever added, this assertion is the reminder to guard it."""
        assert bar['init']['secondInitClickListeners'] == 3

    def test_refresh_is_the_hook_the_state_objects_call(self, bar):
        assert bar['refresh_routes_to_sync'] is True

    def test_close_dismisses_the_style_submenu(self, bar):
        assert bar['close_dismisses_style'] is True
