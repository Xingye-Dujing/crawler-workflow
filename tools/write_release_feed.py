"""Write ``version.json`` from the bytes actually published, never from a copied number.

The manifest is the one file every installed client reads, and its three claims per platform — the
URL, the byte count and the SHA-256 — must describe the files that are really on the release. Two of
those numbers cannot be typed by hand:

* **Windows** is read from ``dist/`` after the shards were written by ``tools/publish_gitee.py``,
  and the parts must add up to the archive (a mismatch means a stale split, which would install a
  truncated zip).
* **macOS** is read back from the GitHub release's asset list, because those DMGs were built on a
  runner this checkout never saw, and the release API reports their digest.

A feed is refused while a platform it claims has no published asset: a manifest naming a download
nobody can fetch makes every client prompt for an update it cannot install. A Windows-only release
must therefore be written with ``--windows-only``, which drops the ``darwin-*`` entries on purpose —
leaving them would send Mac clients to the PREVIOUS DMG while their version says otherwise.

    python tools/write_release_feed.py 2026.11.19.1 exe-2026-11-19.1 --notes-file scratchpad/notes.md
    python tools/write_release_feed.py 2026.11.19.1 exe-2026-11-19.1 --notes-file ... --windows-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
FEED = ROOT / 'version.json'
REPO = 'Xingye-Dujing/crawler-workflow'
GITEE = 'https://gitee.com/Xingye-Dujing/crawler-workflow/releases/download'
GITHUB = f'https://github.com/{REPO}/releases/download'

#: The feed's own version grammar (``services/update._VERSION_RE`` accepts the same shape).
VERSION_RE = re.compile(r'^\d+(\.\d+){2,3}$')

#: Platform key → the architecture word in the DMG file name built by the macOS workflow.
MAC_ARCHS = {'darwin-arm64': 'arm64', 'darwin-x64': 'x86_64'}


# ─── Bytes ───


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def released_date(version: str) -> str:
    """``2026.11.19.1`` → ``2026-11-19``: the build number is not a day."""
    parts = version.split('.')
    day, month, year = parts[2], parts[1], parts[0]
    return f'{year}-{month}-{day}'


# ─── The two platform shapes ───


def windows_entry(tag: str, archive: Path, parts: list[Path]) -> dict:
    """The Win32 entry: the whole archive's digest plus the shards the domestic download page needs.

    Gitee caps one attachment at 100 MB, so ``parts`` is what most users actually download; the
    archive's own digest lets the online installer check the joined file.
    """
    if not archive.exists():
        raise SystemExit(f'{archive} is missing: build before writing the feed')
    entries = []
    for part in parts:
        if not part.exists():
            raise SystemExit(f'{part} is missing: shard before writing the feed')
        entries.append({'url': f'{GITEE}/{tag}/{part.name}', 'sha256': sha256(part), 'size': part.stat().st_size})
    total = sum(entry['size'] for entry in entries)
    if entries and total != archive.stat().st_size:
        raise SystemExit(
            f'the shards add up to {total} bytes but {archive.name} is {archive.stat().st_size}: '
            'they describe a different build'
        )
    return {
        'archive': 'zip',
        'sha256': sha256(archive),
        'size': archive.stat().st_size,
        'parts': entries,
    }


def mac_entry(tag: str, platform: str, published: dict) -> dict:
    """One macOS DMG, described by what the release API says was uploaded."""
    name = f'CaiXiHui-macOS-{MAC_ARCHS[platform]}.dmg'
    asset = published.get(name)
    if not asset:
        raise SystemExit(f'{name} is not on the {tag} release yet: run the macOS workflow first')
    digest = str(asset.get('digest') or '').removeprefix('sha256:').lower()
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        # The release API reports a digest for every uploaded asset; its absence means we would be
        # publishing an UNVERIFIED download, which the client refuses anyway.
        raise SystemExit(f'{name} has no sha256 digest in the release API: {asset.get("digest")!r}')
    return {'archive': 'dmg', 'url': f'{GITHUB}/{tag}/{name}', 'sha256': digest, 'size': int(asset.get('size') or 0)}


def feed_document(version: str, notes: str, platforms: dict) -> dict:
    if not VERSION_RE.match(version):
        raise SystemExit(f'{version!r} is not a version (three or four numeric groups)')
    if not str(notes or '').strip():
        raise SystemExit('a feed without notes shows an empty update card: pass --notes or --notes-file')
    if not platforms:
        raise SystemExit('a feed with no platform is not downloadable')
    return {
        'schema': 1,
        'version': version,
        'released': released_date(version),
        'notes': notes.strip(),
        'platforms': platforms,
    }


# ─── Where the numbers come from ───


def release_assets(tag: str, repo: str = REPO) -> dict:
    """The published asset list, from the release API (name → {size, digest})."""
    out = subprocess.run(
        ['gh', 'release', 'view', tag, '--repo', repo, '--json', 'assets'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=120,
        check=False,
    )
    if out.returncode != 0:
        raise SystemExit(f'reading the {tag} release failed: {out.stderr.strip()[:400]}')
    return {str(asset.get('name') or ''): asset for asset in json.loads(out.stdout or '{}').get('assets') or []}


def windows_shards(dist: Path = DIST) -> list[Path]:
    """Every shard publish_gitee.py actually wrote, in index order.

    Hard-coding ``(1, 2)`` broke the feed the moment a build grew past two shards: extra shards
    were published but omitted, and windows_entry then refused the whole feed because the listed
    bytes no longer added up to the archive.
    """
    archive_name = 'CaiXiHui-win64.zip'
    shards = []
    for path in dist.glob(f'{archive_name}.*'):
        suffix = path.name[len(archive_name) + 1 :]
        if suffix.isdigit():
            shards.append((int(suffix), path))
    return [path for _index, path in sorted(shards)]


def build_feed(version: str, tag: str, *, notes: str, windows_only: bool, dist: Path = DIST) -> dict:
    platforms = {
        'win32': windows_entry(
            tag,
            dist / 'CaiXiHui-win64.zip',
            windows_shards(dist),
        )
    }
    if not windows_only:
        published = release_assets(tag)
        for platform in MAC_ARCHS:
            platforms[platform] = mac_entry(tag, platform, published)
    return feed_document(version, notes, platforms)


def notes_from(args) -> str:
    if args.notes_file:
        return Path(args.notes_file).read_text(encoding='utf-8')
    return str(args.notes or '')


def write_feed(version: str, tag: str, *, notes: str, windows_only: bool, feed: Path = FEED, dist: Path = DIST) -> dict:
    document = build_feed(version, tag, notes=notes, windows_only=windows_only, dist=dist)
    feed.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Write version.json from the bytes actually published.')
    parser.add_argument('version', help='the release version (2026.11.19.1), the same one APP_VERSION carries')
    parser.add_argument('tag', help='the release tag the assets were uploaded to (exe-2026-11-19.1)')
    parser.add_argument('--notes', default='', help='the sentence(s) the update card shows')
    parser.add_argument('--notes-file', default='', help='a markdown file with the same text')
    parser.add_argument('--windows-only', action='store_true', help='drop the darwin-* entries on purpose')
    args = parser.parse_args(argv)
    document = write_feed(
        args.version, args.tag, notes=notes_from(args), windows_only=args.windows_only, feed=FEED, dist=DIST
    )
    print(f'wrote {FEED} for {document["version"]} ({", ".join(document["platforms"])})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
