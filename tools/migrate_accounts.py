"""Move a pre-accounts data root into the bootstrap administrator's own folder.

Before accounts, the checkout-level ``data/`` was the single owner's tree. A multi-account host
gives every account ``data/users/<user_id>/`` (``backend/runtime/paths.py``), so the old tree must
be adopted by the first administrator or none of its runs, datasets, workflows, cookies or exports
are reachable.

The move is deliberately conservative:

* **dry run by default** — ``--apply`` is required to touch anything;
* **copy, verify, then set the original aside** — every SQLite file is checked with
  ``PRAGMA integrity_check`` and every directory's file count/size is compared before the source
  is renamed into ``data/.migrated-<timestamp>/`` (never deleted);
* **refuses an occupied destination** — the administrator already having a ``runs.db`` means this
  has been run before (or the account is in use), and merging two stores is not something this
  tool may guess at;
* **only the user's work moves** — ``accounts.db``, ``settings.json``, ``lexicon.db``, ``models/``
  and ``jieba/`` stay at the root because they describe the machine, not one person.

Usage (server STOPPED, from the repository root):

    .venv/Scripts/python.exe tools/migrate_accounts.py --user admin
    .venv/Scripts/python.exe tools/migrate_accounts.py --user admin --apply
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

#: One file or directory each. Anything not listed belongs to the machine (see the docstring).
ENTRIES = (
    'runs.db',
    'datasets.db',
    'history.db',
    'workflow_history.db',
    'biblio.db',
    'workflows',
    'cookies',
    'chrome_profile',
    'exports',
    'checkpoints',
    'harvest',
    'reusable_nodes',
    'locks.json',
    'schedules.json',
)
SQLITE_FILES = ('runs.db', 'datasets.db', 'history.db', 'workflow_history.db', 'biblio.db')


class MigrationError(RuntimeError):
    """A named refusal: the tool does not guess what to do with an ambiguous tree."""


def _lookup_user(accounts_db: Path, username: str) -> str:
    from services.accounts.store import AccountsStore

    if not accounts_db.is_file():
        raise MigrationError(
            f'no account registry at {accounts_db} — start the server once with the bootstrap '
            'password first, so the administrator exists'
        )
    store = AccountsStore(str(accounts_db))
    try:
        row = store.get_user_by_username(username)
    finally:
        store.close()
    if row is None:
        raise MigrationError(f'no account named {username!r} in {accounts_db}')
    return str(row['user_id'])


def plan(data_root: Path, username: str) -> dict:
    """What a run WOULD move, and where to. Refuses an ambiguous destination."""
    data_root = Path(data_root)
    user_id = _lookup_user(data_root / 'accounts.db', username)
    target = data_root / 'users' / user_id
    moves = []
    occupied = []
    for name in ENTRIES:
        source = data_root / name
        if not source.exists():
            continue
        destination = target / name
        if destination.exists():
            occupied.append(str(destination))
        moves.append((str(source), str(destination)))
    if occupied:
        raise MigrationError('the administrator already has data at: ' + ', '.join(occupied))
    return {'user_id': user_id, 'target': str(target), 'moves': moves}


def _files(directory: Path) -> list:
    if directory.is_file():
        return [directory]
    return [path for path in directory.rglob('*') if path.is_file()]


def _verify(source: Path, target: Path) -> None:
    if source.is_file():
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            raise MigrationError(f'copy of {source.name} does not match its size')
        return
    source_files = _files(source)
    target_files = _files(target)
    if len(source_files) != len(target_files):
        raise MigrationError(f'copy of {source.name} has {len(target_files)} files, expected {len(source_files)}')
    for src in source_files:
        dst = target / src.relative_to(source)
        if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
            raise MigrationError(f'copy of {src.relative_to(source)} does not match')


def _integrity(path: Path) -> None:
    try:
        conn = sqlite3.connect(str(path))
        try:
            answer = conn.execute('PRAGMA integrity_check').fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise MigrationError(f'{path.name} is not a readable SQLite database: {exc}') from exc
    if not answer or str(answer[0]).lower() != 'ok':
        raise MigrationError(f'{path.name} failed PRAGMA integrity_check: {answer[0] if answer else "no answer"}')


def migrate(data_root: Path, username: str, apply: bool = False) -> dict:
    """Copy the legacy tree into the account, verify it, then set the originals aside."""
    data_root = Path(data_root)
    answer = plan(data_root, username)
    answer['applied'] = False
    if not apply:
        return answer
    target = Path(answer['target'])
    moved_aside = data_root / f'.migrated-{time.strftime("%Y%m%d-%H%M%S")}'
    os.makedirs(target, exist_ok=True)
    for source_text, destination_text in answer['moves']:
        source = Path(source_text)
        destination = Path(destination_text)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        _verify(source, destination)
        if source.suffix == '.db':
            _integrity(destination)
    os.makedirs(moved_aside, exist_ok=True)
    for source_text, _destination in answer['moves']:
        source = Path(source_text)
        shutil.move(str(source), str(moved_aside / source.name))
    answer['applied'] = True
    answer['moved_aside'] = str(moved_aside)
    return answer


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description='Move a pre-accounts data root into the administrator account.')
    parser.add_argument(
        '--data-root', default=str(REPO_ROOT / 'data'), help="the data/ directory to migrate (default: this checkout's)"
    )
    parser.add_argument('--user', default='admin', help='the account that adopts the tree (default: admin)')
    parser.add_argument('--apply', action='store_true', help='perform the move (default is a dry run)')
    args = parser.parse_args(argv)
    data_root = Path(args.data_root).expanduser().resolve()
    try:
        answer = migrate(data_root, args.user, apply=args.apply)
    except MigrationError as exc:
        print(f'refused: {exc}')
        return 2
    if not answer['moves']:
        print('nothing to migrate: the legacy tree holds none of the account-owned entries')
        return 0
    verb = 'moved' if answer['applied'] else 'would move'
    print(f'{verb} {len(answer["moves"])} entries into {answer["target"]} for {args.user} ({answer["user_id"]})')
    for source, destination in answer['moves']:
        print(f'  {source} -> {destination}')
    if not answer['applied']:
        print('dry run only — pass --apply to perform it (stop the server first)')
    else:
        print(f'originals were set aside in {answer["moved_aside"]} (nothing was deleted)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
