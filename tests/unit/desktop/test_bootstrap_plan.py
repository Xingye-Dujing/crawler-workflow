"""The installer's pure decisions: default folder, sizes and what a preset selects.

No Tkinter, no downloads, no network: the novice default being the domestic/no-VPN route is a
property of the catalogue, and the preset's meaning is pinned here so a UI edit cannot silently
start installing every optional multi-gigabyte component.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PLAN = Path(__file__).resolve().parents[3] / 'desktop' / 'bootstrap' / 'plan.py'


@pytest.fixture(scope='module')
def plan():
    spec = importlib.util.spec_from_file_location('installer_plan', PLAN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_default_folder_is_per_user_and_needs_no_admin(plan, tmp_path):
    root = plan.default_root({'LOCALAPPDATA': str(tmp_path)})
    assert root == tmp_path / 'Programs' / 'CaiXiHui'


def test_sizes_are_for_humans(plan):
    assert plan.human_size(0) == '0 B'
    assert plan.human_size(1024) == '1 KB'
    assert plan.human_size(5 * 1024**3) == '5.0 GB'


def test_presets_do_not_accidentally_select_optional_components(plan):
    chosen = {'app': True, 'chrome': True, 'ollama': False}
    assert plan.selected_ids('one', chosen, ['app', 'chrome', 'ollama']) == ['app', 'chrome']
    assert plan.selected_ids('app', chosen, ['app', 'chrome', 'ollama']) == ['app']
    assert plan.selected_ids('all', chosen, ['app', 'chrome', 'ollama']) == ['app', 'chrome', 'ollama']
    assert plan.total_size({'app': 10, 'chrome': 5}, ['app', 'chrome']) == 15
