"""The Windows swap script, run for real against a throwaway install tree.

This is the step that silently never happened in every shipped build (the helper died on a
``DETACHED_PROCESS`` flag before its first statement, and the app had already killed itself). A
string assertion cannot catch that class of failure: only running the script and looking at the
files can. It is a device-tier case because it needs the real PowerShell the product uses.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from core import procs

from services import update, update_job

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name != 'nt', reason='the swap script is Windows PowerShell'),
    pytest.mark.skipif(shutil.which('powershell') is None, reason='powershell is not on PATH'),
]


def _wait_for(path: Path, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


def test_the_script_replaces_the_program_and_keeps_user_data(tmp_path):
    root = tmp_path / 'install'
    staged = tmp_path / 'staged'
    (root / 'app' / 'data').mkdir(parents=True)
    staged.mkdir()
    # The installed (old) build, with the two things a swap must never touch.
    (root / 'app' / 'CaiXiHui.exe').write_bytes(b'OLD-EXE')
    (root / 'app' / 'data-root.txt').write_text('D:/userdata', encoding='utf-8')
    (root / 'app' / 'data' / 'runs.db').write_bytes(b'PRECIOUS')
    # The payload.
    (staged / 'CaiXiHui.exe').write_bytes(b'NEW-EXE')
    (staged / '_internal').mkdir()
    (staged / '_internal' / 'python311.dll').write_bytes(b'dll')
    (staged / 'data-root.txt').write_text('SHOULD-NOT-WIN', encoding='utf-8')
    # A stand-in for the relaunched program: it must still be running when the script checks.
    launcher = tmp_path / 'launch.cmd'
    launcher.write_text('@echo off\r\nping -n 6 127.0.0.1 >nul\r\n', encoding='ascii')
    receipt = tmp_path / 'helper.started'
    marker = tmp_path / 'applying.marker'
    log = tmp_path / 'update.log'
    script = tmp_path / 'apply.ps1'
    script.write_text(update._WINDOWS_SCRIPT, encoding='utf-8')
    args = [
        '-AppPid',
        '0',
        '-WorkerPid',
        '0',
        '-InstallRoot',
        str(root),
        '-Staged',
        str(staged),
        '-Exe',
        str(launcher),
        '-Mode',
        'app',
        '-Receipt',
        str(receipt),
        '-Log',
        str(log),
        '-Marker',
        str(marker),
        '-VerifySeconds',
        '1',
    ]
    completed = subprocess.run(
        procs.powershell_command(str(script), [str(item) for item in args]),
        capture_output=True,
        timeout=120,
        check=False,
        **procs.popen_kwargs(),
    )
    assert completed.returncode == 0, completed.stderr.decode(errors='replace')
    assert receipt.is_file(), 'the receipt is what the app waits for before it exits'
    assert 'started' in receipt.read_text(encoding='utf-8')
    assert (root / 'app' / 'CaiXiHui.exe').read_bytes() == b'NEW-EXE'
    assert (root / 'app' / '_internal' / 'python311.dll').is_file()
    assert (root / 'app' / 'data-root.txt').read_text(encoding='utf-8') == 'D:/userdata'
    assert (root / 'app' / 'data' / 'runs.db').read_bytes() == b'PRECIOUS'
    assert (root / 'app.previous' / 'CaiXiHui.exe').read_bytes() == b'OLD-EXE'
    assert not marker.exists(), 'the marker must be gone once the swap is done'
    text = log.read_text(encoding='utf-8')
    assert 'files replaced' in text
    assert 'new build running' in text


def test_a_build_that_dies_right_after_launch_is_rolled_back(tmp_path):
    """The old build comes back when the new one cannot stay up — never a broken install."""
    root = tmp_path / 'install'
    staged = tmp_path / 'staged'
    root.mkdir()
    staged.mkdir()
    (root / 'CaiXiHui.exe').write_bytes(b'OLD-EXE')
    (root / 'keep.txt').write_text('user data', encoding='utf-8')
    (staged / 'CaiXiHui.exe').write_bytes(b'NEW-EXE')
    (staged / '_internal').mkdir()
    (staged / '_internal' / 'python311.dll').write_bytes(b'dll')
    # A launcher that exits immediately: the script's liveness check must catch it.
    launcher = tmp_path / 'launch.cmd'
    launcher.write_text('@echo off\r\nexit /b 0\r\n', encoding='ascii')
    marker = tmp_path / 'applying.marker'
    script = tmp_path / 'apply.ps1'
    script.write_text(update._WINDOWS_SCRIPT, encoding='utf-8')
    args = [
        '-AppPid',
        '0',
        '-WorkerPid',
        '0',
        '-InstallRoot',
        str(root),
        '-Staged',
        str(staged),
        '-Exe',
        str(launcher),
        '-Mode',
        'portable',
        '-Receipt',
        str(tmp_path / 'helper.started'),
        '-Log',
        str(tmp_path / 'update.log'),
        '-Marker',
        str(marker),
        '-VerifySeconds',
        '1',
    ]
    completed = subprocess.run(
        procs.powershell_command(str(script), args),
        capture_output=True,
        timeout=180,
        check=False,
        **procs.popen_kwargs(),
    )
    assert completed.returncode == 1
    assert (root / 'CaiXiHui.exe').read_bytes() == b'OLD-EXE', 'the old build was not restored'
    assert (root / 'keep.txt').read_text(encoding='utf-8') == 'user data'
    text = (tmp_path / 'update.log').read_text(encoding='utf-8')
    assert 'rolling back' in text
    assert not marker.exists(), 'a rollback also clears the in-progress marker'


def test_the_server_passes_both_peers_and_the_receipt_path(tmp_path, monkeypatch):
    """The spawn inside the product, without running it: args are the handshake's only contract."""
    staging = tmp_path / 'data' / 'updates' / '2026.11.12.1' / 'staged'
    staging.mkdir(parents=True)
    monkeypatch.setattr(update_job, 'data_dir', lambda root=None: tmp_path / 'data')
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(state=update_job.STATE_STAGED, staged=str(staging), worker_pid=777)
    monkeypatch.setattr(
        update,
        '_swap_targets',
        lambda: {'ok': True, 'mode': 'app', 'root': tmp_path, 'exe': tmp_path / 'app.exe'},
    )
    monkeypatch.setattr(update.machine, 'platform_name', lambda system=None: 'win32')
    seen = {}

    def fake_spawn(script, args):
        seen['args'] = args
        seen['script'] = script
        Path(args[args.index('-Receipt') + 1]).write_text('started', encoding='utf-8')
        return 1234

    monkeypatch.setattr(update, '_spawn_script', fake_spawn)
    assert update.request_restart()['ok'] is True
    args = seen['args']
    assert args[args.index('-WorkerPid') + 1] == '777'
    assert args[args.index('-AppPid') + 1] == str(os.getpid())
    assert args[args.index('-Marker') + 1] == str(update_job.marker_file())
    assert str(staging) in args
    assert seen['script'].name == 'apply.ps1'
