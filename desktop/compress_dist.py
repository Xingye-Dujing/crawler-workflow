"""Compress the packaged binaries with UPX, and say loudly when it did not happen.

PyInstaller can do this itself (``upx=True``), and this project used to let it. Measured reason
not to: PyInstaller searches for ``upx`` on its own terms and **silently skips every file when it
cannot find one**, so a build on a machine without UPX on PATH produces a folder that looks like a
compressed one. Here a missing ``upx`` is a named failure, each compressed file is verified with
``upx -t``, and the byte delta is printed.

Scope is deliberately the same as PyInstaller's: the bootloader exe plus the PE files inside
``_internal``. ``*.onnx``, dictionaries and marshals are DATA — UPX only compresses executables,
which is why the BERT model pack shrinks through quantisation and the archive, not through here.

Usage: python compress_dist.py <dist/CaiXiHui>
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

#: Never packed: the runtime the bootloader itself needs to start, and the Windows API
#: shims. A compressed ``python311.dll`` is a window that closes before it prints anything.
UNCHANGED_NAMES = (
    'python311.dll',
    'python3.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
    'msvcp140.dll',
    'ucrtbase.dll',
)
UNCHANGED_PREFIXES = ('api-ms-win-', 'ext-ms-win-')

#: Extensions worth compressing. ``.dll``/``.pyd``/``.exe`` are the PE files PyInstaller collects.
PE_SUFFIXES = ('.dll', '.pyd', '.exe')

#: ``--no-version-info`` is not an option UPX 5.0.2 accepts (measured: it exits 1 with
#: "unrecognized option"), which is exactly the silent no-op this module exists to avoid.
UPX_ARGS = ['--best', '--force']

#: ``--best`` on the 20 MB OpenBLAS DLL measured 30 s on this machine, and the folder holds 307
#: PE files (6 of them over 5 MB). Sequentially that is a ten-minute tail on the build; the
#: workers are separate processes, so the 24 cores this box has are otherwise idle.
WORKERS = 8


def is_unchanged(path: Path) -> bool:
    name = path.name.lower()
    return name in UNCHANGED_NAMES or name.startswith(UNCHANGED_PREFIXES)


def already_packed(path: Path) -> bool:
    """True when UPX put its own marker in the header.

    Running UPX over an already-compressed file either fails or produces a bigger file, and the
    build script may be re-run over a folder that is already packed. ``--force`` would happily
    overwrite, so the marker is checked instead.
    """
    try:
        with path.open('rb') as handle:
            return b'UPX!' in handle.read(4096)
    except OSError:
        return False


def pe_targets(dist: Path) -> list[Path]:
    """Every PE file this pass owns: the exe beside the folder, plus everything in ``_internal``."""
    targets = [path for path in (dist / 'CaiXiHui.exe',) if path.is_file()]
    internal = dist / '_internal'
    if internal.is_dir():
        targets.extend(path for path in internal.rglob('*') if path.is_file() and path.suffix.lower() in PE_SUFFIXES)
    return [path for path in targets if not is_unchanged(path)]


def _run(upx: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([upx, *args], capture_output=True, text=True, check=False)


def _drop_stale_backups(dist: Path) -> int:
    """Remove ``*.upxbackup`` a previous interrupted run left behind.

    The only way one of those survives here is a build that was killed mid-file, and the packed
    binary beside it is the one that loads. Shipping it in the zip would just be a mystery file.
    """
    stale = list(Path(dist).rglob('*.upxbackup'))
    for path in stale:
        with contextlib.suppress(OSError):
            path.unlink()
    return len(stale)


def _compress_one(upx: str, target: Path) -> tuple:
    """Pack one binary. Returns ``(kind, path, before, after, reason)``."""
    original = target.stat().st_size
    if already_packed(target):
        return ('skipped', str(target), original, original, 'already packed')
    backup = target.with_suffix(target.suffix + '.upxbackup')
    shutil.copy2(target, backup)
    result = _run(upx, [*UPX_ARGS, str(target)])
    packed = target.stat().st_size if target.is_file() else 0
    verified = _run(upx, ['-t', str(target)])
    if result.returncode != 0 or verified.returncode != 0 or packed <= 0 or packed >= original:
        reason = (result.stderr or verified.stderr or result.stdout or '').strip()[:200]
        # ``python3.dll`` answers ``NotCompressibleException``: it is a 100 KB forwarder with nothing
        # in it worth packing, and UPX declining a file is not the same event as a file that packed
        # and then failed verification. Keep the original either way; only the second one is a reason
        # to stop a release, because failing on the first would make every build red for no change.
        if 'NotCompressibleException' in reason:
            # Restore from the backup rather than trusting the file in place: UPX writes its output
            # to the same path, so a refusal that happens mid-write leaves a truncated DLL behind —
            # and a broken python3.dll is a window that closes before it prints anything.
            target.unlink(missing_ok=True)
            shutil.move(str(backup), str(target))
            return ('skipped', str(target), original, original, f'UPX 拒绝该文件，保留原样：{reason}')
        # A half-packed binary is the flash-quit bug class again, only found by the user: restore.
        target.unlink(missing_ok=True)
        shutil.move(str(backup), str(target))
        return ('failed', str(target), original, original, reason or f'exit {result.returncode}')
    backup.unlink(missing_ok=True)
    return ('compressed', str(target), original, packed, '')


def compress(dist: Path, *, upx_path: str | None = None, workers: int = WORKERS) -> dict:
    """Pack every target in ``dist``; nothing is reported as compressed that was not verified."""
    upx = upx_path or shutil.which('upx') or ''
    ledger = {'upx': upx, 'compressed': [], 'skipped': [], 'failed': [], 'before': 0, 'after': 0}
    stale = _drop_stale_backups(dist)
    if stale:
        print(f'清理上次中断留下的备份文件：{stale} 个')
    if not upx:
        ledger['failed'].append(('upx', 0, 'upx is not on PATH — install it or pass the path; nothing was compressed'))
        return ledger
    targets = pe_targets(Path(dist))
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(targets) or 1))) as pool:
        for kind, path, before, after, reason in pool.map(lambda item: _compress_one(upx, item), targets):
            ledger['before'] += before
            ledger['after'] += after
            if kind == 'compressed':
                ledger['compressed'].append((path, before, after))
            elif kind == 'skipped':
                ledger['skipped'].append((path, before, reason))
            else:
                ledger['failed'].append((path, before, reason))
    return ledger


def report(ledger: dict) -> None:
    """One line per outcome, and the totals the release notes quote."""
    if not ledger['upx']:
        print(f'UPX 压缩未能开始：{ledger["failed"][0][2] if ledger["failed"] else "未知原因"}')
        return
    mb = 1024 * 1024
    for path, size, why in ledger['skipped']:
        print(f'跳过（{why}）：{path} {size / mb:.1f} MB')
    for path, size, why in ledger['failed']:
        print(f'未能压缩，已还原原文件：{path}（{size / mb:.1f} MB）原因：{why}')
    for path, before, after in ledger['compressed']:
        print(f'压缩：{path} {before / mb:.1f} → {after / mb:.1f} MB')
    print(
        f'UPX：{len(ledger["compressed"])} 个文件，'
        f'{ledger["before"] / mb:.1f} → {ledger["after"] / mb:.1f} MB，'
        f'省下 {(ledger["before"] - ledger["after"]) / mb:.1f} MB；'
        f'跳过 {len(ledger["skipped"])}，失败 {len(ledger["failed"])}'
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('usage: python compress_dist.py <dist/CaiXiHui>', file=sys.stderr)
        return 2
    dist = Path(argv[1])
    if not (dist / '_internal').is_dir():
        print(f'not an onedir build: {dist}', file=sys.stderr)
        return 2
    ledger = compress(dist)
    report(ledger)
    if not ledger['upx'] or ledger['failed']:
        # A missing UPX or a rejected binary is reported as a build failure: the alternative is a
        # deliverable whose size — and whose "we compressed it" claim — is a guess.
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
