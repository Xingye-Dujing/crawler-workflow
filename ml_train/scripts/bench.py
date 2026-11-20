"""Measure accuracy AND throughput of the deployed classifiers on this machine.

One model at a time, one fixed held-out slice, no parallel workers. The result is a table of facts
(metric, dataset, split, rows/s, peak VRAM) written under ``ml_train/logs/model_bench`` and appended
to ``docs/model_bench.md``; a model that cannot load is named in the report, never dropped silently.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import _env
import pandas as pd
from gpu_preflight import require

SEED = 42


def _sentiment_frame(limit: int) -> pd.DataFrame:
    path = _env.DATASETS_DIR / 'classification/sentiment/weibo_senti_100k.csv'
    if not path.is_file():
        raise FileNotFoundError(f'{path}: run backup_assets.py first')
    frame = pd.read_csv(path, usecols=['label', 'review'])
    frame = frame.rename(columns={'review': 'text'})
    return frame.sample(n=min(limit, len(frame)), random_state=SEED).reset_index(drop=True)


LOADERS = {'sentiment': (_sentiment_frame, 0.6, 0.4)}


def _measure_sentiment(model_path: str, frame: pd.DataFrame, pos: float, neg: float) -> dict:
    from analyzers import SentimentAnalyzer

    try:
        import torch

        torch.cuda.reset_peak_memory_stats()
    except ImportError:
        torch = None
    started = time.perf_counter()
    analyzer = SentimentAnalyzer(mode='bert', bert_model=model_path, pos_threshold=pos, neg_threshold=neg)
    loaded = time.perf_counter()
    result = analyzer.analyze_dataframe(frame.copy(), text_column='text')
    finished = time.perf_counter()
    truth = frame['label'].astype(int).map({0: 'negative', 1: 'positive'})
    accuracy = float((result['sentiment'].astype(str).to_numpy() == truth.to_numpy()).mean())
    peak = round(torch.cuda.max_memory_allocated() / (1024 * 1024)) if torch and torch.cuda.is_available() else 0
    return {
        'model': model_path,
        'accuracy': round(accuracy, 4),
        'rows': len(frame),
        'load_seconds': round(loaded - started, 2),
        'infer_seconds': round(finished - loaded, 2),
        'rows_per_sec': round(len(frame) / max(0.001, finished - loaded), 1),
        'peak_vram_mb': peak,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--task',
        choices=tuple(LOADERS),
        default='sentiment',
        help='more tasks are added when their eval split is wired',
    )
    parser.add_argument('--models', required=True, help='comma-separated model folders or hub ids')
    parser.add_argument('--rows', type=int, default=2000)
    parser.add_argument(
        '--out', default='', help='JSON report path; default is a timestamp under ml_train/logs/model_bench'
    )
    args = parser.parse_args()

    # The analyzers are imported by lazy helpers below; publish backend/ on this process's path
    # before the first helper runs (isort would move a late sys.path edit above the imports).
    backend = str(_env.ROOT / 'backend')
    if backend not in sys.path:
        sys.path.insert(0, backend)
    gpu = require('infer')
    loader, pos, neg = LOADERS[args.task]
    frame = loader(args.rows)
    print(f'task={args.task} rows={len(frame)} gpu={gpu["device"]} free={gpu["free_mb"]} MiB')
    rows = []
    for model in [item.strip() for item in args.models.split(',') if item.strip()]:
        print(f'[{model}]', flush=True)
        try:
            rows.append(_measure_sentiment(model, frame, pos, neg))
        except Exception as exc:
            rows.append({'model': model, 'error': f'{type(exc).__name__}: {exc}'})
    report = {
        'schema': 1,
        'task': args.task,
        'seed': SEED,
        'measured_utc': datetime.now(UTC).isoformat(timespec='seconds'),
        'machine': gpu,
        'dataset': str(_env.DATASETS_DIR / 'classification/sentiment/weibo_senti_100k.csv'),
        'rows': [],
    }
    report['rows'] = rows
    target = (
        Path(args.out)
        if args.out
        else _env.LOGS_DIR / 'model_bench' / f'{args.task}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': str(target), 'rows': rows}, ensure_ascii=False, indent=2))
    return 0 if all('error' not in row for row in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
