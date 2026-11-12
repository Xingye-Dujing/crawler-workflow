"""The environment panel is a view of the server's facts, not a second opinion.

No node harness here: the panel is a thin renderer over ``/api/environment`` and
``/api/components``. What is worth pinning statically is that it asks those two routes, polls the
job instead of holding a request open, and never inserts server data as HTML.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
JS = REPO / 'backend' / 'static' / 'js' / 'components.js'
HTML = REPO / 'backend' / 'static' / 'index.html'
CATALOGUE = REPO / 'backend' / 'static' / 'js' / 'i18n' / 'components.js'


def test_the_panel_asks_the_server_for_both_halves():
    source = JS.read_text(encoding='utf-8')
    assert "fetch('/api/environment')" in source
    assert "fetch('/api/components')" in source
    assert '/api/components/jobs/' in source
    assert 'setTimeout(tick' in source, 'a long download must be polled, not awaited inside one fetch'


def test_server_data_is_text_never_markup():
    source = JS.read_text(encoding='utf-8')
    assert 'innerHTML' not in source, 'capability reasons come from the server and must stay text'
    assert 'textContent' in source


def test_the_panel_can_uninstall_but_never_the_application_itself():
    source = JS.read_text(encoding='utf-8')
    assert "'/api/components/remove'" in source
    assert "component.id !== 'app'" in source, 'the app is removed by the uninstaller, not this panel'


def test_the_restart_hint_is_painted_after_the_repaint_that_clears_the_body():
    source = JS.read_text(encoding='utf-8')
    refresh = source.index('await this.refresh();')
    hint = source.index('if (finished) this._restartHint();')
    assert refresh < hint, 'a hint prepended before _render is wiped in the same tick and never shows'


def test_a_double_click_cannot_start_two_install_loops():
    source = JS.read_text(encoding='utf-8')
    assert 'if (this._busy) return;' in source
    assert source.count('this._busy = false;') >= 3, 'every exit path has to release the guard'


def test_the_panel_offers_both_component_sources_only_where_an_installer_exists():
    """Both copies are legitimate on an installed desktop; a source checkout has no
    installer tree, so the server's `installer_available` hides the picker rather than
    letting the user choose a copy that cannot exist."""
    source = JS.read_text(encoding='utf-8')
    assert "fetch('/api/settings'" in source, 'the saved preference is a setting, not local state'
    assert 'env.component_source_preference' in source, 'the buttons show what the next start uses'
    assert 'env.installer_available !== false' in source, 'the picker reads the server verdict'
    assert "['bundled', 'env.sourceBundled']" in source
    assert "'system'" in source and "'env.sourceSystem'" in source
    assert 'this._sourceKeys[row.source]' in source, 'each row names the copy it is using'
    assert '_showComponent(component)' in source, 'installer rows are filtered by the same verdict'
    catalogue = CATALOGUE.read_text(encoding='utf-8')
    for key in ('env.sourceTitle', 'env.sourceBundled', 'env.sourceSystem', 'env.sourceHint'):
        assert f"'{key}'" in catalogue


def test_manual_components_are_detected_not_called_uninstalled():
    """Ollama/BERT/MiKTeX are machine-level tools, never installer payloads. Their row
    now reads the same capability answer as the matrix above instead of “未安装”."""
    source = JS.read_text(encoding='utf-8')
    assert "component.kind === 'manual'" in source
    assert 'this._capabilityFor(env, component.id)' in source
    assert "'env.detectedHere'" in source and "'env.notDetected'" in source
    catalogue = CATALOGUE.read_text(encoding='utf-8')
    for key in ('env.detectedHere', 'env.detectedDegraded', 'env.notDetected'):
        assert f"'{key}'" in catalogue


def test_the_page_loads_the_panel_and_its_words():
    html = HTML.read_text(encoding='utf-8')
    assert 'js/components.js' in html
    assert 'js/i18n/components.js' in html
    assert 'components-panel' in html
    catalogue = CATALOGUE.read_text(encoding='utf-8')
    for key in ('env.title', 'env.stateMissing', 'env.installFailed'):
        assert f"'{key}'" in catalogue
