"""Publish one release's Windows artifacts to Gitee: split, free room, create, upload.

Gitee caps a repository's release attachments at 1 GB and a single attachment at 100 MB, so a
release is a sequence of steps that only work in one order, and every one of them was learned the
hard way:

1. **Split at 99,614,720 B.** The feed's ``parts`` name these bytes; a part is rewritten even when
   its size already matches, because two builds of the same archive have the same first-shard length
   and different bytes — reusing one publishes a digest nobody can download.
2. **Create the release entry before pruning.** ``prune_gitee_releases`` refuses to run while a tag
   it is told to keep has no release (its guard against a typo emptying the repository), and the tag
   being published is one of the kept ones.
3. **Prune** — delete every attachment outside the kept tags, so the 1 GB budget has room.
4. **Upload** the shards and the online installer, skipping a name already attached.

The token is read from ``GITEE_TOKEN`` only: argv is world-readable. Gitee's v5 write endpoints want
it as a *form field* together with ``owner``/``repo``; a path-only request answers
400 “验证失败，所有参数不能为空”.

    set GITEE_TOKEN=...
    python tools/publish_gitee.py exe-2026-11-19.1 --keep manual-2026-11 --dry-run
    python tools/publish_gitee.py exe-2026-11-19.1 --keep manual-2026-11
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
API = 'https://gitee.com/api/v5/repos'
DEFAULT_REPO = 'Xingye-Dujing/crawler-workflow'

#: Gitee's attachment limit is 100 MB; the split point the feed documents is just under it.
SHARD_BYTES = 99_614_720

#: Long enough for a 95 MB part on a slow uplink, short enough to fail a dead socket.
UPLOAD_TIMEOUT = 600

#: Archives the feed serves as ``parts`` and the installer that installs nothing itself (it reads
#: ``version.json`` at install time, so the same bytes serve every later release).
ARCHIVES = ('CaiXiHui-win64.zip', 'CaiXiHui-Setup.exe')
STANDALONE = ('CaiXiHui-Online-Setup.exe',)


# ─── Bytes ───


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def shard_plan(size: int, shard: int = SHARD_BYTES) -> list[tuple[int, int]]:
    """``(offset, length)`` per part; an exact multiple must not gain an empty tail part."""
    if size <= 0:
        raise ValueError('an archive of zero bytes cannot be published')
    if shard <= 0:
        raise ValueError('the shard size must be positive')
    return [(offset, min(shard, size - offset)) for offset in range(0, size, shard)]


def write_shards(path: Path, shard: int = SHARD_BYTES, *, dry_run: bool = False) -> list[Path]:
    """Cut *path* into ``<name>.001``… and return them in feed order.

    A part is ALWAYS rewritten: the size check this used to make ("already correct") let a rebuilt
    archive keep the previous build's first part, whose length matches and whose bytes do not.
    """
    plan = shard_plan(path.stat().st_size, shard)
    parts: list[Path] = []
    for index, (offset, length) in enumerate(plan, start=1):
        target = path.with_name(f'{path.name}.{index:03d}')
        parts.append(target)
        if dry_run:
            print(f'  would write {target.name} ({length} B)')
            continue
        with path.open('rb') as source, target.open('wb') as sink:
            source.seek(offset)
            remaining = length
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise SystemExit(f'{path.name} ended early at {offset + length - remaining}')
                sink.write(block)
                remaining -= len(block)
        print(f'  + {target.name} ({length} B) sha256={sha256(target)}')
    return parts


# ─── Gitee ───


def token_from_env() -> str:
    token = str(os.environ.get('GITEE_TOKEN') or '').strip()
    if not token:
        raise SystemExit('GITEE_TOKEN is not set: export a Gitee personal token with the projects scope')
    return token


def _read_headers(token: str) -> dict:
    """Reads accept the token as a header; writes do not (see ``_form``)."""
    return {'Authorization': f'token {token}'}


def _form(repo: str, token: str) -> dict:
    """What a v5 WRITE endpoint needs: the token, and the owner/repo the path already names."""
    owner, name = repo.split('/', 1)
    return {'access_token': token, 'owner': owner, 'repo': name}


def list_releases(repo: str, token: str) -> list[dict]:
    found: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            f'{API}/{repo}/releases',
            headers=_read_headers(token),
            params={'page': page, 'per_page': 100, 'direction': 'desc'},
            timeout=60,
        )
        if resp.status_code >= 300:
            raise SystemExit(f'listing releases failed: HTTP {resp.status_code} {resp.text[:300]}')
        batch = resp.json() or []
        found.extend(batch)
        if len(batch) < 100:
            return found
        page += 1


def release_notes(tag: str) -> str:
    """The same markdown GitHub got, if the release run left it in ``scratchpad/``."""
    candidate = ROOT / 'scratchpad' / f'release_notes_{tag.removeprefix("exe-")}.md'
    return candidate.read_text(encoding='utf-8') if candidate.exists() else ''


def ensure_release(repo: str, token: str, tag: str, *, body: str = '', dry_run: bool = False) -> int:
    """The release id for *tag*, creating the entry when it is missing."""
    for release in list_releases(repo, token):
        if str(release.get('tag_name') or '') == tag:
            print(f'release {tag} already exists (id {release["id"]})')
            return int(release['id'])
    if dry_run:
        print(f'would create release {tag}')
        return 0
    resp = requests.post(
        f'{API}/{repo}/releases',
        headers=_read_headers(token),
        data={
            **_form(repo, token),
            'tag_name': tag,
            'name': tag,
            # An absent `body` answers `body is missing`; an empty string is a field.
            'body': body,
            'target_commitish': 'main',
            'prerelease': 'false',
        },
        timeout=60,
    )
    if resp.status_code >= 300:
        raise SystemExit(f'creating release {tag} failed: HTTP {resp.status_code} {resp.text[:300]}')
    created = resp.json()
    print(f'created release {tag} (id {created["id"]})')
    return int(created['id'])


def attached(repo: str, token: str, release_id: int) -> dict[str, int]:
    """Attachment name → size, for the one release being published."""
    resp = requests.get(f'{API}/{repo}/releases/{release_id}/attach_files', headers=_read_headers(token), timeout=60)
    if resp.status_code >= 300:
        raise SystemExit(f'listing attachments failed: HTTP {resp.status_code} {resp.text[:300]}')
    return {str(asset.get('name') or ''): int(asset.get('size') or 0) for asset in resp.json() or []}


def upload(repo: str, token: str, release_id: int, files: list[Path], *, dry_run: bool = False) -> None:
    present = attached(repo, token, release_id) if release_id else {}
    for path in files:
        if path.name in present:
            print(f'  = {path.name} already attached ({present[path.name]} B)')
            continue
        print(f'  ^ {path.name} ({path.stat().st_size / 1024**2:.1f} MB)')
        if dry_run:
            continue
        with path.open('rb') as handle:
            resp = requests.post(
                f'{API}/{repo}/releases/{release_id}/attach_files',
                headers=_read_headers(token),
                data=_form(repo, token),
                files={'file': (path.name, handle)},
                timeout=UPLOAD_TIMEOUT,
            )
        if resp.status_code >= 300:
            raise SystemExit(f'uploading {path.name} failed: HTTP {resp.status_code} {resp.text[:400]}')


def _prune_module():
    """The sibling tool, loaded by path.

    ``tools/`` is not a package: a plain ``import prune_gitee_releases`` resolves only when this file
    is executed as a script (``sys.path[0]`` is then ``tools/``), and the test suite loads this module
    by path instead. Loading it by path works in both.
    """
    spec = importlib.util.spec_from_file_location(
        'prune_gitee_releases', Path(__file__).resolve().with_name('prune_gitee_releases.py')
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['prune_gitee_releases'] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def prune(repo: str, token: str, keep: set[str]) -> None:
    """Delete attachments outside *keep* — the one rule lives in ``prune_gitee_releases``."""
    _prune_module().prune(repo, token, keep, dry_run=False)


# ─── One run ───


def publish(repo: str, tag: str, keep: set[str], *, dry_run: bool = False, do_prune: bool = True) -> int:
    print('== split')
    parts: list[Path] = []
    for name in ARCHIVES:
        source = DIST / name
        if not source.exists():
            raise SystemExit(f'{source} is missing: build before publishing')
        parts.extend(write_shards(source, dry_run=dry_run))
    standalone = [DIST / name for name in STANDALONE]
    for path in standalone:
        if not path.exists():
            raise SystemExit(f'{path} is missing')
    sizes = [*parts, *standalone]

    if dry_run:
        # A dry run is the check you make BEFORE the build's upload window: local bytes only, no
        # token, no network. What it cannot tell you is which names are already attached — that
        # needs the release entry, and the upload step asks for it anyway.
        print(f'== would publish {len(sizes)} files to {repo} at {tag}; keeping {", ".join(sorted(keep))}')
        for path in sizes:
            print(f'  {path.name} {path.stat().st_size} {sha256(path)}')
        return 0

    token = token_from_env()

    print('== release')
    # Before the prune: prune_gitee_releases refuses a keep-tag with no release entry, and this tag
    # is one of the kept ones.
    release_id = ensure_release(repo, token, tag, body=release_notes(tag))

    if do_prune:
        print('== prune')
        prune(repo, token, keep)

    print('== upload')
    upload(repo, token, release_id, sizes)

    print('== sizes')
    for path in sizes:
        print(f'  {path.name} {path.stat().st_size} {sha256(path)}')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Split and upload one release's Windows artifacts to Gitee.")
    parser.add_argument('tag', help='the release tag being published (exe-2026-11-19.1)')
    parser.add_argument(
        '--keep',
        action='append',
        default=[],
        help='another tag whose attachments must survive the sweep (repeatable, for example manual-2026-11)',
    )
    parser.add_argument('--repo', default=DEFAULT_REPO, help=f'owner/name (default {DEFAULT_REPO})')
    parser.add_argument('--no-prune', action='store_true', help='upload without freeing room')
    parser.add_argument('--dry-run', action='store_true', help='print the plan, upload nothing')
    args = parser.parse_args(argv)
    return publish(args.repo, args.tag, {args.tag, *args.keep}, dry_run=args.dry_run, do_prune=not args.no_prune)


if __name__ == '__main__':
    sys.exit(main())
