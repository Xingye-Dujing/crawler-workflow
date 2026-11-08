"""The installer's pure decisions: default folder, sizes and what a preset selects.

No Tkinter, no downloads, no network: the novice default being the domestic/no-VPN route is a
property of the catalogue, and the preset's meaning is pinned here so a UI edit cannot silently
start installing every optional multi-gigabyte component.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT / 'desktop' / 'bootstrap' / 'plan.py'
THEME = ROOT / 'desktop' / 'bootstrap' / 'ui_theme.py'


@pytest.fixture(scope='module')
def plan():
    spec = importlib.util.spec_from_file_location('installer_plan', PLAN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def theme():
    spec = importlib.util.spec_from_file_location('installer_theme', THEME)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _css_tokens(css: str, selector: str) -> dict[str, str]:
    start = css.index(selector)
    body = css[start : css.index('}', start)]
    tokens = {}
    for line in body.splitlines():
        line = line.strip()
        if line.startswith('--') and ':' in line:
            name, value = line.rstrip(';').split(':', 1)
            tokens[name.strip()] = value.strip()
    return tokens


def _hex(value: str) -> str:
    value = value.strip().lower()
    if len(value) == 4 and value.startswith('#'):
        return '#' + ''.join(char * 2 for char in value[1:])
    return value


def test_the_default_folder_is_per_user_and_needs_no_admin(plan, tmp_path):
    root = plan.default_root({'LOCALAPPDATA': str(tmp_path)})
    assert root == tmp_path / 'Programs' / 'CaiXiHui'


def test_sizes_are_for_humans(plan):
    assert plan.human_size(0) == '0 B'
    assert plan.human_size(1024) == '1 KB'
    assert plan.human_size(5 * 1024**3) == '5.0 GB'


def test_the_data_folder_default_is_the_launchers_own_default(plan, tmp_path):
    root = plan.default_data_root({'APPDATA': str(tmp_path / 'Roaming')})
    assert root == tmp_path / 'Roaming' / 'CaiXiHui'


def test_presets_are_checkbox_states_not_a_hidden_answer(plan):
    """The boxes must show what will be installed: 一键安装 ticked the defaults, 仅主程序 only the app."""
    downloadable = ['app', 'chrome', 'node', 'xelatex']
    one = plan.preset_choices('one', ['app', 'chrome', 'node'], downloadable)
    assert one == {'app': True, 'chrome': True, 'node': True, 'xelatex': False}
    assert plan.preset_choices('app', ['app', 'chrome', 'node'], downloadable) == {
        'app': True,
        'chrome': False,
        'node': False,
        'xelatex': False,
    }


def test_an_unticked_component_is_not_installed_whatever_the_preset(plan):
    """The preset came first; the user's ticks are the answer after they touch a box."""
    chosen = {'app': True, 'chrome': False, 'node': True}
    assert plan.chosen_ids(chosen, ['app', 'chrome', 'node']) == ['app', 'node']
    assert plan.total_size({'app': 10, 'chrome': 5}, ['app', 'chrome']) == 15


def test_a_requirement_is_added_ahead_of_the_component_that_needs_it(plan):
    requires = {'catbus': ['node'], 'chromedriver': ['chrome'], 'node': [], 'chrome': []}
    downloadable = ['app', 'chrome', 'chromedriver', 'node', 'catbus']
    assert plan.with_requirements(['catbus'], requires, downloadable) == ['node', 'catbus']
    assert plan.with_requirements(['catbus', 'chromedriver'], requires, downloadable) == [
        'node',
        'catbus',
        'chrome',
        'chromedriver',
    ]
    assert plan.with_requirements(['app'], requires, downloadable) == ['app']


def test_a_requirement_the_installer_cannot_download_is_not_invented(plan):
    """MiKTeX is detection-only: adding it would create a job that can only fail."""
    assert plan.with_requirements(['app'], {'app': ['xelatex']}, ['app']) == ['app']


