"""Digests for the FINAL signed release artifacts, written only after the last signature lands.

A signature changes the bytes of the PE it is added to, and UPX changes them again. So the
manifest is the last stage of the release chain, never a by-product of the compile job:

    build (no credentials) -> sign exe -> Inno Setup embeds the signed bytes -> sign Setup.exe
    -> SHA256SUMS + release-manifest.json

``SHA256SUMS`` is the ordinary ``sha256sum`` shape (hex, two spaces, relative name) so a
downloader or a shell can check it without our tooling. The JSON manifest adds sizes and a
catalog hint: those are the exact numbers ``tools/release_components.py`` needs for the
online installer's ``app`` entry after a signed rebuild.

    .venv/Scripts/python.exe desktop/release_manifest.py --dist dist --version 1.0.0
    .venv/Scripts/python.exe desktop/release_manifest.py --dist dist --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / 'dist'

#: These must be the already-signed bytes. Naming them is the refusal: a build that skipped
#: the installer, or a zip made before signing, cannot quietly produce a "complete" manifest.
REQUIRED = (
    'CaiXiHui/CaiXiHui.exe',
    'CaiXiHui-win64.zip',
    'CaiXiHui-Setup.exe',
)
OPTIONAL = ('CaiXiHui-Online-Setup.exe',)
APP_ARCHIVE = 'CaiXiHui-win64.zip'
SUMS_NAME = 'SHA256SUMS'
MANIFEST_NAME = 'release-manifest.json'


class ReleaseError(Exception):
    """A named release-stage refusal; the caller prints the reason and exits non-zero."""


def sha256_file(path: Path) -> str:
    """Stream the digest; a 150 MB zip must not be read into memory."""
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def artifact_names(dist: Path) -> tuple[str, ...]:
    """The release files that exist, with the optional online installer included when present."""
    names = [name for name in REQUIRED if (dist / name).is_file()]
    names += [name for name in OPTIONAL if (dist / name).is_file()]
    return tuple(sorted(names))


def collect(dist: Path) -> dict[str, dict[str, object]]:
    """Hash every release file; refuse, by name, any required artifact that is absent."""
    missing = [name for name in REQUIRED if not (dist / name).is_file()]
    if missing:
        raise ReleaseError('missing signed artifacts: ' + ', '.join(missing))
    return {
        name: {'sha256': sha256_file(dist / name), 'size': (dist / name).stat().st_size}
        for name in artifact_names(dist)
    }


def manifest_payload(
    version: str, channel: str, artifacts: dict[str, dict[str, object]], *, generated_at: str = ''
) -> dict[str, object]:
    """One answer for the publisher: what shipped, at which version, with which digests."""
    return {
        'schema': 1,
        'app': 'CaiXiHui',
        'version': version,
        'channel': channel,
        'generated_at': generated_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'artifacts': artifacts,
        'catalog_hint': {
            'component': 'app',
            'platform': 'win32',
            'file': APP_ARCHIVE,
            'sha256': artifacts[APP_ARCHIVE]['sha256'],
            'size': artifacts[APP_ARCHIVE]['size'],
        },
    }


def sums_text(artifacts: dict[str, dict[str, object]]) -> str:
    """Two spaces, relative POSIX-style names: what ``sha256sum -c`` expects."""
    return ''.join(f'{values["sha256"]}  {name}\n' for name, values in sorted(artifacts.items()))


def write_atomic(path: Path, data: bytes) -> None:
    """A reader sees either the old file or the whole new one, never a half-written digest."""
    partial = path.with_name(path.name + '.partial')
    partial.write_bytes(data)
    os.replace(partial, path)


def write_release(dist: Path, version: str, channel: str) -> dict[str, object]:
    """Write both records from the same set of bytes, so they cannot disagree."""
    artifacts = collect(dist)
    payload = manifest_payload(version, channel, artifacts)
    write_atomic(dist / SUMS_NAME, sums_text(artifacts).encode('ascii'))
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    write_atomic(dist / MANIFEST_NAME, encoded.encode('utf-8'))
    return payload


def verify(dist: Path, payload: dict[str, object]) -> list[str]:
    """Re-hash the files on disk; return every disagreement as a named reason."""
    problems: list[str] = []
    declared = payload.get('artifacts')
    if not isinstance(declared, dict):
        return ['release-manifest.json has no artifacts object']
    for name, values in sorted(declared.items()):
        path = dist / str(name)
        if not path.is_file():
            problems.append(f'{name}: missing')
            continue
        if not isinstance(values, dict):
            problems.append(f'{name}: malformed entry')
            continue
        actual = sha256_file(path)
        if values.get('sha256') != actual:
            problems.append(f'{name}: sha256 is not the file on disk')
        if values.get('size') != path.stat().st_size:
            problems.append(f'{name}: size is not the file on disk')
    for name in REQUIRED:
        if name not in declared:
            problems.append(f'{name}: absent from the manifest')
    return problems


def main(argv: list[str] | None = None) -> int:
    """Write the manifest, or (--check) prove the recorded digests still match the bytes."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', default=str(DEFAULT_DIST))
    parser.add_argument('--version', default='')
    parser.add_argument('--channel', default='stable')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    dist = Path(args.dist)

    try:
        if args.check:
            holder = dist / MANIFEST_NAME
            payload = json.loads(holder.read_text(encoding='utf-8'))
            problems = verify(dist, payload)
            if problems:
                raise ReleaseError('; '.join(problems))
            print(f'verified {len(payload.get("artifacts") or {})} signed artifacts in {dist}')
            return 0
        if not args.version:
            raise ReleaseError('--version is required when writing a manifest')
        payload = write_release(dist, args.version, args.channel)
    except (ReleaseError, OSError, ValueError) as error:
        print(f'release manifest refused: {error}', file=sys.stderr)
        return 1

    hint = payload['catalog_hint']
    print(f'wrote {dist / SUMS_NAME} and {dist / MANIFEST_NAME}')
    if isinstance(hint, dict):
        print(f'app catalog: sha256={hint.get("sha256")} size={hint.get("size")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
