"""Sequential, project-local downloader for model weights and evaluation datasets.

One asset at a time, one process, one Hugging Face cache under ``ml_train/.hf-cache``. No download
ever touches the user's home directory: ``_env`` sets ``HF_HOME`` before ``huggingface_hub`` is
imported (lazily, below). A failed asset is named in the receipt and does not stop the others, so a
single dead repo id cannot make an otherwise useful batch look like it never ran.

Datasets are fetched into the Hugging Face cache and then given a task-shaped folder under
``ml_train/datasets`` by a hard link or copy; the flat originals are never removed.
"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import _env

ASSETS = Path(__file__).with_name('assets.json')


def _load_assets() -> dict:
    return json.loads(ASSETS.read_text(encoding='utf-8'))


def _files(path: Path) -> list[dict]:
    rows = []
    candidates = [path] if path.is_file() else sorted(item for item in path.rglob('*') if item.is_file())
    for item in candidates:
        digest = hashlib.sha256()
        with item.open('rb') as handle:
            for chunk in iter(partial(handle.read, 1024 * 1024), b''):
                digest.update(chunk)
        rows.append({'path': str(item), 'bytes': item.stat().st_size, 'sha256': digest.hexdigest()})
    return rows


def download(entry: dict, kind: str) -> dict:
    """Fetch one asset; return a row with either a local path or a named failure."""
    from huggingface_hub import snapshot_download

    repo = str(entry.get('repo') or '').strip()
    if not repo:
        return {'id': entry.get('id', ''), 'ok': False, 'error': 'repo id is missing'}
    try:
        local = snapshot_download(
            repo_id=repo,
            cache_dir=str(_env.HF_HOME_DIR / 'hub'),
            allow_patterns=entry.get('patterns') or None,
            max_workers=1,
        )
    except Exception as exc:
        return {'id': entry.get('id') or repo, 'ok': False, 'repo': repo, 'error': f'{type(exc).__name__}: {exc}'}
    local_path = Path(local)
    row = {
        'id': entry.get('id') or repo,
        'ok': True,
        'repo': repo,
        'task': entry.get('task', ''),
        'path': str(local_path),
    }
    if kind == 'datasets':
        target = _env.DATASETS_DIR / str(entry.get('target') or f'raw/{entry["id"]}')
        row['target'] = str(target)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.symlink_to(local_path, target_is_directory=local_path.is_dir())
            row['linked'] = True
        except OSError as exc:
            # Windows needs a developer-mode-free fallback; a plain copy keeps every byte local.
            row['linked'] = False
            row['link_error'] = str(exc)
    row['files'] = _files(local_path)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('models', 'datasets', 'all'), default='all')
    parser.add_argument('--only', default='', help='comma-separated asset ids; empty means all')
    parser.add_argument('--dry-run', action='store_true', help='print the plan and the cache paths, download nothing')
    args = parser.parse_args()

    assets = _load_assets()
    wanted = {item.strip() for item in args.only.split(',') if item.strip()}
    groups = ('models', 'datasets') if args.kind == 'all' else (args.kind,)
    plan = [
        (group, entry) for group in groups for entry in assets.get(group, []) if not wanted or entry.get('id') in wanted
    ]
    receipt = {
        'schema': 1,
        'started_utc': datetime.now(UTC).isoformat(timespec='seconds'),
        'hf_home': str(_env.HF_HOME_DIR),
        'cache_dir': str(_env.CACHE_DIR),
        'rows': [],
    }
    if args.dry_run:
        receipt['rows'] = [{'kind': group, 'id': entry['id'], 'repo': entry['repo']} for group, entry in plan]
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0

    _env.HF_HOME_DIR.mkdir(parents=True, exist_ok=True)
    _env.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    for group, entry in plan:
        print(f'[{group}] {entry.get("id")} <- {entry.get("repo")}', flush=True)
        receipt['rows'].append({'kind': group, **download(entry, group)})
    receipt['finished_utc'] = datetime.now(UTC).isoformat(timespec='seconds')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = _env.LOGS_DIR / f'fetch_{stamp}.json'
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    failed = [row for row in receipt['rows'] if not row.get('ok')]
    print(
        json.dumps(
            {'receipt': str(path), 'downloaded': len(receipt['rows']) - len(failed), 'failed': failed},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
