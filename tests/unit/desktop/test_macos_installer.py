"""The macOS online installer's contract, tested on Windows too.

The .app and DMG can only be built on macOS, so these cases pin what can be checked anywhere: the
generated catalogue describes the exact DMG being published, the shared installer is reused rather
than forked, the app is installed by mounting (not unzipping) its bundle, and the platform payload
tables point at the binaries the probe will look for.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from core.machine import component_payload_path, platform_asset_key

from services.components.archive import ArchiveError
from services.components.catalog import Catalog, load_catalog
from services.components.install import InstallError, install_component
from services.components.macos import extract_command

REPO = Path(__file__).resolve().parents[3]
DESKTOP = REPO / 'desktop'
BOOTSTRAP = DESKTOP / 'bootstrap'
CATALOG_PATH = REPO / 'backend' / 'services' / 'components' / 'default_catalog.json'

pytestmark = pytest.mark.unit


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def installer_app():
    return _load('installer_macos_contract', BOOTSTRAP / 'installer_macos.py')


@pytest.fixture(scope='module')
def builder():
    return _load('build_macos_installer_contract', DESKTOP / 'build_macos_installer.py')


def test_the_platform_key_is_per_mac_architecture_but_keeps_windows_unchanged():
    assert platform_asset_key('darwin', 'arm64') == 'darwin-arm64'
    assert platform_asset_key('darwin', 'aarch64') == 'darwin-arm64'
    assert platform_asset_key('darwin', 'x86_64') == 'darwin-x64'
    assert platform_asset_key('win32', 'AMD64') == 'win32'
    assert platform_asset_key('linux', 'x86_64') == 'linux'


def test_a_component_payload_is_found_where_its_platform_archive_puts_it():
    assert component_payload_path('chrome', 'darwin') == (
        'Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
    )
    assert component_payload_path('chromedriver', 'darwin') == 'chromedriver'
    assert component_payload_path('node', 'darwin') == 'bin/node'
    assert component_payload_path('node', 'win32') == 'node.exe'
    assert component_payload_path('catbus', 'darwin') == 'dist/integrations/crawler-workflow/cli.js'
    assert component_payload_path('missing', 'darwin') == ''


def test_the_native_extractor_uses_ditto_and_tar_not_python_zipfile():
    assert extract_command('chrome.zip', 'out', 'zip') == ['/usr/bin/ditto', '-x', '-k', 'chrome.zip', 'out']
    assert extract_command('node.tar.gz', 'out', 'tar.gz') == ['/usr/bin/tar', '-xzf', 'node.tar.gz', '-C', 'out']
    with pytest.raises(ArchiveError, match='dmg'):
        extract_command('app.dmg', 'out', 'dmg')


def test_a_dmg_is_refused_by_the_generic_component_manager_before_download(tmp_path):
    catalog = Catalog(
        {
            'schema': 1,
            'components': {
                'app': {
                    'version': '1.0.0',
                    'platforms': {
                        platform_asset_key(): {
                            'archive': 'dmg',
                            'urls': ['https://example.com/app.dmg'],
                            'sha256': '0' * 64,
                            'size': 1,
                        }
                    },
                }
            },
        }
    )
    with pytest.raises(InstallError, match='desktop installer'):
        install_component(catalog, 'app', tmp_path)


def test_the_mac_components_live_under_the_chosen_data_root(tmp_path, monkeypatch):
    from services.components import paths

    monkeypatch.delenv('CIXI_COMPONENTS_DIR', raising=False)
    monkeypatch.setenv('CRAWLER_DATA_ROOT', str(tmp_path / 'root'))
    monkeypatch.setattr(paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(paths, 'platform_name', lambda: 'darwin')
    assert paths.components_root() == tmp_path / 'root' / 'components'
    assert paths.install_root() == tmp_path / 'root'


def test_the_checked_in_catalog_has_both_mac_arches_and_no_catbus_build():
    catalog = Catalog(load_catalog(CATALOG_PATH))
    for component_id in ('chrome', 'chromedriver', 'node'):
        for key in ('darwin-arm64', 'darwin-x64'):
            asset = catalog.get(component_id).asset(key)
            assert asset is not None, f'{component_id} has no {key} asset'
            assert len(asset.sha256) == 64
            assert asset.size > 0
            assert asset.urls and all(url.startswith('https://') for url in asset.urls)
    assert catalog.get('catbus').asset('darwin-arm64') is None
    assert catalog.get('catbus').asset('darwin-x64') is None
    assert catalog.get('catbus').asset('win32') is not None
    # The build script adds the application entry; the checked-in catalogue never names bytes that
    # have not been built yet.
    assert catalog.get('app').asset('darwin-arm64') is None


def test_the_build_script_pins_the_exact_app_dmg_it_will_publish(builder, tmp_path):
    dmg = tmp_path / 'CaiXiHui-macOS-arm64.dmg'
    dmg.write_bytes(b'a built application image')
    expected = hashlib.sha256(dmg.read_bytes()).hexdigest()
    payload = builder.build_catalog(dmg, 'arm64', 'exe-test', base=CATALOG_PATH)
    asset = payload['components']['app']['platforms']['darwin-arm64']
    assert asset['archive'] == 'dmg'
    assert asset['install_as'] == 'app'
    assert asset['sha256'] == expected
    assert asset['size'] == len(b'a built application image')
    assert asset['verify'] == ['CaiXiHui.app/Contents/MacOS/CaiXiHui']
    assert asset['urls'] == [
        'https://github.com/Xingye-Dujing/crawler-workflow/releases/download/exe-test/CaiXiHui-macOS-arm64.dmg'
    ]
    Catalog(payload)


def test_the_dmg_builder_can_wrap_either_app_bundle():
    source = (DESKTOP / 'build_macos.py').read_text(encoding='utf-8')
    assert "f'{stem}-macOS-{arch}.dmg'" in source
    assert 'stage / app.name' in source, 'the installer .app must keep its own bundle name'
    assert "os.symlink('/Applications'" in source


def test_the_build_script_maps_x86_64_to_the_catalogue_and_artifact_names(builder, tmp_path):
    dmg = tmp_path / 'app.dmg'
    dmg.write_bytes(b'x64')
    payload = builder.build_catalog(dmg, 'x86_64', 'tag', base=CATALOG_PATH)
    asset = payload['components']['app']['platforms']['darwin-x64']
    assert asset['urls'][0].endswith('/tag/CaiXiHui-macOS-x86_64.dmg')
    assert builder.artifact_arch('x86_64') == 'x86_64'
    assert builder.asset_key('x86_64') == 'x64'


def test_the_installer_reuses_the_shared_page_instead_of_a_second_copy(installer_app):
    source = (BOOTSTRAP / 'installer_macos.py').read_text(encoding='utf-8')
    assert "_load_shared('installer_shared', 'installer.py')" in source
    assert 'class MacInstallerState(installer.InstallerState)' in source
    assert 'class MacHandler(installer.Handler)' in source
    assert 'class MacInstallerServer(installer.InstallerServer)' in source
    assert installer_app.MAC_TEXT['zh']['not_writable'] != installer_app.TEXT['zh']['elevate_failed']
    assert installer_app.MAC_TEXT['en']['intro'] != installer_app.TEXT['en']['intro']


def test_the_application_is_installed_by_mounting_its_dmg_not_unpacking_a_zip(installer_app):
    source = (BOOTSTRAP / 'installer_macos.py').read_text(encoding='utf-8')
    assert 'hdiutil' in source and "'attach'" in source and "'detach'" in source
    assert '"/usr/bin/ditto"' in source or "'/usr/bin/ditto'" in source
    assert 'download_asset' in source
    assert 'safe_extract' not in source, 'a .app bundle must keep its symlinks and executable bits'
    assert installer_app.APP_BUNDLE == 'CaiXiHui.app'
    assert installer_app.APP_BINARY.as_posix() == 'Contents/MacOS/CaiXiHui'


def test_the_installer_records_the_data_folder_where_the_app_reads_it(installer_app):
    source = (BOOTSTRAP / 'installer_macos.py').read_text(encoding='utf-8')
    entry = (DESKTOP / 'macos_entry.py').read_text(encoding='utf-8')
    assert 'data-root.txt' in source and 'data-root.txt' in entry
    assert 'CRAWLER_DATA_ROOT' in source and 'CRAWLER_DATA_ROOT' in entry
    assert "'/usr/bin/defaults'" in source
    assert 'plistlib.loads' in entry
    assert installer_app.BUNDLE_ID == 'com.caixihui.desktop'


def test_the_workflow_builds_and_uploads_the_installer_for_both_arches():
    workflow = (REPO / '.github' / 'workflows' / 'macos-build.yml').read_text(encoding='utf-8')
    assert 'desktop/build_macos_installer.py --clean' in workflow
    assert '--app-dmg "dist/CaiXiHui-macOS-${{ matrix.arch }}.dmg"' in workflow
    assert '--release-tag "$RELEASE_TAG"' in workflow
    assert 'dist/CaiXiHui-Online-Setup-macOS-*.dmg' in workflow
    assert workflow.count('dist/CaiXiHui-Online-Setup-macOS-*.dmg') >= 2


def test_the_installer_spec_is_a_windowed_cocoa_bundle_with_the_generated_catalog():
    spec = (BOOTSTRAP / 'installer_macos.spec').read_text(encoding='utf-8')
    assert "name='CaiXiHui-Online-Setup.app'" in spec
    assert "bundle_identifier='com.caixihui.installer'" in spec
    assert 'console=False' in spec
    assert 'webview.platforms.cocoa' in spec and 'WebKit' in spec
    assert 'import pythonnet' not in spec
    assert "'pythonnet'" not in spec
    assert 'webview.platforms.winforms' not in spec
    assert "os.environ.get('CIXI_INSTALLER_CATALOG')" in spec
    assert "('installer.py'" in spec or "installer.py')," in spec


def test_the_installer_does_not_claim_a_windows_style_elevation_or_vpn(installer_app):
    words = json.dumps(installer_app.MAC_TEXT, ensure_ascii=False).lower()
    assert 'windows' not in words
    assert 'uac' not in words


@pytest.mark.skipif(sys.platform != 'darwin', reason='the macOS default folder is a macOS fact')
def test_the_mac_default_folders_are_user_writable(installer_app):
    assert installer_app.default_data_root() == Path.home() / 'Library' / 'Application Support' / 'CaiXiHui'
    root = installer_app.default_app_root()
    assert root.name == 'Applications'
