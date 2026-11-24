"""One-time move from the flat export folder to one folder per run.

This is a RELEASE step, not a startup hook. The flat layout is the only thing the old build knows,
so the move is explicit, dry-runnable and reversible. Every moved file is recorded in
``migration_manifest.json`` beside the export folder, with its old and new relative names.

    python tools/migrate_export_groups.py --dry-run
    python tools/migrate_export_groups.py
    python tools/migrate_export_groups.py --reverse
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _backend():
    if os.path.join(ROOT, 'backend') not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, 'backend'))


def _manifest_path(export_dir: str) -> str:
    return os.path.join(export_dir, 'migration_manifest.json')


def _write_manifest(export_dir: str, rows: list[dict]) -> None:
    with open(_manifest_path(export_dir), 'w', encoding='utf-8') as handle:
        json.dump({'version': 1, 'files': rows}, handle, ensure_ascii=False, indent=2)


def _load_manifest(export_dir: str) -> list[dict]:
    try:
        with open(_manifest_path(export_dir), encoding='utf-8') as handle:
            return list(json.load(handle).get('files') or [])
    except (OSError, ValueError):
        return []


def migrate(dry_run: bool = False) -> dict:
    _backend()
    from runtime import paths
    from runtime.stores import get_run_store

    from services.exports.groups import LEGACY_GROUP, ensure_group

    active = paths.active()
    export_dir = active.export_dir
    store = get_run_store()
    ledger = store.run_ledger()
    by_name = {}
    for run in ledger:
        for file in run.get('files') or []:
            by_name[str(file.get('name') or '')] = (str(run.get('run_id') or ''), str(file.get('group') or ''))
    flat = [
        name
        for name in sorted(os.listdir(export_dir))
        if os.path.isfile(os.path.join(export_dir, name))
        and not name.startswith('.')
        and name != 'migration_manifest.json'
    ]
    moved = []
    for name in flat:
        run_id, group = by_name.get(name, ('', ''))
        if not group:
            group = str((store.get_run(run_id) or {}).get('export_group') or '') if run_id else ''
        if not group:
            group = LEGACY_GROUP
        source = os.path.join(export_dir, name)
        target_dir = ensure_group(export_dir, group) if not dry_run else os.path.join(export_dir, group)
        target = os.path.join(target_dir, name)
        moved.append({'old': name, 'new': os.path.join(group, name), 'run_id': run_id, 'group': group})
        if dry_run:
            continue
        os.makedirs(target_dir, exist_ok=True)
        if os.path.exists(target):
            stem, ext = os.path.splitext(name)
            n = 1
            while os.path.exists(os.path.join(target_dir, f'{stem}-{n}{ext}')):
                n += 1
            target = os.path.join(target_dir, f'{stem}-{n}{ext}')
        shutil.move(source, target)
        if run_id:
            store.set_export_group(run_id, group)
            store.set_file_group(run_id, name, group)
    if not dry_run:
        _write_manifest(export_dir, moved)
    return {'dry_run': dry_run, 'moved': len(moved), 'files': moved}


def reverse() -> dict:
    _backend()
    from runtime import paths

    export_dir = paths.active().export_dir
    rows = _load_manifest(export_dir)
    restored = 0
    for row in rows:
        source = os.path.join(export_dir, str(row.get('new') or ''))
        target = os.path.join(export_dir, str(row.get('old') or ''))
        if not os.path.isfile(source) or os.path.exists(target):
            continue
        shutil.move(source, target)
        restored += 1
    return {'restored': restored}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--reverse', action='store_true')
    args = parser.parse_args()
    if args.reverse:
        print(json.dumps(reverse(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(migrate(dry_run=args.dry_run), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
