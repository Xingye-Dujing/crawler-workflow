"""Back up the fine-tuned checkpoints and give datasets a task-shaped directory tree.

The four deployed BERTs are the result of weeks of distillation and training. A cleanup script that
removes ``ml_train/models`` would destroy them, so this tool keeps a second, checksummed copy under
``ml_train/backups/models/<timestamp>/`` before any experiment starts. A second copy of the datasets
is placed under task folders; on the same drive the copy is a hard link, so the organised tree costs
no extra bytes and deleting a legacy flat file cannot destroy the data.

Nothing here overwrites a file whose bytes differ, and nothing here deletes an original. Re-running
with a new timestamp adds a new backup; ``--verify`` only reads and reports.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import _env

#: Existing flat files -> their place in the task tree. New downloads follow the same vocabulary:
#: classification/sentiment|emotion, stance/raw|distilled|labeled, ner/<corpus>, retrieval/<pair>,
#: evaluation/<task>, raw/<source>.
DATASET_LAYOUT = {
    'ewect_smp2020': Path('classification/emotion/ewect_smp2020'),
    'weibo_senti_100k.csv': Path('classification/sentiment/weibo_senti_100k.csv'),
    'weibo_clean_265k.csv': Path('raw/weibo_clean_265k.csv'),
    'tendency_distilled.csv': Path('stance/distilled/tendency_distilled.csv'),
    'tendency_holdout_template.csv': Path('evaluation/stance/tendency_holdout_template.csv'),
    'controversy_crawl.csv': Path('stance/raw/controversy_crawl.csv'),
    'controversy_labeled.csv': Path('stance/labeled/controversy_labeled.csv'),
}

#: Folders prepared for downloads that are not present yet. Downloads never land in the flat root.
FUTURE_CATEGORIES = (
    'classification/sentiment',
    'classification/emotion',
    'stance/raw',
    'stance/distilled',
    'stance/labeled',
    'ner/msra',
    'ner/cluener',
    'ner/weibo_ner',
    'retrieval/lcqmc',
    'retrieval/bq',
    'retrieval/csts',
    'evaluation/sentiment',
    'evaluation/stance',
    'evaluation/ner',
    'evaluation/retrieval',
    'raw',
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _link_or_copy(source: Path, target: Path) -> str:
    """Place one file at ``target`` without touching ``source``; report the method used."""
    if target.exists():
        if target.is_file() and sha256(target) == sha256(source):
            return 'already-identical'
        raise FileExistsError(f'{target}: a different file is already there; refusing to overwrite')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
        return 'hardlink'
    except OSError:
        shutil.copy2(source, target)
        return 'copy'


def _copy_file(source: Path, target: Path) -> str:
    """An independent copy of one file; a different existing file is a refusal, never an overwrite."""
    if target.exists():
        if target.is_file() and sha256(target) == sha256(source):
            return 'already-identical'
        raise FileExistsError(f'{target}: a different file is already there; refusing to overwrite')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return 'copy'


def discover_models() -> list[Path]:
    """Every deployed checkpoint: a directory holding both weights and a tokenizer."""
    if not _env.MODELS_DIR.is_dir():
        return []
    return sorted(
        child
        for child in _env.MODELS_DIR.iterdir()
        if child.is_dir() and (child / 'model.safetensors').is_file() and (child / 'tokenizer.json').is_file()
    )


def backup_models(stamp: str) -> dict:
    target_root = _env.BACKUPS_DIR / 'models' / stamp
    target_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for source in discover_models():
        target = target_root / source.name
        for file in sorted(source.rglob('*')):
            if file.is_file():
                # A real copy, not a hard link: a training script that overwrites a weight in place
                # must not silently rewrite the backup as well.
                _copy_file(file, target / file.relative_to(source))
        rows.append(
            {
                'name': source.name,
                'source': str(source),
                'backup': str(target),
                'files': sum(1 for item in target.rglob('*') if item.is_file()),
                'bytes': sum(item.stat().st_size for item in target.rglob('*') if item.is_file()),
                'weights_sha256': sha256(source / 'model.safetensors'),
            }
        )
    manifest = {
        'schema': 1,
        'created_utc': datetime.now(UTC).isoformat(timespec='seconds'),
        'reason': 'protect fine-tuned checkpoints from an accidental cleanup of ml_train/models',
        'models': rows,
    }
    (target_root / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    return manifest


def organise_datasets() -> dict:
    rows = []
    for name, relative in DATASET_LAYOUT.items():
        source = _env.DATASETS_DIR / name
        if not source.exists():
            continue
        target = _env.DATASETS_DIR / relative
        method = _link_or_copy(source, target) if source.is_file() else _copy_tree(source, target)
        rows.append({'name': name, 'path': relative.as_posix(), 'method': method})
    for folder in FUTURE_CATEGORIES:
        (_env.DATASETS_DIR / folder).mkdir(parents=True, exist_ok=True)
    index = {
        'schema': 1,
        'layout': 'classification/<task>, stance/<raw|distilled|labeled>, ner/<corpus>, '
        'retrieval/<pair>, evaluation/<task>, raw/<source>',
        'datasets': rows,
    }
    (_env.DATASETS_DIR / 'INDEX.json').write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    return index


def _copy_tree(source: Path, target: Path) -> str:
    if target.exists() and not target.is_dir():
        raise FileExistsError(f'{target}: a file is already there; refusing to overwrite')
    target.mkdir(parents=True, exist_ok=True)
    method = 'hardlink'
    for file in sorted(source.rglob('*')):
        if file.is_file():
            outcome = _link_or_copy(file, target / file.relative_to(source))
            if outcome == 'copy':
                method = 'copy'
    return method


def verify() -> dict:
    """Check the newest backup against the live checkpoints, reading only."""
    roots = sorted((_env.BACKUPS_DIR / 'models').glob('*/manifest.json'))
    if not roots:
        return {'ok': False, 'reason': 'no backup manifest; run backup_assets.py first'}
    manifest = json.loads(roots[-1].read_text(encoding='utf-8'))
    problems = []
    for row in manifest['models']:
        source = Path(row['source'])
        if not source.is_dir():
            problems.append(f'{source}: live model is missing')
            continue
        live = sha256(source / 'model.safetensors')
        if live != row['weights_sha256']:
            problems.append(f'{source}: weights changed since the backup')
        for name in ('config.json', 'tokenizer.json'):
            if not (Path(row['backup']) / name).is_file():
                problems.append(f'{Path(row["backup"]) / name}: backup file is missing')
    return {'ok': not problems, 'manifest': str(roots[-1]), 'problems': problems, 'models': len(manifest['models'])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='only compare the newest backup with the live models')
    args = parser.parse_args()
    if args.verify:
        result = verify()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    models = backup_models(stamp)
    datasets = organise_datasets()
    result = verify()
    print(
        json.dumps(
            {'stamp': stamp, 'models': models, 'datasets': datasets, 'verify': result}, ensure_ascii=False, indent=2
        )
    )
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
