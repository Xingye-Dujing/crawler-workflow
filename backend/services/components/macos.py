"""macOS-native extraction for installer payloads.

The shared :func:`services.components.archive.safe_extract` is deliberately portable and refuses
symlinks and permission bits it cannot represent. That is the right answer for a Windows zip, and
the wrong one for a Mac payload: Chrome for Testing is an ``.app`` full of framework symlinks, Node's
tarball puts ``bin/npm`` behind a link, and an executable without its ``+x`` bit cannot start. So a
macOS install unpacks with the system's own ``ditto``/``tar``, which preserve all three.

The bytes being unpacked are already pinned by SHA-256 in the catalogue, so the system tool is not
trusted with something the installer did not verify first. Extraction still happens into a staging
directory; the caller moves the result into place atomically.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from core.procs import popen_kwargs

from services.components.archive import ArchiveError

DITTO = '/usr/bin/ditto'
TAR = '/usr/bin/tar'
_SCRATCH = '.native-extract'


def extract_command(archive: str | Path, destination: str | Path, archive_type: str) -> list[str]:
    """The system command that unpacks one archive, as argv (pure, so a test can pin it)."""
    source = str(archive)
    target = str(destination)
    if archive_type == 'zip':
        # ``-x -k`` is ditto's "extract a PKZip archive"; resources and symlinks are preserved.
        return [DITTO, '-x', '-k', source, target]
    if archive_type == 'tar.gz':
        return [TAR, '-xzf', source, '-C', target]
    raise ArchiveError(f'unsupported archive type {archive_type!r} for macOS extraction')


def _run(command: list[str], source: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False, **popen_kwargs())
    if result.returncode == 0:
        return
    lines = (result.stderr or result.stdout or '').strip().splitlines()
    reason = lines[-1] if lines else f'exit {result.returncode}'
    raise ArchiveError(f'cannot extract {source}: {reason}')


def extract_native(
    archive: str | Path,
    target: str | Path,
    *,
    archive_type: str = 'zip',
    strip_prefix: str = '',
) -> Path:
    """Extract with ``ditto``/``tar``, then copy the stripped payload into ``target``."""
    source = Path(archive)
    destination = Path(target)
    scratch = destination.parent / f'.{destination.name}-macos'
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        _run(extract_command(source, scratch, archive_type), source.name)
        payload = scratch / strip_prefix if strip_prefix else scratch
        if strip_prefix and not payload.is_dir():
            raise ArchiveError(f'the archive does not contain {strip_prefix}')
        destination.mkdir(parents=True, exist_ok=True)
        # ditto (not shutil.move) so symlinks, executable bits and extended attributes survive the
        # second hop into the caller's staging directory.
        _run([DITTO, str(payload), str(destination)], source.name)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return destination
