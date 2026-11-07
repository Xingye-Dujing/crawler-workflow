"""The installer's local server state, exercised without opening a browser.

The window is the user's browser, so the contract worth pinning is the model behind it: a preset
is a set of ticks, an unticked component is not installed, and a requirement (CatBus → Node) is
added to the effective download. Nothing here binds a socket; the page itself is covered by the
static checks in ``test_bootstrap_plan.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / 'desktop' / 'bootstrap' / 'installer.py'


@pytest.fixture(scope='module')
def installer():
    """The installer module, without its synthetic ``services`` package leaking to other tests."""
    before_path = list(sys.path)
    before_modules = set(sys.modules)
    spec = importlib.util.spec_from_file_location('installer_server', INSTALLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    for name in list(sys.modules):
        if name in before_modules or not (name == 'services' or name.startswith('services.')):
            continue
        loaded = sys.modules[name]
        if getattr(loaded, '__file__', None) is None:
            del sys.modules[name]
    sys.path[:] = before_path
    return module


def _state(installer):
    return installer.InstallerState(installer.Catalog(installer.load_catalog()), 'C:/app', 'D:/data', False)


def test_the_default_preset_ticks_exactly_the_catalogue_defaults(installer):
    state = _state(installer)
    body = state.snapshot()
    expected = {item.id for item in state.catalog.components.values() if item.default and item.asset()}
    assert {row['id'] for row in body['components'] if row['checked']} == expected
    assert body['total'] > 0


def test_switching_to_application_only_untickes_everything_else(installer):
    state = _state(installer)
    assert state.set_preset('app') is True
    body = state.snapshot()
    assert [row['id'] for row in body['components'] if row['checked']] == ['app']


def test_an_unknown_preset_is_refused_rather_than_guessed(installer):
    state = _state(installer)
    assert state.set_preset('everything') is False
    assert state.preset == 'one'


def test_the_effective_download_adds_a_requirement_the_user_did_not_tick(installer):
    state = _state(installer)
    state.set_selection(['catbus'])
    effective = state._effective()
    assert 'node' in effective, 'CatBus without Node is a download that can only fail'
    assert effective.index('node') < effective.index('catbus')
    body = state.snapshot()
    assert body['total'] == sum(
        state.catalog.get(item).asset().size for item in effective if state.catalog.get(item).asset()
    )


def test_a_detection_only_component_is_listed_but_never_selected(installer):
    state = _state(installer)
    state.set_selection(['xelatex'])
    body = state.snapshot()
    row = next(item for item in body['components'] if item['id'] == 'xelatex')
    assert row['downloadable'] is False
    assert row['checked'] is False
    assert 'app' not in state._effective()


def test_the_running_process_says_whether_it_was_elevated(installer):
    """The page must be able to tell “ask once” from “already asked and still refused”."""
    assert _state(installer).elevated is False
    elevated = installer.InstallerState(installer.Catalog(installer.load_catalog()), 'C:/app', 'D:/data', True)
    assert elevated.elevated is True
