"""The signed-release and managed-install contract, provable without a certificate or Inno.

None of this needs a frozen exe, a Windows-only API or a signing key: the digest and receipt
modules are plain byte readers, and everything else here is a text contract on the scripts
that the release chain runs in order. The one ordering that matters is the one a signature
can silently lose -- UPX after signing, or a zip made from the unsigned folder.
"""

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
DESKTOP = REPO / 'desktop'
WORKFLOW = REPO / '.github' / 'workflows' / 'release-windows.yml'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def manifest():
    return _load('release_manifest', DESKTOP / 'release_manifest.py')


@pytest.fixture(scope='module')
def receipt():
    return _load('install_receipt', DESKTOP / 'install_receipt.py')


def _dist(root: Path, *, online=False) -> Path:
    dist = root / 'dist'
    (dist / 'CaiXiHui').mkdir(parents=True, exist_ok=True)
    for name, data in (
        ('CaiXiHui/CaiXiHui.exe', b'MZ launcher'),
        ('CaiXiHui-win64.zip', b'zip bytes'),
        ('CaiXiHui-Setup.exe', b'MZ setup'),
    ):
        (dist / name).write_bytes(data)
    if online:
        (dist / 'CaiXiHui-Online-Setup.exe').write_bytes(b'MZ online')
    return dist


def _install(root: Path, pointer: bytes = b'1.0.0\n', payload: dict | None = None) -> Path:
    holder = root / 'install'
    version = pointer.decode('utf-8', errors='replace').strip()
    (holder / 'versions' / version).mkdir(parents=True, exist_ok=True)
    (holder / 'current-version').write_bytes(pointer)
    body = payload or {
        'app': 'CaiXiHui',
        'artifact': 'desktop',
        'channel': 'stable',
        'method': 'direct',
        'version': version,
        'root': holder.as_posix(),
    }
    (holder / 'versions' / version / 'install.json').write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
    return holder


class TestTheReleaseManifest:
    def test_a_missing_signed_artifact_is_refused_by_name(self, manifest, tmp_path):
        dist = _dist(tmp_path)
        (dist / 'CaiXiHui-Setup.exe').unlink()
        with pytest.raises(manifest.ReleaseError) as caught:
            manifest.collect(dist)
        assert 'CaiXiHui-Setup.exe' in str(caught.value)
        assert manifest.main(['--dist', str(dist), '--version', '1.0.0']) == 1

    def test_the_sums_file_is_the_shape_sha256sum_reads(self, manifest, tmp_path, capsys):
        dist = _dist(tmp_path)
        assert manifest.main(['--dist', str(dist), '--version', '1.0.0']) == 0
        text = (dist / 'SHA256SUMS').read_text(encoding='ascii')
        lines = text.splitlines()
        assert len(lines) == 3
        assert [line.split('  ')[1] for line in lines] == sorted(manifest.REQUIRED)
        for line in lines:
            digest, name = line.split('  ')
            assert len(digest) == 64 and set(digest) <= set('0123456789abcdef')
            assert name in manifest.REQUIRED
        assert 'app catalog:' in capsys.readouterr().out

    def test_the_manifest_and_the_sums_describe_the_same_bytes(self, manifest, tmp_path):
        dist = _dist(tmp_path)
        payload = manifest.write_release(dist, '1.2.3', 'stable')
        recorded = json.loads((dist / 'release-manifest.json').read_text(encoding='utf-8'))
        assert recorded['version'] == '1.2.3' and recorded['channel'] == 'stable'
        assert recorded['artifacts'] == payload['artifacts'] == manifest.collect(dist)
        assert manifest.sums_text(payload['artifacts']) == (dist / 'SHA256SUMS').read_text(encoding='ascii')

    def test_the_catalog_hint_is_the_app_archive_digest(self, manifest, tmp_path):
        dist = _dist(tmp_path)
        payload = manifest.write_release(dist, '1.0.0', 'stable')
        hint = payload['catalog_hint']
        assert hint['component'] == 'app' and hint['platform'] == 'win32'
        assert hint['sha256'] == manifest.sha256_file(dist / 'CaiXiHui-win64.zip')
        assert hint['size'] == (dist / 'CaiXiHui-win64.zip').stat().st_size

    def test_a_changed_file_is_named_by_check(self, manifest, tmp_path, capsys):
        dist = _dist(tmp_path)
        manifest.write_release(dist, '1.0.0', 'stable')
        (dist / 'CaiXiHui-Setup.exe').write_bytes(b're-signed with different bytes')
        payload = json.loads((dist / 'release-manifest.json').read_text(encoding='utf-8'))
        problems = manifest.verify(dist, payload)
        assert any('CaiXiHui-Setup.exe: sha256' in item for item in problems)
        assert manifest.main(['--dist', str(dist), '--check']) == 1
        assert 'release manifest refused' in capsys.readouterr().err

    def test_an_optional_online_installer_is_hashed_only_when_present(self, manifest, tmp_path):
        dist = _dist(tmp_path)
        assert 'CaiXiHui-Online-Setup.exe' not in manifest.collect(dist)
        _dist(tmp_path, online=True)
        assert 'CaiXiHui-Online-Setup.exe' in manifest.collect(dist)

    def test_the_written_records_are_bom_free_and_leave_no_partial(self, manifest, tmp_path):
        dist = _dist(tmp_path)
        manifest.write_release(dist, '1.0.0', 'stable')
        for name in (manifest.SUMS_NAME, manifest.MANIFEST_NAME):
            raw = (dist / name).read_bytes()
            assert not raw.startswith(b'\xef\xbb\xbf'), f'{name} carries a BOM'
        assert not list(dist.glob('*.partial')), 'an atomic write left its staging file behind'

    def test_a_version_is_required_to_write_and_not_to_check(self, manifest, tmp_path, capsys):
        dist = _dist(tmp_path)
        assert manifest.main(['--dist', str(dist)]) == 1
        assert '--version is required' in capsys.readouterr().err


