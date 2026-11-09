"""The catalogue updater must keep one platform's digest out of another's asset row.

A Mac app is two architectures and Windows is a third; a single ``--component chrome=win64.zip``
run used to write that Windows digest into every platform entry, which would make the macOS
installer reject the Mac build it just downloaded.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from core import machine

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / 'tools' / 'release_components.py'
pytestmark = pytest.mark.unit


def _tool():
    spec = importlib.util.spec_from_file_location('release_components_contract', TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _catalog(tmp_path: Path) -> Path:
    payload = {
        'schema': 1,
        'components': {
            'chrome': {
                'version': '1.0',
                'platforms': {
                    'win32': {
                        'urls': ['https://example.com/old-win.zip'],
                        'sha256': 'a' * 64,
                        'size': 1,
                    },
                    'darwin-arm64': {
                        'urls': ['https://example.com/old-mac.zip'],
                        'sha256': 'b' * 64,
                        'size': 2,
                    },
                },
            }
        },
    }
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))['components']['chrome']['platforms']


def test_a_windows_zip_updates_only_the_windows_row(tmp_path, monkeypatch):
    tool = _tool()
    catalog = _catalog(tmp_path)
    archive = tmp_path / 'chrome-win64.zip'
    archive.write_bytes(b'windows bytes')
    monkeypatch.setattr(machine, 'platform_asset_key', lambda system=None, machine=None: 'win32')
    out = tmp_path / 'out.json'
    tool.main(
        [
            '--catalog',
            str(catalog),
            '--out',
            str(out),
            '--component',
            f'chrome={archive}',
            '--url',
            'chrome=https://example.com/new-win.zip',
        ]
    )
    rows = _read(out)
    assert rows['win32']['sha256'] == tool.sha256(archive)
    assert rows['win32']['size'] == len(b'windows bytes')
    assert rows['win32']['urls'] == ['https://example.com/new-win.zip']
    assert rows['darwin-arm64']['sha256'] == 'b' * 64
    assert rows['darwin-arm64']['size'] == 2
    assert rows['darwin-arm64']['urls'] == ['https://example.com/old-mac.zip']


def test_an_explicit_platform_updates_the_mac_row(tmp_path, monkeypatch):
    tool = _tool()
    catalog = _catalog(tmp_path)
    archive = tmp_path / 'chrome-mac-arm64.zip'
    archive.write_bytes(b'mac bytes')
    monkeypatch.setattr(machine, 'platform_asset_key', lambda system=None, machine=None: 'win32')
    out = tmp_path / 'out.json'
    tool.main(['--catalog', str(catalog), '--out', str(out), '--component', f'chrome:darwin-arm64={archive}'])
    rows = _read(out)
    assert rows['darwin-arm64']['sha256'] == tool.sha256(archive)
    assert rows['win32']['sha256'] == 'a' * 64


def test_a_platform_typo_is_refused_by_name(tmp_path, monkeypatch):
    tool = _tool()
    catalog = _catalog(tmp_path)
    archive = tmp_path / 'chrome.zip'
    archive.write_bytes(b'x')
    monkeypatch.setattr(machine, 'platform_asset_key', lambda system=None, machine=None: 'win32')
    with pytest.raises(SystemExit, match='no asset for darwin-x64'):
        tool.main(
            [
                '--catalog',
                str(catalog),
                '--out',
                str(tmp_path / 'out.json'),
                '--component',
                f'chrome:darwin-x64={archive}',
            ]
        )
