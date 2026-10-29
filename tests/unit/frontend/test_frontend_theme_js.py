"""Theme behaviour tests — the chrome switch and the chart recolour, under node.

Skipped when node is not on PATH, like every other frontend harness. See
tests/frontend/harness_theme.mjs for what it drives.
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

JS_DIR = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_theme.mjs'


@pytest.fixture(scope='module')
def theme():
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, f'theme harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestThemeSwitch:
    def test_explicit_light_and_dark_resolve_to_themselves(self, theme):
        assert theme['light']['resolved'] == 'light'
        assert theme['dark']['resolved'] == 'dark'

    def test_auto_follows_the_os_scheme(self, theme):
        """The stub reports no dark preference, so auto must resolve to light — and the CHOICE
        ('auto') is what persists, not the resolved value, so the OS can still change it later."""
        assert theme['auto']['resolved'] == 'light', 'no OS dark preference → auto is light'
        assert theme['auto']['stored'] == 'auto'

    def test_the_choice_is_persisted(self, theme):
        assert theme['light']['stored'] == 'light'
        assert theme['dark']['stored'] == 'dark'

    def test_the_active_control_marks_the_choice(self, theme):
        assert theme['light']['active'] == ['light']
        assert theme['dark']['active'] == ['dark']
        assert theme['auto']['active'] == ['auto'], 'auto stays the lit option even though it resolves light'

    def test_native_widgets_follow_the_resolved_theme(self, theme):
        """Scrollbars, form controls and the canvas backdrop are painted by the UA from
        ``color-scheme``; a dark chrome with a light scheme keeps white scrollbars."""
        assert theme['light']['colorScheme'] == 'light'
        assert theme['dark']['colorScheme'] == 'dark'
        assert theme['auto']['colorScheme'] == 'light', 'auto resolved light, so the scheme does too'


class TestThemeFirstPaint:
    """theme-boot.js, the page's first script, applies the SAVED choice before any app code.

    The harness seeds ``theme: dark, bg: void, lang: en`` before loading the page, so these
    assertions read what the first painted frame would show — not what a later repaint fixes.
    """

    def test_the_saved_theme_is_on_the_document_before_app_code_runs(self, theme):
        boot = theme['boot']
        assert boot['choice'] == 'dark'
        assert boot['resolved'] == 'dark'
        assert boot['colorScheme'] == 'dark', 'the UA scheme must not stay light until app.js boots'

    def test_the_saved_background_and_language_are_applied_before_first_paint(self, theme):
        boot = theme['boot']
        assert boot['bg'] is True
        assert boot['grid'] is False, 'the default grid background must be replaced, not kept alongside'
        assert boot['lang'] == 'en'
        assert boot['htmlLang'] == 'en', 'a reader would otherwise keep the declared zh-CN voice'

    def test_the_document_language_follows_a_language_switch(self, theme):
        """setLang() flips ``body.dataset.lang`` and repaints through I18n.apply(); the
        document's own ``lang`` has to move with it or assistive tech stays Chinese."""
        assert theme['lang_attr'] == {'zh': 'zh-CN', 'en': 'en'}


class TestThemeCharts:
    def test_charts_recolour_with_the_theme(self, theme):
        """A dark chrome must not keep light-only charts: the title ink, tooltip ground, axis
        labels and split lines all flip, otherwise chart text is dark-on-dark."""
        light = theme['chart_light']
        dark = theme['chart_dark']
        assert light['title'] == '#111'
        assert dark['title'] == '#e7e5df'
        assert light['axisLabel'] != dark['axisLabel']
        assert light['splitLine'] != dark['splitLine']
        assert light['tooltipBg'] != dark['tooltipBg']

    def test_export_background_matches_the_theme(self, theme):
        """The saved chart PNG carries the theme ground, so a dark-theme export is not a white
        box dropped onto a dark report."""
        assert theme['chart_light']['exportBg'] == '#ffffff'
        assert theme['chart_dark']['exportBg'] == '#1c2027'
