"""Self-update for the main program: version check, download, staged swap, restart.

Components change rarely and the application ships often, so this module owns only the
application payload. It never touches ``components/``, ``data/``, logs, cookies or models: the
downloaded archive is extracted into a staging folder beside the running install and a small
per-OS script swaps the program entries after this process exits.

The feed is a small ``version.json`` in the repository (served raw by Gitee, with GitHub as a
fallback), never a release API: the app only needs a version, notes and one verified asset. The
download is checked against the feed's SHA-256 before anything is staged; a mismatch is a refusal,
not a retry with an unverified file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from core import machine, procs
from core.config import Config
from version import APP_VERSION

from services.components.archive import ArchiveError, safe_extract

#: The same file two ways: Gitee is the primary network in China, GitHub the fallback.
FEED_URLS = (
    'https://gitee.com/Xingye-Dujing/crawler-workflow/raw/main/version.json',
    'https://raw.githubusercontent.com/Xingye-Dujing/crawler-workflow/main/version.json',
)

#: A stale check is cheap; asking on every boot would be noise, and the feed is a static file.
FEED_TTL = 30 * 60
USER_AGENT = 'CaiXiHui-updater'
_JOB_LOCK = threading.Lock()
_JOB: dict = {}
_FEED_CACHE: dict = {'at': 0.0, 'feed': None, 'error': ''}


def current_version() -> str:
    return APP_VERSION


def version_tuple(text: str) -> tuple[int, ...]:
    """A comparable tuple; anything unparseable sorts below every real version."""
    parts = tuple(int(part) for part in re.findall(r'\d+', str(text or '')))
    return parts or (0,)


def is_newer(latest: str, current: str) -> bool:
    return version_tuple(latest) > version_tuple(current)


def updates_root() -> Path:
    return Path(Config.DATA_DIR) / 'updates'


def _frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def install_layout() -> tuple[str, Path | None, Path]:
    """``(mode, install root, executable)`` for the running build.

    ``app`` is the online installer's ``<root>/app/CaiXiHui.exe`` layout; anything else is a
    portable folder. ``macapp`` is the macOS bundle, whose ``.app`` is moved as one unit.
    """
    exe = Path(sys.executable).resolve()
    if machine.platform_name() == 'darwin':
        for parent in exe.parents:
            if parent.suffix == '.app':
                return 'macapp', parent, exe
        return '', None, exe
    if exe.parent.name == 'app':
        return 'app', exe.parent.parent, exe
    return 'portable', exe.parent, exe


def _platform_key() -> str:
    return machine.platform_asset_key()


def _asset(feed: dict) -> dict:
    platforms = feed.get('platforms') if isinstance(feed, dict) else None
    asset = (platforms or {}).get(_platform_key())
    return asset if isinstance(asset, dict) else {}


def _fetch(url: str, timeout: float = 8.0) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _valid_feed(payload) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get('schema') == 1
        and bool(str(payload.get('version') or '').strip())
        and isinstance(payload.get('platforms'), dict)
    )


def fetch_feed(force: bool = False) -> dict | None:
    """The cached release feed, or ``None`` with the reason kept in ``_FEED_CACHE``."""
    with _JOB_LOCK:
        if not force and _FEED_CACHE['feed'] and time.monotonic() - _FEED_CACHE['at'] < FEED_TTL:
            return _FEED_CACHE['feed']
    error = ''
    for url in FEED_URLS:
        try:
            payload = json.loads(_fetch(url).decode('utf-8'))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            error = f'{url}: {exc}'
            continue
        if not _valid_feed(payload):
            error = f'{url}: not a version feed'
            continue
        with _JOB_LOCK:
            _FEED_CACHE.update({'at': time.monotonic(), 'feed': payload, 'error': ''})
        return payload
    with _JOB_LOCK:
        _FEED_CACHE.update({'at': time.monotonic(), 'feed': None, 'error': error or 'no feed'})
    return None


def _cleanup_updates() -> None:
    """Drop staged packages from previous versions; the running app never needs them again."""
    with _JOB_LOCK:
        active = _JOB.get('state') in ('downloading', 'staging', 'done')
    if active:
        return
    root = updates_root()
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)


def check() -> dict:
    current = current_version()
    if not _frozen():
        return {'ok': True, 'supported': False, 'current': current, 'reason': 'source'}
    _cleanup_updates()
    feed = fetch_feed()
    if feed is None:
        with _JOB_LOCK:
            error = _FEED_CACHE['error']
        return {'ok': False, 'supported': True, 'current': current, 'error': error}
    latest = str(feed.get('version') or '').strip()
    asset_ready = bool(_asset(feed))
    return {
        'ok': True,
        'supported': True,
        'current': current,
        'latest': latest,
        # A version with no asset for THIS platform is not an offer the user can act on.
        'update_available': asset_ready and is_newer(latest, current),
        'notes': str(feed.get('notes') or ''),
        'platform': _platform_key(),
        'asset_ready': asset_ready,
    }


def _size_of(asset: dict) -> int:
    try:
        return int(asset.get('size') or 0)
    except (TypeError, ValueError):
        return 0


def _stream(url: str, destination: Path) -> int:
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    written = 0
    with urllib.request.urlopen(request, timeout=60) as response, open(destination, 'wb') as handle:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            handle.write(block)
            written += len(block)
    return written


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _set_job(**values) -> None:
    with _JOB_LOCK:
        _JOB.update(values)


def _fail(message: str) -> None:
    _set_job(state='failed', error=str(message)[:500])


def _download_package(asset: dict, package: Path) -> None:
    parts = asset.get('parts') if isinstance(asset.get('parts'), list) else []
    total = _size_of(asset)
    done = 0
    if parts:
        with open(package, 'wb') as output:
            for index, part in enumerate(parts, 1):
                url = str(part.get('url') or '').strip()
                expected_size = int(part.get('size') or 0)
                part_path = package.with_name(f'{package.name}.part{index:03d}')
                try:
                    written = _stream(url, part_path)
                except (OSError, urllib.error.URLError) as exc:
                    raise RuntimeError(f'第 {index} 个分片下载失败：{exc}') from exc
                if expected_size and written != expected_size:
                    raise RuntimeError(f'第 {index} 个分片大小不对：{written} != {expected_size}')
                expected_sha = str(part.get('sha256') or '').strip()
                if expected_sha and _sha256(part_path) != expected_sha:
                    raise RuntimeError(f'第 {index} 个分片校验失败')
                with open(part_path, 'rb') as reader:
                    shutil.copyfileobj(reader, output, 1024 * 1024)
                part_path.unlink(missing_ok=True)
                done += written
                _set_job(progress=min(95, int(done * 95 / total)) if total else 0)
    else:
        url = str(asset.get('url') or '').strip()
        if not url:
            raise RuntimeError('发行清单里没有这个平台的安装包')
        try:
            _stream(url, package)
        except (OSError, urllib.error.URLError) as exc:
            raise RuntimeError(f'下载失败：{exc}') from exc
        _set_job(progress=90)
    expected_sha = str(asset.get('sha256') or '').strip()
    if expected_sha and _sha256(package) != expected_sha:
        raise RuntimeError('安装包 SHA-256 校验失败，已拒绝使用')
    expected_size = _size_of(asset)
    if expected_size and package.stat().st_size != expected_size:
        raise RuntimeError(f'安装包大小不对：{package.stat().st_size} != {expected_size}')


def _stage_macos(package: Path, staging: Path) -> Path:
    """Mount the DMG and copy the one ``.app`` out of it; returns the staged bundle."""
    staging.mkdir(parents=True, exist_ok=True)
    mount = staging / 'mnt'
    mount.mkdir()
    try:
        subprocess.run(
            ['hdiutil', 'attach', '-nobrowse', '-readonly', '-mountpoint', str(mount), str(package)],
            check=True,
            capture_output=True,
            timeout=120,
            **procs.popen_kwargs(),
        )
        try:
            bundles = sorted(mount.glob('*.app'))
            if not bundles:
                raise RuntimeError('DMG 里没有 .app')
            target = staging / 'CaiXiHui.app'
            if target.exists():
                shutil.rmtree(target)
            subprocess.run(
                ['ditto', str(bundles[0]), str(target)],
                check=True,
                timeout=600,
                **procs.popen_kwargs(),
            )
            return target
        finally:
            subprocess.run(
                ['hdiutil', 'detach', str(mount)],
                check=False,
                capture_output=True,
                timeout=60,
                **procs.popen_kwargs(),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'展开 macOS 安装包失败：{exc}') from exc


def _run_download(version: str, asset: dict) -> None:
    root = updates_root() / re.sub(r'[^0-9A-Za-z._-]+', '_', version)
    try:
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        package = root / ('package.dmg' if machine.platform_name() == 'darwin' else 'package.zip')
        _set_job(state='downloading', progress=0, error='')
        _download_package(asset, package)
        _set_job(state='staging', progress=96)
        if machine.platform_name() == 'darwin':
            staged = _stage_macos(package, root / 'staged')
        else:
            staged = root / 'staged'
            safe_extract(package, staged, archive_type='zip', strip_prefix='CaiXiHui')
        _set_job(state='done', progress=100, staged=str(staged), version=version)
    except (ArchiveError, OSError, RuntimeError, ValueError) as exc:
        _fail(str(exc))


def start_download() -> dict:
    if not _frozen():
        return {'ok': False, 'error': '源码运行不执行自更新'}
    feed = fetch_feed()
    if feed is None:
        with _JOB_LOCK:
            return {'ok': False, 'error': _FEED_CACHE['error'] or '无法读取更新清单'}
    latest = str(feed.get('version') or '').strip()
    asset = _asset(feed)
    if not asset:
        return {'ok': False, 'error': f'发行清单里没有 {_platform_key()} 的安装包'}
    with _JOB_LOCK:
        if _JOB.get('state') in ('downloading', 'staging'):
            return {'ok': True, 'job': dict(_JOB)}
        _JOB.clear()
        _JOB.update({'id': uuid.uuid4().hex, 'state': 'downloading', 'progress': 0, 'error': '', 'version': latest})
        job = dict(_JOB)
    threading.Thread(
        target=_run_download,
        args=(latest, asset),
        name='update-download',
        daemon=True,
    ).start()
    return {'ok': True, 'job': job}


def job(job_id: str = '') -> dict:
    with _JOB_LOCK:
        current = dict(_JOB)
    if job_id and current.get('id') != job_id:
        return {}
    return current


_WINDOWS_SCRIPT = r"""
param([int]$AppPid,[string]$InstallRoot,[string]$Staged,[string]$Exe,[string]$Mode)
$ErrorActionPreference = 'Stop'
try { Wait-Process -Id $AppPid -Timeout 180 -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Milliseconds 900
$targetRoot = if ($Mode -eq 'app') { Join-Path $InstallRoot 'app' } else { $InstallRoot }
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
$previous = Join-Path $InstallRoot 'app.previous'
if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force }
New-Item -ItemType Directory -Force -Path $previous | Out-Null
$preserve = @('Data','data','logs','mplconfig','components','install-manifest.json',
  'bert_models','portable.txt','data-root.txt','instance.json','webview-profile',
  'drivers','updates','app.previous')
