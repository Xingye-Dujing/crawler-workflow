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


def test_the_page_loads_the_panel_and_its_words():
    html = HTML.read_text(encoding='utf-8')
    assert 'js/components.js' in html
    assert 'js/i18n/components.js' in html
    assert 'components-panel' in html
    catalogue = CATALOGUE.read_text(encoding='utf-8')
    for key in ('env.title', 'env.stateMissing', 'env.installFailed'):
        assert f"'{key}'" in catalogue
