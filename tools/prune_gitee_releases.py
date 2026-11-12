"""Free room on Gitee before uploading a new release.

Gitee caps a repository's release attachments at **1 GB**, and every Windows release carries
~260 MB of split archives, so the fourth or fifth release fills it: measured, uploading
``CaiXiHui-Online-Setup.exe`` after the split parts answered
``验证失败，文件大小已超过仓库附件大小：1 GB`` and the installer was missing from the domestic
download page while ``version.json`` already pointed at that tag. The release the feed names is
the one that matters, so the rule is "keep the tags being published, delete the rest".

    set GITEE_TOKEN=...                     # never on the command line: argv is world-readable
    python tools/prune_gitee_releases.py --tag exe-2026-11.13 --dry-run
    python tools/prune_gitee_releases.py --tag exe-2026-11.13 --tag manual-2026-11

Only ATTACHMENTS are deleted: the release entry, its notes and the git tag stay, so an old
download page still explains what that version was. Gitee's releases list carries no attachment
ids or sizes, so each release's ``attach_files`` is read for the real bytes. The auto-generated
``<tag>.zip`` / ``.tar.gz`` links in that list are NOT attachments (they point at
``/archive/refs/tags/``), cannot be deleted this way, and cost nothing against the budget.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import requests

DEFAULT_REPO = 'Xingye-Dujing/crawler-workflow'
API = 'https://gitee.com/api/v5/repos'
TIMEOUT = 60


@dataclass(frozen=True)
class Attachment:
    """One file attached to a release, with what it costs against the 1 GB budget."""

    release_id: int
    tag: str
    attach_id: int
    name: str
    size: int


def plan(releases: list[dict], keep_tags: set[str]) -> tuple[list[Attachment], int]:
    """The attachments to delete — every tag except those being kept — and their total bytes.

    The kept tag is named, never inferred from a date: a re-published older tag must stay
    downloadable even when a newer tag exists.
    """
    doomed: list[Attachment] = []
    for release in releases:
        tag = str(release.get('tag_name') or '')
        if tag in keep_tags:
            continue
        for asset in release.get('assets') or []:
            doomed.append(
                Attachment(
                    release_id=int(release.get('id') or 0),
                    tag=tag,
                    attach_id=int(asset.get('id') or 0),
                    name=str(asset.get('name') or ''),
                    size=int(asset.get('size') or 0),
                )
            )
    return doomed, sum(item.size for item in doomed)


def _headers(token: str) -> dict:
    return {'Authorization': f'token {token}'}


def list_releases(repo: str, token: str) -> list[dict]:
    releases: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            f'{API}/{repo}/releases',
            headers=_headers(token),
            params={'page': page, 'per_page': 100, 'direction': 'desc'},
            timeout=TIMEOUT,
        )
        if resp.status_code >= 300:
            raise SystemExit(f'listing releases failed: HTTP {resp.status_code} {resp.text[:300]}')
        batch = resp.json() or []
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def list_attachments(repo: str, token: str, release_id: int) -> list[dict]:
    """Real attachments only; the archive links Gitee generates are not deletable and cost nothing."""
    resp = requests.get(f'{API}/{repo}/releases/{release_id}/attach_files', headers=_headers(token), timeout=TIMEOUT)
    if resp.status_code >= 300:
        raise SystemExit(f'listing attachments of release {release_id} failed: HTTP {resp.status_code}')
    return [
        asset for asset in (resp.json() or []) if '/releases/download/' in str(asset.get('browser_download_url') or '')
    ]


def prune(repo: str, token: str, keep_tags: set[str], *, dry_run: bool) -> int:
    releases = list_releases(repo, token)
    tags = {str(item.get('tag_name') or '') for item in releases}
    missing = sorted(tag for tag in keep_tags if tag not in tags)
    if missing:
        # A typo in --tag would otherwise delete every asset in the repository.
        raise SystemExit(
            f'no Gitee release for {", ".join(missing)}, so "keep the current tag" would delete every '
            f'asset; create the release first (existing: {", ".join(sorted(tags)) or "none"})'
        )
    for release in releases:
        if str(release.get('tag_name') or '') in keep_tags:
            continue
        release['assets'] = list_attachments(repo, token, int(release.get('id') or 0))
    doomed, total = plan(releases, keep_tags)
    print(f'{len(releases)} releases, {len(doomed)} attachments to delete, {total / 1024**2:.1f} MB')
    for item in doomed:
        print(f'  -{item.tag}/{item.name} ({item.size / 1024**2:.1f} MB)')
    if dry_run:
        print('dry run: nothing deleted')
        return 0
    freed = 0
    for item in doomed:
        resp = requests.delete(
            f'{API}/{repo}/releases/{item.release_id}/attach_files/{item.attach_id}',
            headers=_headers(token),
            timeout=TIMEOUT,
        )
        if resp.status_code >= 300:
            raise SystemExit(f'deleting {item.tag}/{item.name} failed: HTTP {resp.status_code} {resp.text[:300]}')
        freed += item.size
        print(f'  deleted {item.tag}/{item.name}')
    print(f'freed {freed / 1024**2:.1f} MB; kept: {", ".join(sorted(keep_tags))}')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Delete Gitee release attachments outside the tags being published.')
    parser.add_argument(
        '--tag',
        action='append',
        required=True,
        help='a release tag to keep (repeatable, for example exe-2026-11.13 and manual-2026-11)',
    )
    parser.add_argument('--repo', default=DEFAULT_REPO, help=f'owner/name (default {DEFAULT_REPO})')
    parser.add_argument('--dry-run', action='store_true', help='print the plan, delete nothing')
    args = parser.parse_args(argv)
    token = str(os.environ.get('GITEE_TOKEN') or '').strip()
    if not token:
        raise SystemExit('GITEE_TOKEN is not set: export a Gitee personal token with the projects scope')
    return prune(args.repo, token, set(args.tag), dry_run=args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
