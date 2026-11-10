"""Write a restore point: a git bundle of the repository plus an archive of the runtime state.

A push protects the branch, not the two things this checkout can lose:

* **history.** The repository's git history was once deleted by a tool; the code survived only
  because it happened to be on disk. A bundle is a single file that restores every ref.
* **runtime state.** ``data/`` is gitignored by design (it holds runs.db, uploaded datasets, the
  lexicon and the saved workflows' durable state), and only ``data/workflows/`` is versioned. A
  clone plus a push therefore cannot bring back a dataset a saved canvas references.

What goes into a backup (all optional items are skipped when absent):

* ``repo.bundle`` — every ref, restorable with ``git clone repo.bundle``;
* ``data.zip`` — the machine's ``settings.json`` and ``model_registry.json``, and for BOTH the
  system tree and every account tree (``data/users/<user_id>/``): ``workflows/``,
  ``reusable_nodes/`` and the SQLite stores (``*.db``). Each database's write-ahead log is merged
  into the file before it is read, and when a running server holds the write lock the ``-wal``
  travels with it — a copy of ``x.db`` alone is not a copy of the database;
* ``manifest.json`` — when, from which commit, whether the worktree was dirty, and every member.

**Cookies are excluded by default.** They are live account credentials in plain JSON; a backup
file gets copied to USB sticks and cloud drives. Pass ``--with-cookies`` only for a backup that
stays on this machine, and treat the resulting zip as a password. It then covers every account's
``cookies/`` as well as the local owner's.

Usage (from the repository root):

    .venv/Scripts/python.exe tools/backup.py
    .venv/Scripts/python.exe tools/backup.py --out D:/backups --with-cookies

Restore: ``git clone <backup>/repo.bundle crawler_workflow`` restores code and history; unpack
``data.zip`` over the checkout's ``data/`` with the server stopped.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
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
#: ``*.db`` are the durable stores. Their ``-wal`` sibling is NOT scratch: committed transactions can
#: still be living there, so a copy of the main file alone loses the newest rows (see
#: :func:`_database`).
DATA_DB_GLOB = '*.db'
#: Live account credentials — excluded unless the caller asks.
COOKIES_DIR = 'cookies'
#: Every account's own tree of the same shape lives under this directory.
ACCOUNTS_DIR = 'users'
#: A deleted account's tree, set aside for the operator to recover or purge deliberately. It is not
#: this backup's subject, and archiving it would double the file for a decision already made.
SKIP_DIRS = ('.trash',)
#: SQLite's side files: ``-wal`` carries what has not been merged yet, ``-shm`` is its index.
SQLITE_SUFFIXES = ('-wal', '-shm')


# ─── What a backup contains ────────────────────────────────────


def _scope_roots(data_root: Path) -> list[Path]:
    """The system tree and every account tree.

    A multi-account install keeps its RUNTIME state in ``data/users/<user_id>/``: each account's
    ``runs.db``/``datasets.db``/``history.db``/``workflow_history.db``/``biblio.db``, its saved
    canvases, its reusable nodes and its cookie jars. Enumerating only ``data/``'s top level — which
    is what this tool did before the accounts landed — therefore backs up the machine's settings and
    NOT one byte of the work the docstring promises to protect, and reports success while doing it.
    """
    roots = [data_root]
    users = data_root / ACCOUNTS_DIR
    if users.is_dir():
        roots.extend(sorted(path for path in users.iterdir() if path.is_dir() and path.name not in SKIP_DIRS))
    return roots


def _database(path: Path) -> list[Path]:
    """One SQLite file plus whatever its write-ahead log still holds back.

    ``x.db`` alone is NOT the database: transactions already committed can still be sitting in
    ``x.db-wal``, so copying the main file alone drops the newest rows — exactly the accounts a
    registry backup exists to keep. The WAL is merged into the file first (the same move
    ``tools/migrate_accounts.py`` makes); when a live server holds the write lock the merge cannot
    run, and the side files travel with the database instead.
    """
    _checkpoint(path)
    chosen = [path]
    for suffix in SQLITE_SUFFIXES:
        peer = path.with_name(path.name + suffix)
        if peer.is_file():
            chosen.append(peer)
    return chosen


def _checkpoint(path: Path) -> None:
    """Fold a database's WAL into the main file, best effort (a busy server is not a failure)."""
    try:
        connection = sqlite3.connect(str(path), timeout=1.0)
        try:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            connection.close()
    except sqlite3.Error:
        return


def select_data(data_root: Path, with_cookies: bool = False) -> list[Path]:
    """Every existing member of the backup, in a stable order, rooted at *data_root*."""
    chosen: list[Path] = []
    data_root = Path(data_root)
    for index, scope in enumerate(_scope_roots(data_root)):
        for name in DATA_DIRS:
            directory = scope / name
            if directory.is_dir():
                chosen.extend(sorted(path for path in directory.rglob('*') if path.is_file()))
        chosen.extend(sorted(item for path in scope.glob(DATA_DB_GLOB) if path.is_file() for item in _database(path)))
        if index == 0:
            # Machine-level single files; an account tree holds none of them.
            for name in DATA_FILES:
                singleton = scope / name
                if singleton.is_file():
                    chosen.append(singleton)
        if with_cookies:
            jar_dir = scope / COOKIES_DIR
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
    """Write one ``<timestamp>/`` directory and return its manifest.

    Two backups inside one second are a real sequence (a script that runs the tool twice, a user
    pressing the button again after a failed verification), and ``exist_ok=False`` answered the
    second with a bare ``FileExistsError`` — the first backup looked like a tool failure. A taken
    name now gets ``-2``, ``-3``… appended instead of aborting.
    """
    moment = datetime.now().astimezone()
    stamp = moment.strftime('%Y%m%d-%H%M%S')
    target = Path(out_dir) / stamp
    attempt = 1
    while True:
        try:
            target.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            attempt += 1
            if attempt > 99:
                raise
            target = Path(out_dir) / f'{stamp}-{attempt}'

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
        help='include every cookies/ jar (live account credentials in plain JSON — keep that backup offline)',
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
