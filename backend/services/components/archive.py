"""Unpacking an archive without letting it write outside the directory it was given.

An installer extracts bytes downloaded from the internet, so the archive is data and not a command:
a name with ``..``, an absolute path, a symlink or a Windows drive letter is refused by name. Limits
on entry count and total size turn a decompression bomb into an error instead of a full disk.

``strip_prefix`` removes the one top-level folder a release zip normally has (``chrome-win64/``),
so the caller controls where the payload lands rather than depending on archive layout.
"""

from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

MAX_ENTRIES = 200_000
MAX_FILE_BYTES = 16 * 1024**3
MAX_TOTAL_BYTES = 24 * 1024**3
_SYMLINK_MODE = 0o120000


class ArchiveError(Exception):
    """An archive that is unsafe or unreadable, with the entry that caused it."""


def _relative(name: str) -> str:
    """A normalized POSIX name, or a refusal naming the unsafe part."""
    cleaned = str(name or '').replace('\\', '/')
    if not cleaned:
        raise ArchiveError('empty archive entry name')
    path = PurePosixPath(cleaned)
    if path.is_absolute() or (len(cleaned) > 1 and cleaned[1] == ':'):
        raise ArchiveError(f'absolute path in archive: {name}')
    if any(part == '..' for part in path.parts):
        raise ArchiveError(f'parent traversal in archive: {name}')
    return path.as_posix()


def _strip(name: str, prefix: str) -> str | None:
    if not prefix:
        return name
    if name == prefix:
        return None
    head = prefix.rstrip('/') + '/'
    if not name.startswith(head):
        raise ArchiveError(f'archive entry {name} is outside the expected folder {prefix}')
    return name[len(head) :]


def safe_extract(
    archive: str | Path,
    target: str | Path,
    *,
    archive_type: str = 'zip',
    strip_prefix: str = '',
) -> Path:
    """Extract ``archive`` into ``target`` (created if needed) and return it."""
    source = Path(archive)
    destination = Path(target)
    destination.mkdir(parents=True, exist_ok=True)
    if archive_type == 'zip':
        _extract_zip(source, destination, strip_prefix)
    elif archive_type == 'tar.gz':
        _extract_tar(source, destination, strip_prefix)
    else:
        raise ArchiveError(f'unsupported archive type {archive_type!r}')
    return destination


def _extract_zip(source: Path, destination: Path, strip_prefix: str) -> None:
    try:
        handle = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveError(f'cannot open zip {source.name}: {exc}') from exc
    with handle:
        entries = handle.infolist()
        if len(entries) > MAX_ENTRIES:
            raise ArchiveError(f'{source.name} has too many entries ({len(entries)})')
        total = 0
        for info in entries:
            name = _relative(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == _SYMLINK_MODE:
                raise ArchiveError(f'symlink in archive: {info.filename}')
            if info.is_dir():
                continue
            stripped = _strip(name, strip_prefix)
            if stripped is None or not stripped:
                continue
            total += info.file_size
            if info.file_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise ArchiveError(f'{source.name} expands beyond the size limit')
            target = _target(destination, stripped)
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(info) as reader, open(target, 'wb') as writer:
                shutil.copyfileobj(reader, writer, 1024 * 1024)


def _extract_tar(source: Path, destination: Path, strip_prefix: str) -> None:
    try:
        with tarfile.open(source, 'r:gz') as handle:
            _extract_tar_members(handle, source, destination, strip_prefix)
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveError(f'cannot open tar.gz {source.name}: {exc}') from exc


def _extract_tar_members(handle: tarfile.TarFile, source: Path, destination: Path, strip_prefix: str) -> None:
    members = handle.getmembers()
    if len(members) > MAX_ENTRIES:
        raise ArchiveError(f'{source.name} has too many entries ({len(members)})')
    total = 0
    for member in members:
        name = _relative(member.name)
        if member.issym() or member.islnk():
            raise ArchiveError(f'link in archive: {member.name}')
        if member.isdir():
            continue
        if not member.isfile():
            raise ArchiveError(f'unsupported entry in archive: {member.name}')
        stripped = _strip(name, strip_prefix)
        if stripped is None or not stripped:
            continue
        total += member.size
        if member.size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ArchiveError(f'{source.name} expands beyond the size limit')
        target = _target(destination, stripped)
        target.parent.mkdir(parents=True, exist_ok=True)
        reader = handle.extractfile(member)
        if reader is None:
            raise ArchiveError(f'cannot read archive entry: {member.name}')
        with reader, open(target, 'wb') as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)


def _target(destination: Path, name: str) -> Path:
    path = destination / PurePosixPath(name)
    resolved = path.resolve()
    root = destination.resolve()
    if root != resolved and root not in resolved.parents:
        raise ArchiveError(f'entry escapes the target directory: {name}')
    return path