class TestTheInstallReceipt:
    def test_a_valid_pointer_resolves_to_the_receipt_it_names(self, receipt, tmp_path):
        holder = _install(tmp_path)
        record = receipt.read_install(holder)
        assert record['version'] == '1.0.0'
        assert record['channel'] == 'stable' and record['method'] == 'direct'
        assert record['receipt'].endswith('install.json')

    def test_a_bom_in_the_pointer_is_refused(self, receipt, tmp_path):
        holder = _install(tmp_path, pointer=b'\xef\xbb\xbf1.0.0\n')
        with pytest.raises(receipt.ReceiptError, match='BOM'):
            receipt.read_install(holder)

    def test_a_non_ascii_pointer_is_refused(self, receipt, tmp_path):
        with pytest.raises(receipt.ReceiptError, match='not valid ascii'):
            receipt.parse_pointer('1.0.0\n'.encode('utf-16'))

    def test_a_traversal_pointer_is_refused_before_it_becomes_a_path(self, receipt, tmp_path):
        for value in (b'..\\..\n', b'../etc\n', b'1.0.0/..\n', b'\n'):
            with pytest.raises(receipt.ReceiptError):
                receipt.parse_pointer(value)

    def test_a_bom_or_bad_encoding_in_the_receipt_is_refused(self, receipt):
        body = json.dumps({'app': 'CaiXiHui'}).encode('utf-8')
        for raw in (b'\xef\xbb\xbf' + body, b'\xff\xfe' + body):
            with pytest.raises(receipt.ReceiptError):
                receipt.parse_receipt(raw)

    def test_a_receipt_with_missing_keys_is_refused_by_name(self, receipt):
        with pytest.raises(receipt.ReceiptError, match='missing keys'):
            receipt.parse_receipt(json.dumps({'app': 'CaiXiHui'}).encode('utf-8'))

    def test_a_pointer_that_names_no_receipt_is_refused(self, receipt, tmp_path):
        holder = _install(tmp_path)
        (holder / 'current-version').write_bytes(b'9.9.9\n')
        with pytest.raises(receipt.ReceiptError, match='is missing'):
            receipt.read_install(holder)

    def test_a_receipt_that_disagrees_with_the_pointer_is_refused(self, receipt, tmp_path):
        body = {
            'app': 'CaiXiHui',
            'artifact': 'desktop',
            'channel': 'stable',
            'method': 'direct',
            'version': '0.9.0',
            'root': 'somewhere',
        }
        holder = _install(tmp_path, payload=body)
        with pytest.raises(receipt.ReceiptError, match='says'):
            receipt.read_install(holder)

    def test_a_non_ascii_install_root_survives_as_utf8(self, receipt):
        raw = json.dumps(
            {
                'app': 'CaiXiHui',
                'artifact': 'desktop',
                'channel': 'stable',
                'method': 'direct',
                'version': '1.0.0',
                'root': 'C:/Users/张三/CaiXiHui',
            },
            ensure_ascii=False,
        ).encode('utf-8')
        assert receipt.parse_receipt(raw)['root'].endswith('张三/CaiXiHui')

    def test_main_prints_the_verified_record(self, receipt, tmp_path, capsys):
        holder = _install(tmp_path)
        assert receipt.main(['--root', str(holder)]) == 0
        assert json.loads(capsys.readouterr().out)['version'] == '1.0.0'