def test_the_installer_wears_the_applications_palette(theme):
    """The installer is the first window of this product; it must not look like another app.

    The tokens come from ``base.css``, so comparing against the stylesheet (rather than against
    a copied hex list here) is what makes a theme change update both surfaces. The installer is
    deliberately LIGHT: the page defines no dark scheme at all.
    """
    css = (ROOT / 'backend' / 'static' / 'css' / 'base.css').read_text(encoding='utf-8')
    light = _css_tokens(css, ':root {')
    assert _hex(theme.PALETTE['bg']) == _hex(light['--bg'])
    assert _hex(theme.PALETTE['text']) == _hex(light['--text'])
    assert _hex(theme.PALETTE['accent']) == _hex(light['--accent'])
    assert 'prefers-color-scheme' not in theme.stylesheet()
    assert '--accent: #9a7740' in theme.stylesheet()


def test_the_primary_button_is_ink_not_the_node_accent(theme):
    """``--accent`` is the node-type brown; the front end's primary action is an ink underline
    (``.studio-btn.primary``), and a brown fill read as another product."""
    css = theme.stylesheet()
    block = css.split('button.primary {', 1)[1].split('}', 1)[0]
    assert 'var(--accent)' not in block
    assert 'var(--text)' in block
    assert 'inset 0 -2px 0 var(--text)' in block


def test_the_page_ships_both_themes_and_an_svg_toggle(theme):
    page = (ROOT / 'desktop' / 'bootstrap' / 'installer_page.html').read_text(encoding='utf-8')
    assert '--accent: #9a7740' in theme.stylesheet()
    assert 'data-theme="dark"' in theme.stylesheet(), 'the dark tokens are an override block'
    assert 'id="theme"' in page
    assert 'icon-moon' in page and 'icon-sun' in page, 'both states are inline SVG, not a glyph'
    assert '☾' not in page and '☀' not in page, 'no Unicode character stands in for an icon'


def test_the_installer_keeps_one_one_click_preset_and_no_duplicate(theme):
    """“全部组件” ticked exactly the same boxes as “一键安装”; a second button that changes
    nothing is a choice the user cannot tell apart."""
    for language in theme.TEXT.values():
        assert 'preset_all' not in language
        assert 'preset_one' in language and 'preset_app' in language
    page = (ROOT / 'desktop' / 'bootstrap' / 'installer_page.js').read_text(encoding='utf-8')
    assert 'api/preset' in page, 'the preset must come from the server state'
    assert 'renderComponents' in page


def test_the_install_log_shows_every_line_not_just_three(theme):
    """Node and CatBus are the last components, so a ``slice(-4)`` plus a 54 px clip cut them off.

    The run pane now owns the leftover height and scrolls internally only when the lines exceed
    one screen; every server line is rendered.
    """
    page = (ROOT / 'desktop' / 'bootstrap' / 'installer_page.html').read_text(encoding='utf-8')
    js = (ROOT / 'desktop' / 'bootstrap' / 'installer_page.js').read_text(encoding='utf-8')
    css = theme.stylesheet()
    assert 'section class="run"' in page
    assert 'slice(-4)' not in js
    assert 'log.scrollTop = log.scrollHeight' in js
    assert 'section.run .log' in css and 'overflow-y: auto' in css


def test_the_installer_ships_no_gui_toolkit():
    """The window is the OS WebView2 host: bundling Qt or Tcl/Tk would multiply the download for
    a page. ``console=False`` is part of the same promise — a console is not a window."""
    spec = (ROOT / 'desktop' / 'bootstrap' / 'installer.spec').read_text(encoding='utf-8')
    assert 'PySide6' not in spec and 'PyQt' not in spec
    assert "'tkinter'" in spec, 'Tcl/Tk must be excluded from the onefile'
    assert 'console=False' in spec
    assert "'webview'" in spec and "'clr'" in spec, 'the WebView2 host must be bundled'
    page = (ROOT / 'desktop' / 'bootstrap' / 'installer_page.js').read_text(encoding='utf-8')
    assert 'innerHTML' not in page, 'server data stays text; the installer page never injects markup'
