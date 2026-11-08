"""The installer's local server state, exercised without opening the native window.

The window is a WebView2 view over this state, so the contract worth pinning is the model behind
it: a preset is a set of ticks, an unticked component is not installed, and a requirement (CatBus
→ Node) is added to the effective download. Nothing here binds a socket; the page itself is
covered by the static checks in ``test_bootstrap_plan.py``.
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
    effective = state.effective()
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
    assert 'app' not in state.effective()


def test_the_folder_picker_buffer_is_declared_as_a_pointer(installer):
    """A ``create_unicode_buffer`` is a c_wchar_Array, never a c_wchar_p.

    Declaring ``pszDisplayName``/``SHGetPathFromIDListW`` as LPWSTR made ctypes raise before (or
    right after) the dialog, which surfaced in the page as ERR_EMPTY_RESPONSE on /api/browse.
    """
    source = INSTALLER.read_text(encoding='utf-8')
    assert "('pszDisplayName', ctypes.c_void_p)" in source
    assert "('pszDisplayName', wintypes.LPWSTR)" not in source
    assert 'SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]' in source
    assert 'ctypes.cast(path, ctypes.c_void_p)' in source


def test_the_window_cannot_be_closed_while_a_download_runs(installer):
    """Closing the window ends the process; a half-downloaded component is not resumable, so the
    X is refused and the page's 取消 is the documented way out."""
    assert installer.may_close('running') is False
    assert installer.may_close('idle') is True
    assert installer.may_close('done') is True


def test_the_page_origin_is_stable_so_local_storage_survives(installer):
    """A random port would be a new origin on every launch, and the page's language/theme
    choice (localStorage) would reset each time. The token still guards the server."""
    assert installer.INSTALLER_PORT == 3968


@pytest.mark.enable_socket
def test_a_busy_fixed_port_falls_back_to_an_ephemeral_one(installer):
    import socket

    blocker = socket.socket()
    try:
        try:
            blocker.bind(('127.0.0.1', installer.INSTALLER_PORT))
        except OSError:
            pytest.skip('the installer port is already in use on this machine')
        blocker.listen(1)
        server = installer._make_server(_state(installer), 'token')
        try:
            assert server.server_address[1] != installer.INSTALLER_PORT
        finally:
            server.server_close()
    finally:
        blocker.close()


def test_the_running_process_says_whether_it_was_elevated(installer):
    """The page must be able to tell “ask once” from “already asked and still refused”."""
    assert _state(installer).elevated is False
    elevated = installer.InstallerState(installer.Catalog(installer.load_catalog()), 'C:/app', 'D:/data', True)
    assert elevated.elevated is True