$moved = @()
$added = @()
try {
  Get-ChildItem -LiteralPath $Staged -Force | ForEach-Object {
    if ($preserve -contains $_.Name) { return }
    $old = Join-Path $targetRoot $_.Name
    if (Test-Path -LiteralPath $old) {
      Move-Item -LiteralPath $old -Destination (Join-Path $previous $_.Name) -Force
      $moved += $_.Name
    }
    Copy-Item -LiteralPath $_.FullName -Destination $old -Recurse -Force
    $added += $_.Name
  }
  Start-Process -FilePath $Exe
} catch {
  foreach ($name in $added) {
    $target = Join-Path $targetRoot $name
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
  }
  foreach ($name in $moved) {
    $backup = Join-Path $previous $name
    $target = Join-Path $targetRoot $name
    if (Test-Path -LiteralPath $backup) {
      if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
      Move-Item -LiteralPath $backup -Destination $target -Force
    }
  }
  Start-Process -FilePath $Exe
  exit 1
}
"""

_MACOS_SCRIPT = """#!/bin/bash
set -u
PID="$1"
APP="$2"
STAGED="$3"
while kill -0 "$PID" 2>/dev/null; do sleep 0.5; done
sleep 0.8
rm -rf "$APP.previous"
mv "$APP" "$APP.previous"
if ditto "$STAGED" "$APP"; then
  open "$APP"
