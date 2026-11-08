"""The macOS packaging contract, testable on Windows.

The .app and DMG are built only on GitHub's macOS runners, so this suite pins the pieces that
cannot be checked by running them: the entry point serves loopback and uses the Cocoa backend, the
spec is a windowed ``BUNDLE`` with WebKit (never WebView2/pythonnet), the DMG carries the
architecture, and the workflow uploads to the requested release tag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DESKTOP = REPO / 'desktop'
WORKFLOW = REPO / '.github' / 'workflows' / 'macos-build.yml'

pytestmark = pytest.mark.unit


def test_the_macos_entry_serves_loopback_and_uses_the_system_webkit():
    source = (DESKTOP / 'macos_entry.py').read_text(encoding='utf-8')
    assert "make_server('127.0.0.1'" in source
    assert 'webview.start(' in source and 'storage_path=' in source
    assert 'Library/Application Support' in source
    assert 'CRAWLER_DATA_ROOT' in source
    assert 'MessageBoxW(' not in source and 'windll' not in source


def test_the_macos_bundle_is_windowed_and_collects_cocoa_not_webview2():
    spec = (DESKTOP / 'caixihui_macos.spec').read_text(encoding='utf-8')
    assert 'BUNDLE(' in spec
    assert 'console=False' in spec
    assert 'webview.platforms.cocoa' in spec
    for module in ('objc', 'Foundation', 'AppKit', 'WebKit', 'PyObjCTools.AppHelper'):
        assert repr(module) in spec
    assert "'pythonnet'" not in spec and "'clr'" not in spec, 'the Windows CLR stack must not ship'
    assert 'webview.platforms.winforms' not in spec


def test_the_dmg_builder_names_the_architecture_and_uses_hdiutil():
    source = (DESKTOP / 'build_macos.py').read_text(encoding='utf-8')
    assert 'hdiutil' in source and 'UDZO' in source
    assert 'CaiXiHui-macOS-' in source
    assert 'platform.machine()' in source
    assert "sys.platform != 'darwin'" in source, 'the build must refuse to pretend on Windows'


def test_the_workflow_builds_both_architectures_and_uploads_the_dmg():
    workflow = WORKFLOW.read_text(encoding='utf-8')
    assert 'macos-15-intel' in workflow and 'macos-15' in workflow
    assert 'x86_64' in workflow and 'arm64' in workflow
    assert 'desktop/build_macos.py --clean' in workflow
    assert 'gh release upload "$RELEASE_TAG"' in workflow
    assert 'requirements-macos.txt' in workflow
    assert 'permissions:' in workflow and 'contents: write' in workflow


def test_macos_requirements_are_the_runtime_set_without_windows_or_torch():
    text = (DESKTOP / 'requirements-macos.txt').read_text(encoding='utf-8')
    names = {line.split('==', 1)[0].strip().lower() for line in text.splitlines() if '==' in line}
    for present in ('flask', 'pandas', 'numpy', 'scipy', 'scikit-learn', 'selenium', 'jieba', 'snownlp', 'pywebview'):
        assert present in names, f'{present} is missing from the macOS runtime set'
    for absent in ('torch', 'transformers', 'pyarrow', 'mitmproxy', 'pythonnet', 'onnxruntime', 'pytest'):
        assert absent not in names, f'{absent} must not enter the macOS bundle'
    assert not {byte for byte in text.encode('utf-8') if byte > 127}, 'pip reads this as cp1252 on mac'
