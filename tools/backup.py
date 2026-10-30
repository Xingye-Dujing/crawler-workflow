"""Write a restore point: a git bundle of the repository plus an archive of the runtime state.

A push protects the branch, not the two things this checkout can lose:

* **history.** The repository's git history was once deleted by a tool; the code survived only
  because it happened to be on disk. A bundle is a single file that restores every ref.
* **runtime state.** ``data/`` is gitignored by design (it holds runs.db, uploaded datasets, the
  lexicon and the saved workflows' durable state), and only ``data/workflows/`` is versioned. A
  clone plus a push therefore cannot bring back a dataset a saved canvas references.

What goes into a backup (all optional items are skipped when absent):

* ``repo.bundle`` — every ref, restorable with ``git clone repo.bundle``;
* ``data.zip`` — ``data/workflows/``, ``data/reusable_nodes/``, the SQLite stores (``*.db``),
  ``settings.json`` and ``model_registry.json``;
* ``manifest.json`` — when, from which commit, whether the worktree was dirty, and every member.

**Cookies are excluded by default.** They are live account credentials in plain JSON; a backup
file gets copied to USB sticks and cloud drives. Pass ``--with-cookies`` only for a backup that
stays on this machine, and treat the resulting zip as a password.

Usage (from the repository root):

    .venv/Scripts/python.exe tools/backup.py
    .venv/Scripts/python.exe tools/backup.py --out D:/backups --with-cookies

Restore: ``git clone <backup>/repo.bundle crawler_workflow`` restores code and history; unpack
``data.zip`` over the checkout's ``data/`` with the server stopped.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / 'backups'
DEFAULT_DATA = REPO_ROOT / 'data'

#: Data directories that belong to the user's work (cookies are a separate opt-in).
DATA_DIRS = ('workflows', 'reusable_nodes')
#: Single files worth keeping: settings hold machine paths, the registry names the fine-tuned models.
DATA_FILES = ('settings.json', 'model_registry.json')
#: ``*.db`` are the durable stores; their ``-wal``/``-shm`` siblings are scratch.
DATA_DB_GLOB = '*.db'
#: Live account credentials — excluded unless the caller asks.
COOKIES_DIR = 'cookies'


# ─── What a backup contains ────────────────────────────────────


def select_data(data_root: Path, with_cookies: bool = False) -> list[Path]:
    """Every existing member of the backup, in a stable order, rooted at *data_root*."""
    chosen: list[Path] = []
    for name in DATA_DIRS:
        directory = data_root / name
        if directory.is_dir():
            chosen.extend(sorted(path for path in directory.rglob('*') if path.is_file()))
    for pattern in (*DATA_FILES, DATA_DB_GLOB):
        chosen.extend(sorted(path for path in data_root.glob(pattern) if path.is_file()))
    if with_cookies:
        jar_dir = data_root / COOKIES_DIR
        if jar_dir.is_dir():
            chosen.extend(sorted(path for path in jar_dir.rglob('*') if path.is_file()))
    return chosen


def write_data_archive(members: list[Path], target: Path, data_root: Path) -> None:
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in members:
            archive.write(path, arcname=f'data/{path.relative_to(data_root).as_posix()}')


# ─── The git half ──────────────────────────────────────────────


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ['git', '-C', str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
    except OSError as error:  # git is not installed — a backup without it is still a backup
        return subprocess.CompletedProcess(args, 127, '', f'git not available: {error}')


def git_facts(repo_root: Path, bundle_target: Path | None) -> dict:
    """HEAD, worktree diritness, remotes, and the bundle result (a failure is recorded, not raised)."""
    facts: dict = {'head': '', 'dirty': None, 'remotes': [], 'bundle': None}
    if not (repo_root / '.git').exists():
        facts['bundle'] = {'created': False, 'error': 'not a git checkout'}
        return facts
    head = _git(repo_root, 'rev-parse', 'HEAD')
    facts['head'] = head.stdout.strip() if head.returncode == 0 else ''
    status = _git(repo_root, 'status', '--porcelain')
    facts['dirty'] = bool(status.stdout.strip()) if status.returncode == 0 else None
    remotes = _git(repo_root, 'remote', '-v')
    facts['remotes'] = sorted({line.split()[0] for line in remotes.stdout.splitlines() if line.strip()})
    if bundle_target is not None:
        created = _git(repo_root, 'bundle', 'create', str(bundle_target), '--all')
        facts['bundle'] = (
            {'created': True, 'path': bundle_target.name}
            if created.returncode == 0
            else {'created': False, 'error': (created.stderr or created.stdout).strip()[-400:]}
        )
    return facts


# ─── The restore point ─────────────────────────────────────────


def create_backup(
    out_dir: Path,
    data_root: Path = DEFAULT_DATA,
    repo_root: Path = REPO_ROOT,
    with_cookies: bool = False,
    bundle: bool = True,
) -> dict:
    """Write one ``<timestamp>/`` directory and return its manifest."""
    moment = datetime.now().astimezone()
    target = Path(out_dir) / moment.strftime('%Y%m%d-%H%M%S')
    target.mkdir(parents=True, exist_ok=False)

    bundle_path = target / 'repo.bundle' if bundle else None
    git = git_facts(Path(repo_root), bundle_path)
    if bundle_path is not None and not (git['bundle'] or {}).get('created'):
        # A half-written bundle next to a manifest claiming otherwise is the worst outcome.
        bundle_path.unlink(missing_ok=True)

    members = select_data(Path(data_root), with_cookies=with_cookies)
    total_bytes = sum(path.stat().st_size for path in members)
    if members:
        write_data_archive(members, target / 'data.zip', Path(data_root))

    manifest = {
        'created_at': moment.isoformat(timespec='seconds'),
        'path': str(target),
        'repo_root': str(Path(repo_root)),
        'data_root': str(Path(data_root)),
        'git': git,
        'data_archive': 'data.zip' if members else None,
        'data_bytes': total_bytes,
        'cookies_included': bool(with_cookies),
        'members': [f'data/{path.relative_to(Path(data_root)).as_posix()}' for path in members],
    }
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Write a restore point (git bundle + data archive).')
    parser.add_argument('--out', default=str(DEFAULT_OUT), help=f'where to write it (default {DEFAULT_OUT})')
    parser.add_argument('--data', default=str(DEFAULT_DATA), help='the data/ root to archive')
    parser.add_argument(
        '--with-cookies',
        action='store_true',
        help='include data/cookies (live account credentials in plain JSON — keep that backup offline)',
    )
    args = parser.parse_args(argv)
    manifest = create_backup(Path(args.out), Path(args.data), REPO_ROOT, with_cookies=args.with_cookies)
    bundle = manifest['git']['bundle'] or {}
    print(f'backup written under {args.out}')
    print(f'  git bundle: {"ok" if bundle.get("created") else "skipped: " + str(bundle.get("error"))}')
    print(f'  data.zip:   {len(manifest["members"])} file(s), {manifest["data_bytes"] / (1 << 20):.1f} MB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
