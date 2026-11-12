"""The real settings page: schema-rendered fields, the preset card and export/import.

The panel is the only UI that can change a crawl-wide value, so a broken render or a
field posted under the wrong key is a setting the user cannot actually use. The
harness loads the shipped ``panels/settings-panel.js`` with a stubbed transport.
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

HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_settings_panel.mjs'


@pytest.fixture(scope='module')
def panel():
    proc = run_node(str(HARNESS))
    assert proc.returncode == 0, f'settings-panel harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


def test_every_schema_group_and_field_reaches_the_page(panel):
    assert panel['rendered']['paceField'] is True
    assert panel['rendered']['groups'] >= 2


def test_a_changed_field_is_posted_under_its_own_key(panel):
    assert panel['save']['body'] == {'settings': {'crawl_pace_scale': 2.5}}


def test_reset_restores_the_declared_default(panel):
    assert panel['reset']['value'] == 1
    assert panel['reset']['draft'] == 1.0


def test_the_preset_card_uses_the_preset_route_for_both_actions(panel):
    assert panel['preset'] == ['apply', 'restore']


def test_export_carries_the_machine_path_opt_in_and_the_deploy_prefix(panel):
    assert panel['export'] == '/crawler/api/settings/export?include_machine=1'


def test_the_canvas_never_pins_a_worker_count_over_the_server_setting():
    """`max_workers: 4` here made both 最大并发浏览器 settings dead."""
    canvas = (Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js' / 'canvas.js').read_text(
        encoding='utf-8'
    )
    block = canvas.split('toWorkflowJSON', 1)[1].split('};', 1)[0]
    assert 'max_workers' not in block


def test_an_outside_click_dismisses_the_settings_page():
    """The settings page is a form, not a read-only dock: clicking back into the
    canvas must leave it, without a second press on 关闭."""
    floating = (Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js' / 'floating-panels.js').read_text(
        encoding='utf-8'
    )
    start = floating.index("document.getElementById('settings-panel')")
    block = floating[start : start + 900]
    assert "e.target.closest('#settings-panel" in block
    assert 'SettingsPanel.close()' in block
    assert "e.target.closest('.settings-open-full')" in block, 'the opener would close-then-reopen the panel'


def test_the_settings_dock_is_in_the_shared_dock_list_and_has_a_resize_handler():
    js_dir = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js'
    workflow = (js_dir / 'workflow.js').read_text(encoding='utf-8')
    floating = (js_dir / 'floating-panels.js').read_text(encoding='utf-8')
    assert "'settings-panel'" in workflow.split('var DOCKED_PANELS', 1)[1].split('];', 1)[0]
    assert "initDockResize('settings-resize-handle', 'settings-panel')" in floating