else
  rm -rf "$APP"
  mv "$APP.previous" "$APP"
  open "$APP"
  exit 1
fi
"""


def _spawn_script(script: Path, args: list[str]) -> None:
    if machine.platform_name() == 'win32':
        subprocess.Popen(
            procs.powershell_command(str(script), args),
            close_fds=True,
            **procs.popen_kwargs(detached=True),
        )
    else:
        subprocess.Popen(
            ['/bin/bash', str(script), *args],
            close_fds=True,
            start_new_session=True,
            **procs.popen_kwargs(),
        )


def _writable(path: Path) -> bool:
    try:
        probe = path / '.update-write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        return True
    except OSError:
        return False


def apply_update() -> dict:
    with _JOB_LOCK:
        current = dict(_JOB)
    if current.get('state') != 'done' or not current.get('staged'):
        return {'ok': False, 'error': '更新包还没有下载完成'}
    mode, root, exe = install_layout()
    if not root or not exe.exists():
        return {'ok': False, 'error': '无法定位当前安装目录'}
    if not _writable(root) or (mode == 'app' and not _writable(root / 'app')):
        return {'ok': False, 'error': '安装目录不可写；请用安装器更新，或把程序放到有写权限的文件夹'}
    staged = Path(str(current['staged']))
    version = str(current.get('version') or 'new')
    script_dir = updates_root() / re.sub(r'[^0-9A-Za-z._-]+', '_', version)
    script_dir.mkdir(parents=True, exist_ok=True)
    if machine.platform_name() == 'win32':
        script = script_dir / 'apply.ps1'
        script.write_text(_WINDOWS_SCRIPT, encoding='utf-8')
        _spawn_script(
            script,
            [
                '-AppPid',
                str(os.getpid()),
                '-InstallRoot',
                str(root),
                '-Staged',
                str(staged),
                '-Exe',
                str(exe),
                '-Mode',
                mode,
            ],
        )
    elif mode == 'macapp':
        script = script_dir / 'apply.sh'
        script.write_text(_MACOS_SCRIPT, encoding='utf-8')
        script.chmod(0o755)
        _spawn_script(script, [str(os.getpid()), str(root), str(staged)])
    else:
        return {'ok': False, 'error': '当前平台不支持自更新'}
    return {'ok': True, 'restarting': True}
