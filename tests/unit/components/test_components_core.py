"""The component core: catalogue validation, safe archives, fetch, install and the manifest.

These cases use only tmp files and ``file://`` URLs: no network, no Chrome, no daemon. The point is
that every refusal is named (bad schema, HTTP URL, missing digest, zip-slip, wrong payload) and that
a failed install leaves no half-written component behind.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from core.machine import browser_version, platform_name

from services.components import install as install_module
from services.components import probe as probe_module
from services.components.archive import ArchiveError, safe_extract
from services.components.catalog import Asset, Catalog, CatalogError, Part, load_catalog
from services.components.fetch import DownloadCancelledError, DownloadError, download_asset
from services.components.install import InstallError, install_component, remove_component
from services.components.manifest import Manifest, ManifestError
from services.components.paths import components_root, install_root


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as handle:
        for name, payload in entries.items():
            handle.writestr(name, payload)
    return buffer.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _asset(path: Path, sha: str, size: int, **changes) -> Asset:
    values = {
        'urls': (path.as_uri(),),
        'parts': (),
        'sha256': sha,
        'size': size,
        'archive': 'zip',
        'strip_prefix': 'top',
        'install_as': 'component',
        'verify': ('hello.txt',),
    }
    values.update(changes)
    return Asset(**values)


class TestCatalog:
    def test_the_bundled_catalogue_is_valid_and_defaults_to_the_domestic_route(self):
        catalog = Catalog(load_catalog())
        # The installer is a Windows desktop component; asking for the host asset on Linux would
        # find none (the catalogue has win32 entries only), not a broken catalogue.
        defaults = catalog.defaults('win32')
        assert {'app', 'chrome', 'chromedriver', 'node', 'catbus'} <= set(defaults)
        chrome = catalog.get('chrome').asset('win32')
        assert chrome is not None and 'npmmirror.com' in chrome.urls[0], 'the novice default must not need a VPN'
        catbus = catalog.get('catbus').asset('win32')
        assert catbus is not None and catbus.parts and 'gitee.com' in catbus.parts[0].url

    def test_a_schema_this_installer_does_not_know_is_refused(self):
        with pytest.raises(CatalogError, match='schema'):
            Catalog({'schema': 999, 'components': {}})

    def test_a_version_that_would_escape_the_component_folder_is_refused(self):
        payload = {'schema': 1, 'components': {'x': {'version': '../evil', 'platforms': {'win32': {}}}}}
        with pytest.raises(CatalogError, match='unusable version'):
            Catalog(payload)

    def test_an_http_url_and_a_missing_digest_are_refused_by_name(self):
        base = {
            'schema': 1,
            'components': {
                'x': {
                    'version': '1',
                    'platforms': {
                        'win32': {
                            'urls': ['http://example.com/x.zip'],
                            'sha256': '0' * 64,
                            'size': 1,
                        }
                    },
                }
            },
        }
        with pytest.raises(CatalogError, match='https'):
            Catalog(base)
        base['components']['x']['platforms']['win32']['urls'] = ['https://example.com/x.zip']
        base['components']['x']['platforms']['win32']['sha256'] = 'nope'
        with pytest.raises(CatalogError, match='sha256'):
            Catalog(base)


class TestManifest:
    def test_a_record_survives_a_reload_and_pruning_keeps_the_newest(self, tmp_path):
        manifest = Manifest(tmp_path)
        for index, version in enumerate(('1.0', '2.0', '3.0')):
            path = tmp_path / 'components' / 'node' / version
            path.mkdir(parents=True)
            os.utime(path, (1000 + index, 1000 + index))
        manifest.record('node', '3.0', tmp_path / 'components' / 'node' / '3.0', 'a' * 64, 'https://example.com')
        manifest.save()
        assert Manifest(tmp_path).load().get('node')['version'] == '3.0'
        removed = Manifest(tmp_path).load().prune('node', keep=2)
        assert [item.name for item in removed] == ['1.0']
        assert (tmp_path / 'components' / 'node' / '3.0').exists()

    def test_a_path_outside_the_root_is_refused(self, tmp_path):
        manifest = Manifest(tmp_path)
        with pytest.raises(ManifestError, match='escapes'):
            manifest.record('x', '1', tmp_path.parent / 'elsewhere', 'a' * 64, '')


class TestArchive:
    def test_the_top_folder_is_stripped_and_files_land_inside(self, tmp_path):
        archive = tmp_path / 'a.zip'
        archive.write_bytes(_zip_bytes({'top/hello.txt': b'hi', 'top/sub/a.txt': b'a'}))
        target = tmp_path / 'out'
        safe_extract(archive, target, strip_prefix='top')
        assert (target / 'hello.txt').read_bytes() == b'hi'
        assert (target / 'sub' / 'a.txt').read_bytes() == b'a'

    def test_parent_traversal_is_refused_and_writes_nothing_outside(self, tmp_path):
        archive = tmp_path / 'bad.zip'
        archive.write_bytes(_zip_bytes({'../evil.txt': b'x'}))
        target = tmp_path / 'out'
        with pytest.raises(ArchiveError, match='parent traversal'):
            safe_extract(archive, target)
        assert not (tmp_path / 'evil.txt').exists()

    def test_an_symlink_entry_is_refused(self, tmp_path):
        archive = tmp_path / 'link.zip'
        info = zipfile.ZipInfo('top/link')
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, 'w') as handle:
            handle.writestr(info, '')
        with pytest.raises(ArchiveError, match='symlink'):
            safe_extract(archive, tmp_path / 'out')


class TestFetch:
    def test_a_file_url_is_accepted_only_when_insecure_is_explicit(self, tmp_path):
        source = tmp_path / 'x.zip'
        source.write_bytes(b'payload')
        asset = _asset(source, _sha(b'payload'), 7)
        with pytest.raises(DownloadError, match='non-HTTPS'):
            download_asset(asset, tmp_path / 'copy.zip')
        assert download_asset(asset, tmp_path / 'copy.zip', allow_insecure=True).read_bytes() == b'payload'

    def test_a_checksum_mismatch_deletes_the_download_and_names_the_file(self, tmp_path):
        source = tmp_path / 'x.zip'
        source.write_bytes(b'payload')
        asset = _asset(source, '0' * 64, 7)
        with pytest.raises(DownloadError, match='SHA-256'):
            download_asset(asset, tmp_path / 'copy.zip', allow_insecure=True)
        assert not (tmp_path / 'copy.zip').exists()

    def test_a_cancel_keeps_the_partial_file_for_the_next_attempt(self, tmp_path):
        source = tmp_path / 'x.zip'
        source.write_bytes(b'payload')
        asset = _asset(source, _sha(b'payload'), 7)
        target = tmp_path / 'copy.zip'
        with pytest.raises(DownloadCancelledError):
            download_asset(asset, target, allow_insecure=True, cancel=lambda: True)
        assert target.exists(), 'the bytes already fetched must not be deleted by the Cancel button'
        assert download_asset(asset, target, allow_insecure=True).read_bytes() == b'payload'

    def test_parts_are_concatenated_and_verified_as_one_file(self, tmp_path):
        first, second = b'hello ', b'world'
        part_a, part_b = tmp_path / 'a.001', tmp_path / 'a.002'
        part_a.write_bytes(first)
        part_b.write_bytes(second)
        asset = _asset(
            part_a,
            _sha(first + second),
            len(first + second),
            urls=(),
            parts=(
                Part(url=part_a.as_uri(), sha256=_sha(first), size=len(first)),
                Part(url=part_b.as_uri(), sha256=_sha(second), size=len(second)),
            ),
        )
        target = download_asset(asset, tmp_path / 'joined.zip', allow_insecure=True)
        assert target.read_bytes() == first + second


class TestInstall:
    @pytest.fixture
    def catalogue(self):
        system = platform_name()
        return Catalog(
            {
                'schema': 1,
                'components': {
                    'demo': {
                        'version': '1.0',
                        'platforms': {
                            system: {
                                'archive': 'zip',
                                'strip_prefix': 'top',
                                'verify': ['hello.txt'],
                                'urls': ['https://example.com/demo.zip'],
                                'sha256': '0' * 64,
                                'size': 1,
                            }
                        },
                    }
                },
            }
        )

    def test_install_extracts_registers_and_removes(self, tmp_path, catalogue, monkeypatch):
        archive = tmp_path / 'demo.zip'
        archive.write_bytes(_zip_bytes({'top/hello.txt': b'hi'}))

        def fake_download(asset, dest, **kwargs):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(archive.read_bytes())
            return Path(dest)

        monkeypatch.setattr(install_module, 'download_asset', fake_download)
        target = install_component(catalogue, 'demo', tmp_path / 'root')
        assert (target / 'hello.txt').read_bytes() == b'hi'
        record = Manifest(tmp_path / 'root').load().get('demo')
        assert record['version'] == '1.0'
        assert remove_component(tmp_path / 'root', 'demo')
        assert not target.exists()

    def test_a_payload_without_the_expected_file_is_refused(self, tmp_path, catalogue, monkeypatch):
        archive = tmp_path / 'demo.zip'
        archive.write_bytes(_zip_bytes({'top/other.txt': b'hi'}))

        def fake_download(asset, dest, **kwargs):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(archive.read_bytes())
            return Path(dest)

        monkeypatch.setattr(install_module, 'download_asset', fake_download)
        with pytest.raises(InstallError, match='hello.txt'):
            install_component(catalogue, 'demo', tmp_path / 'root')
        assert not (tmp_path / 'root' / 'components' / 'demo').exists()

    def test_a_removal_that_cannot_delete_the_folder_keeps_the_record(self, tmp_path, catalogue, monkeypatch):
        """A running Chrome can hold its own directory: the record must not vanish while the files stay."""
        archive = tmp_path / 'demo.zip'
        archive.write_bytes(_zip_bytes({'top/hello.txt': b'hi'}))

        def fake_download(asset, dest, **kwargs):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(archive.read_bytes())
            return Path(dest)

        monkeypatch.setattr(install_module, 'download_asset', fake_download)
        install_component(catalogue, 'demo', tmp_path / 'root')

        def refuse(*_args, **_kwargs):
            raise OSError('the file is in use')

        monkeypatch.setattr(install_module.shutil, 'rmtree', refuse)
        with pytest.raises(InstallError, match='cannot delete'):
            remove_component(tmp_path / 'root', 'demo')
        assert Manifest(tmp_path / 'root').load().get('demo') is not None

    def test_the_environment_reads_the_manifest_the_installer_wrote(self, tmp_path, catalogue, monkeypatch):
        archive = tmp_path / 'demo.zip'
        archive.write_bytes(_zip_bytes({'top/hello.txt': b'hi'}))

        def fake_download(asset, dest, **kwargs):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(archive.read_bytes())
            return Path(dest)

        monkeypatch.setattr(install_module, 'download_asset', fake_download)
        install_component(catalogue, 'demo', tmp_path / 'root')
        rows = probe_module.component_rows(tmp_path / 'root', None)
        assert [row['id'] for row in rows] == ['demo'], 'the probe must look where the installer wrote the manifest'

    def test_a_component_whose_folder_disappeared_is_not_reported_as_installed(self, tmp_path, catalogue, monkeypatch):
        archive = tmp_path / 'demo.zip'
        archive.write_bytes(_zip_bytes({'top/hello.txt': b'hi'}))

        def fake_download(asset, dest, **kwargs):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(archive.read_bytes())
            return Path(dest)

        monkeypatch.setattr(install_module, 'download_asset', fake_download)
        install_component(catalogue, 'demo', tmp_path / 'root')
        shutil.rmtree(tmp_path / 'root' / 'components' / 'demo')
        rows = probe_module.component_rows(tmp_path / 'root', None)
        assert rows[0]['state'] == 'missing', 'the manifest record outlived the files it names'

    @staticmethod
    def _app_catalog(version: str) -> Catalog:
        return Catalog(
            {
                'schema': 1,
                'components': {
                    'app': {
                        'version': version,
                        'platforms': {
                            platform_name(): {
                                'archive': 'zip',
                                'strip_prefix': 'top',
                                'install_as': 'app',
                                'verify': ['hello.txt'],
                                'urls': ['https://example.com/app.zip'],
                                'sha256': '0' * 64,
                                'size': 1,
                            }
                        },
                    }
                },
            }
        )

    def test_a_new_application_version_replaces_app_and_keeps_the_previous_copy(self, tmp_path, monkeypatch):
        """The app lives in one folder, so "the exe is there" cannot mean "this version is there"."""
        current = {'bytes': _zip_bytes({'top/hello.txt': b'one'})}

        def fake_download(asset, dest, **kwargs):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(current['bytes'])
            return Path(dest)

        monkeypatch.setattr(install_module, 'download_asset', fake_download)
        root = tmp_path / 'root'
        install_component(self._app_catalog('1.0'), 'app', root)
        assert (root / 'app' / 'hello.txt').read_bytes() == b'one'
        current['bytes'] = _zip_bytes({'top/hello.txt': b'two'})
        install_component(self._app_catalog('2.0'), 'app', root)
        assert (root / 'app' / 'hello.txt').read_bytes() == b'two', 'a version bump must replace the app folder'
        assert (root / 'app.previous' / 'hello.txt').read_bytes() == b'one', 'the old build is the rollback'
        assert Manifest(root).load().get('app')['version'] == '2.0'


class TestComponentSource:
    """The installer's copy and the machine's copy are both legitimate; the user chooses."""

    def test_a_stored_path_inside_the_installers_tree_is_ignored_when_the_machine_is_chosen(
        self, tmp_path, monkeypatch
    ):
        from services.components import source

        components = tmp_path / 'components'
        monkeypatch.setenv('CIXI_COMPONENTS_DIR', str(components))
        monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'system')
        stored = str(components / 'chrome' / '1.0' / 'chrome.exe')
        assert source.usable(stored) == ''
        # A path the user really chose elsewhere still wins.
        assert source.usable('/opt/chrome') == '/opt/chrome'

    def test_the_same_stored_path_is_kept_when_the_installer_is_chosen(self, tmp_path, monkeypatch):
        from services.components import source

        components = tmp_path / 'components'
        (tmp_path / 'install-manifest.json').write_text('{"schema":1,"components":{}}', encoding='utf-8')
        monkeypatch.setenv('CIXI_COMPONENTS_DIR', str(components))
        monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'bundled')
        stored = str(components / 'chrome' / '1.0' / 'chrome.exe')
        assert source.usable(stored) == stored

    def test_a_machine_path_is_ignored_when_the_installer_is_chosen(self, tmp_path, monkeypatch):
        """The reverse of the 本机 rule: a saved local Chrome cannot outvote 安装器安装的 either."""
        from services.components import source

        (tmp_path / 'install-manifest.json').write_text('{"schema":1,"components":{}}', encoding='utf-8')
        monkeypatch.setenv('CIXI_COMPONENTS_DIR', str(tmp_path / 'components'))
        monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'bundled')
        assert source.usable(str(tmp_path / 'machine-chrome')) == ''

    def test_without_an_installer_tree_the_stored_choice_means_the_machine(self, tmp_path, monkeypatch):
        """A zip/source/cloud install has no manifest; making it strict would refuse every crawl."""
        from services.components import source

        monkeypatch.setenv('CIXI_COMPONENTS_DIR', str(tmp_path / 'components'))
        monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'bundled')
        assert source.installer_available() is False
        assert source.prefer_bundled() is False
        assert source.usable('/usr/bin/chromium') == '/usr/bin/chromium'

    def test_the_launcher_reads_the_preference_before_config_exists(self, tmp_path):
        from services.components import source

        (tmp_path / 'data').mkdir()
        (tmp_path / 'data' / 'settings.json').write_text('{"component_source": "system"}', encoding='utf-8')
        assert source.stored_source(tmp_path) == 'system'

    def test_a_broken_or_missing_settings_file_means_the_default(self, tmp_path):
        from services.components import source

        assert source.stored_source(tmp_path) == 'bundled'
        (tmp_path / 'data').mkdir()
        (tmp_path / 'data' / 'settings.json').write_text('{not json', encoding='utf-8')
        assert source.stored_source(tmp_path) == 'bundled'

    def test_a_typo_is_not_a_third_choice(self):
        from services.components import source

        assert source.normalize('system') == 'system'
        assert source.normalize('BUNDLED') == 'bundled'
        assert source.normalize('laptop') == 'bundled'


class TestPaths:
    def test_the_components_directory_is_one_level_below_the_install_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv('CIXI_COMPONENTS_DIR', str(tmp_path / 'root' / 'components'))
        assert components_root() == tmp_path / 'root' / 'components'
        assert install_root() == tmp_path / 'root'

    def test_an_explicit_root_is_the_install_root(self, tmp_path):
        assert install_root(tmp_path / 'somewhere') == tmp_path / 'somewhere'


class TestBrowserVersion:
    def test_a_missing_file_has_no_version(self, tmp_path):
        assert browser_version(str(tmp_path / 'missing-chrome')) == ''

    def test_an_existing_executable_answers_its_version(self):
        # A Windows GUI binary (chrome.exe) is read through its version resource; this checks the
        # resolver answers for an executable that exists on every machine the suite runs on.
        assert browser_version(sys.executable)


class TestCrawlCapability:
    def test_a_missing_driver_is_degraded_because_selenium_manager_can_fetch_one(self, monkeypatch):
        """The launcher prints "Selenium downloads a matching driver"; the panel must not call it off."""
        monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'system')
        monkeypatch.setattr(probe_module, '_setting', lambda key: '')
        monkeypatch.setattr(probe_module, 'find_chrome', lambda *args, **kwargs: '/opt/chrome')
        monkeypatch.setattr(probe_module, '_driver', lambda root: ('', 'none'))
        row = probe_module._crawl_selenium(Path('.'))
        assert row['state'] == 'degraded'
        assert row['reason_key'] == 'env.driverAutoDownload'

    def test_installer_source_reports_the_missing_installer_chrome_not_the_machines(self, monkeypatch):
        """安装器安装的: no installer copy means missing, even when the machine has a Chrome."""
        monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'bundled')
        monkeypatch.setattr(probe_module.component_source, 'prefer_bundled', lambda: True)
        monkeypatch.setattr(probe_module, '_setting', lambda key: '')
        monkeypatch.setattr(probe_module, '_component_binary', lambda root, component_id: '')
        monkeypatch.setattr(probe_module, 'find_chrome', lambda *args, **kwargs: '')
        row = probe_module._crawl_selenium(Path('.'))
        assert row['state'] == 'missing'
        assert row['reason_key'] == 'env.installerBrowserMissing'
        assert row['source'] == 'installer-missing'

    def test_installer_source_reports_the_missing_installer_driver_not_selenium_manager(self, monkeypatch):
        monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'bundled')
        monkeypatch.setattr(probe_module.component_source, 'prefer_bundled', lambda: True)
        monkeypatch.setattr(probe_module, '_setting', lambda key: '')
        monkeypatch.setattr(probe_module, '_component_binary', lambda root, component_id: '/opt/chrome')
        monkeypatch.setattr(probe_module, 'find_chrome', lambda *args, **kwargs: '/opt/chrome')
        monkeypatch.setattr(probe_module, '_driver', lambda root: ('', 'installer-missing'))
        row = probe_module._crawl_selenium(Path('.'))
        assert row['state'] == 'missing'
        assert row['reason_key'] == 'env.installerDriverMissing'

    def test_a_configured_browser_that_is_gone_is_named_rather_than_guessed(self, monkeypatch):
        monkeypatch.setenv('CIXI_COMPONENT_SOURCE', 'system')
        monkeypatch.setattr(
            probe_module, '_setting', lambda key: r'C:\gone\chrome.exe' if key == 'browser_binary' else ''
        )
        monkeypatch.setattr(probe_module, 'find_chrome', lambda *args, **kwargs: '')
        monkeypatch.setattr(probe_module, '_driver', lambda root: ('', 'none'))
        row = probe_module._crawl_selenium(Path('.'))
        assert row['state'] == 'missing'
        assert row['reason_key'] == 'env.browserConfiguredMissing'
        assert row['reason_params']['path'].endswith('chrome.exe')

    def test_the_machine_copy_wins_when_the_installer_copy_is_not_chosen(self, monkeypatch, tmp_path):
        """A matching Chrome in the installer's folder must not overrule 本机."""
        chrome = tmp_path / 'components' / 'chrome' / '1.0' / 'chrome.exe'
        chrome.parent.mkdir(parents=True)
        chrome.write_bytes(b'')
        manifest = Manifest(tmp_path)
        manifest.record('chrome', '1.0', chrome.parent, 'a' * 64, 'https://example.com')
        manifest.save()
        monkeypatch.setattr(probe_module.component_source, 'prefer_bundled', lambda: False)
        monkeypatch.setattr(probe_module, '_setting', lambda key: '')
        monkeypatch.setattr(probe_module, 'find_chrome', lambda *args, **kwargs: '/usr/bin/google-chrome')
        monkeypatch.setattr(probe_module, '_driver', lambda root: ('', 'none'))
        row = probe_module._crawl_selenium(tmp_path)
        assert row['source'] == 'system'
        assert row['reason_params']['chrome'] == '/usr/bin/google-chrome'

    def test_a_configured_driver_that_is_gone_is_named_rather_than_guessed(self, monkeypatch):
        settings = {'browser_binary': '', 'driver_path': r'C:\gone\chromedriver.exe'}
        monkeypatch.setattr(probe_module, '_setting', lambda key: settings.get(key, ''))
        monkeypatch.setattr(probe_module, 'find_chrome', lambda *args, **kwargs: '/opt/chrome')
        monkeypatch.setattr(probe_module, '_driver', lambda root: ('', 'settings-missing'))
        row = probe_module._crawl_selenium(Path('.'))
        assert row['state'] == 'missing'
        assert row['reason_key'] == 'env.driverConfiguredMissing'
        assert row['reason_params']['path'].endswith('chromedriver.exe')