class TestTheChainIsInTheRightOrder:
    def test_the_installer_leaves_managed_records_not_a_broad_kill(self):
        iss = (DESKTOP / 'installer.iss').read_text(encoding='utf-8-sig')
        assert (DESKTOP / 'installer.iss').read_bytes().startswith(b'\xef\xbb\xbf')
        for token in (
            'ChangesEnvironment=yes',
            'PrivilegesRequired=lowest',
            'StopManagedApp()',
            'function PrepareToInstall',
            'SaveStringsToUTF8FileWithoutBOM',
            'WriteAtomically(',
            'current-version',
            'install.json',
            'versions\\',
            'AddBinToPath()',
            'RemoveBinFromPath()',
            'bin\\CaiXiHui.cmd',
        ):
            assert token in iss, f'installer.iss lost {token}'
        assert '$_.Path' in iss and 'StartsWith(' in iss, 'the stop must be filtered by executable path'
        assert 'taskkill' not in iss
        assert iss.count('StopManagedApp();') == 3, 'the definition plus the install and uninstall call sites'
        assert iss.index('ForceDirectories(') < iss.index('WriteUtf8Atomically(ExpandConstant'), (
            'the receipt directory must exist before the UTF-8 writer opens it'
        )
        assert '#ifndef MyAppVersion' in iss, 'the build must be able to stamp a version with /D'

    def test_the_path_launcher_forwards_every_argument(self):
        raw = (DESKTOP / 'bin' / 'CaiXiHui.cmd').read_bytes()
        assert not {byte for byte in raw if byte > 127}, 'a .cmd is read in the console codepage'
        text = raw.decode('ascii')
        assert '"%~dp0..\\CaiXiHui.exe" %*' in text
        assert 'exit /b' in text

    def test_signing_sits_between_upx_and_the_installer(self):
        script = (DESKTOP / 'build_windows.ps1').read_text(encoding='ascii')
        sign_exe = '& $SignScript -Target @($LauncherExe)'
        sign_setup = '& $SignScript -Target $targets'
        assert (
            script.index('prune_dist.py')
            < script.index('compress_dist.py')
            < script.index(sign_exe)
            < script.index('Invoke-Exe $iscc')
            < script.index(sign_setup)
            < script.index('CreateFromDirectory')
        ), 'UPX after signing destroys it; a zip made before signing ships unsigned bytes'
        assert '[switch]$Sign' in script and '[switch]$PackageOnly' in script
        assert '/DMyAppVersion=$Version' in script, 'the installer needs the same version as the manifest'
        assert '$env:CIXI_SIGN_' not in script, 'the compile stage must not read a credential'
        assert 'if ($PackageOnly -and $Clean)' in script
        assert "'-PackageOnly wraps an existing folder" in script

    def test_the_signing_stage_timestamps_and_verifies(self):
        sign = (DESKTOP / 'sign_windows.ps1').read_text(encoding='ascii')
        for token in (
            "'/tr'",
            "'/td'",
            "'SHA256'",
            'Get-AuthenticodeSignature',
            'TimeStamperCertificate',
            'CIXI_SIGN_MODE',
            'no signing credentials',
            'signtool.exe not found',
        ):
            assert token in sign, f'sign_windows.ps1 lost {token}'
        assert sign.index('& $signtool') < sign.index('Assert-Signature $resolved')
        for line in sign.splitlines():
            if 'Write-Host' in line:
                assert '$password' not in line and 'CIXI_SIGN_PASSWORD' not in line, (
                    'a secret must not reach the console'
                )

    def test_the_new_scripts_stay_ascii(self):
        for path in (
            DESKTOP / 'build_windows.ps1',
            DESKTOP / 'sign_windows.ps1',
            DESKTOP / 'bin' / 'CaiXiHui.cmd',
            WORKFLOW,
        ):
            raw = path.read_bytes()
            assert not {byte for byte in raw if byte > 127}, f'{path.name} has non-ASCII bytes'
            assert not raw.startswith(b'\xef\xbb\xbf'), f'{path.name} hides its encoding behind a BOM'

    def test_the_workflow_keeps_credentials_out_of_the_compile_job(self):
        wf = WORKFLOW.read_text(encoding='ascii')
        assert wf.count('environment: release') == 2, 'only the two signing jobs see secrets'
        build_job = wf.split('  build:')[1].split('\n  sign-exe:')[0]
        assert 'environment:' not in build_job and 'secrets.' not in build_job
        assert 'CIXI_SIGN_PFX_BASE64' in wf
        assert wf.index('name: Compile, unsigned') < wf.index('name: Sign the launcher')
        assert wf.index('name: Sign the installer') < wf.index('name: Hash the final bytes')
        assert 'release_manifest.py --dist dist --check' in wf

    def test_the_readme_states_the_chain_and_its_limits(self):
        readme = (DESKTOP / 'README.md').read_text(encoding='utf-8')
        for token in ('-Sign', '-PackageOnly', 'SHA256SUMS', 'release_manifest.py', 'install_receipt.py'):
            assert token in readme, f'desktop/README.md does not document {token}'
