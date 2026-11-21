"""Measure Chinese embedding and reranking candidates on this machine.

One model at a time, a fixed random seed and a fixed slice of a real pair dataset. The report
records recall@10 (retrieval), pairwise accuracy (reranking), rows/s and peak VRAM under
``ml_train/logs/model_bench`` — the same evidence standard as ``bench.py``. A model that cannot
load is named in the report; a candidate without a measured number never enters default_for.
"""

import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import _env
import numpy as np
import pandas as pd
from gpu_preflight import require

SEED = 42
TEXT_COLUMNS = (
    ('query', 'title'),
    ('query', 'doc'),
    ('text1', 'text2'),
    ('sentence1', 'sentence2'),
    ('query1', 'query2'),
)
LABEL_COLUMNS = ('label', 'score', 'similarity', 'cosine_score')


def _dataset_frame(dataset: str) -> pd.DataFrame:
    """Load one downloaded pair dataset, naming the file and columns it actually used."""
    root = _env.DATASETS_DIR / 'retrieval' / dataset
    files = sorted(
        item
        for item in root.rglob('*')
        if item.is_file() and item.suffix.lower() in {'.jsonl', '.json', '.csv', '.tsv', '.parquet'}
    )
    if not files:
        raise FileNotFoundError(f'{root}: no pair file; run fetch_assets.py --kind datasets --only {dataset}')

    def read(path: Path) -> pd.DataFrame:
        suffix = path.suffix.lower()
        if suffix == '.jsonl':
            return pd.read_json(path, lines=True)
        if suffix == '.json':
            return pd.read_json(path)
        if suffix == '.parquet':
            return pd.read_parquet(path)
        return pd.read_csv(path, sep='\t' if suffix == '.tsv' else ',')

    frame = pd.concat([read(path) for path in files], ignore_index=True)
    left = right = label = ''
    for candidate_left, candidate_right in TEXT_COLUMNS:
        if candidate_left in frame.columns and candidate_right in frame.columns:
            left, right = candidate_left, candidate_right
            break
    for candidate in LABEL_COLUMNS:
        if candidate in frame.columns:
            label = candidate
            break
    if not left or not label:
        raise ValueError(f'{root}: cannot find a text pair and a label among {list(frame.columns)}')
    frame = frame[[left, right, label]].dropna()
    frame.columns = ['query', 'candidate', 'label']
    frame['label'] = pd.to_numeric(frame['label'], errors='coerce')
    return frame.dropna(subset=['label'])


def _triplet_data(dataset: str, sample: int, rows: int) -> tuple[list, list, dict, list]:
    """Load a dataset with explicit (query, positives, negatives) triplets.

    T2Reranking ships labelled hard negatives, so both the retrieval and the reranking
    metric stop saturating at 1.0 the way paraphrase-only LCQMC did.
    """
    root = _env.DATASETS_DIR / 'retrieval' / dataset
    files = sorted(item for item in root.rglob('*.parquet') if item.is_file())
    if not files:
        raise FileNotFoundError(f'{root}: no triplet parquet; run fetch_assets.py --only {dataset}')
    frame = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    if not {'query', 'positive', 'negative'}.issubset(frame.columns):
        raise ValueError(f'{root}: expected query/positive/negative columns, got {list(frame.columns)}')
    frame = frame.sample(n=min(sample, len(frame)), random_state=SEED)
    buckets: dict[str, list[str]] = {}
    negatives: dict[str, str] = {}
    corpus: list[str] = []
    for row in frame.itertuples(index=False):
        query = str(row.query)
        positives = [str(item) for item in row.positive]
        candidates = [str(item) for item in row.negative]
        if not positives or not candidates:
            continue
        buckets[query] = positives
        negatives[query] = candidates[0]
        corpus.extend(positives)
        corpus.extend(candidates)
    queries = list(buckets)[: min(rows, len(buckets))]
    return queries, list(dict.fromkeys(corpus)), buckets, [negatives[query] for query in queries]


def _bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _pairs(frame: pd.DataFrame, rows: int, positive_threshold: float) -> tuple[list, list, list]:
    """Build a fixed query/candidate/negative set with LEXICALLY HARD negatives.

    Random negatives make every reranker look perfect on LCQMC paraphrases; picking a
    candidate that shares character bigrams with the query but is not a labelled positive
    keeps pairwise accuracy discriminative.
    """
    rng = random.Random(SEED)
    frame = frame.sample(frac=1, random_state=SEED).reset_index(drop=True)
    corpus = list(dict.fromkeys(frame['candidate'].astype(str).tolist()))
    positive_rows = frame[frame['label'] >= positive_threshold]
    buckets: dict[str, list[str]] = {}
    for query, candidate in zip(
        positive_rows['query'].astype(str), positive_rows['candidate'].astype(str), strict=True
    ):
        buckets.setdefault(query, []).append(candidate)
    queries = list(buckets)[: min(rows, len(buckets))]
    grams = [_bigrams(item) for item in corpus]
    inverted: dict[str, list[int]] = {}
    for index, item in enumerate(grams):
        for gram in item:
            inverted.setdefault(gram, []).append(index)
    negatives = []
    for query in queries:
        forbidden = set(buckets[query])
        counts: dict[int, int] = {}
        for gram in _bigrams(query):
            for index in inverted.get(gram, ()):
                if corpus[index] not in forbidden:
                    counts[index] = counts.get(index, 0) + 1
        if counts:
            best = max(counts.values())
            pool = [corpus[index] for index, count in counts.items() if count >= max(1, best - 1)]
            negatives.append(rng.choice(pool))
        else:
            pool = [item for item in corpus if item not in forbidden]
            negatives.append(rng.choice(pool) if pool else '')
    return queries, corpus, negatives


def _measure_encoder(name: str, queries: list, corpus: list, buckets: dict, device: str) -> dict:
    import torch
    from sentence_transformers import SentenceTransformer

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = SentenceTransformer(name, device=device)
    loaded = time.perf_counter()
    query_vec = model.encode(
        queries, batch_size=64, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
    )
    corpus_vec = model.encode(
        corpus, batch_size=64, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
    )
    finished = time.perf_counter()
    scores = np.asarray(query_vec) @ np.asarray(corpus_vec).T
    top = np.argsort(-scores, axis=1)[:, :10]
    index = {text: i for i, text in enumerate(corpus)}
    hits = 0
    for row, query in enumerate(queries):
        wanted = {index[item] for item in buckets[query] if item in index}
        hits += int(bool(wanted & set(top[row].tolist())))
    recall = hits / max(1, len(queries))
    peak = round(torch.cuda.max_memory_allocated() / (1024 * 1024)) if torch.cuda.is_available() else 0
    del model, query_vec, corpus_vec, scores
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {
        'model': name,
        'task': 'embedding',
        'recall_at_10': round(recall, 4),
        'queries': len(queries),
        'corpus': len(corpus),
        'load_seconds': round(loaded - started, 2),
        'infer_seconds': round(finished - loaded, 2),
        'rows_per_sec': round((len(queries) + len(corpus)) / max(0.001, finished - loaded), 1),
        'peak_vram_mb': peak,
    }


def _measure_reranker(
    name: str, buckets: dict, queries: list, negatives: list, _corpus: list, device: str, batch_size: int
) -> dict:
    import torch
    from sentence_transformers import CrossEncoder

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = CrossEncoder(name, device=device)
    loaded = time.perf_counter()
    pairs, truth = [], []
    for query, negative in zip(queries, negatives, strict=True):
        positives = buckets[query]
        pairs.append((query, positives[0]))
        truth.append(1)
        if negative:
            pairs.append((query, negative))
            truth.append(0)
    scores = model.predict(pairs, batch_size=batch_size)
    finished = time.perf_counter()
    wins = sum(1 for i in range(0, len(scores) - 1, 2) if scores[i] > scores[i + 1])
    scored = len(scores)
    peak = round(torch.cuda.max_memory_allocated() / (1024 * 1024)) if torch.cuda.is_available() else 0
    del model, scores
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {
        'model': name,
        'task': 'reranker',
        'pairwise_accuracy': round(wins / max(1, scored // 2), 4),
        'pairs': len(pairs),
        'load_seconds': round(loaded - started, 2),
        'infer_seconds': round(finished - loaded, 2),
        'rows_per_sec': round(len(pairs) / max(0.001, finished - loaded), 1),
        'peak_vram_mb': peak,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=('embedding', 'reranker'), required=True)
    parser.add_argument('--dataset', default='t2-reranking', choices=('lcqmc', 'bq', 't2-reranking'))
    parser.add_argument('--models', required=True, help='comma-separated hub ids or local paths')
    parser.add_argument('--rows', type=int, default=300, help='number of queries; corpus is the whole sample')
    parser.add_argument('--sample', type=int, default=1500, help='labelled rows to sample from the dataset')
    parser.add_argument('--positive-threshold', type=float, default=1.0, help='CSTS uses a score, others a 0/1 label')
    parser.add_argument('--batch-size', type=int, default=32, help='reranker batch; lower it on 8GB cards')
    parser.add_argument('--out', default='', help='report path; default is a timestamp under ml_train/logs/model_bench')
    args = parser.parse_args()

    gpu = require('infer')
    device = 'cuda' if gpu.get('available') else 'cpu'
    if args.dataset == 't2-reranking':
        queries, corpus, buckets, _negatives = _triplet_data(args.dataset, args.sample, args.rows)
    else:
        data = _dataset_frame(args.dataset)
        frame = data.sample(n=min(args.sample, len(data)), random_state=SEED)
        queries, corpus, _negatives = _pairs(frame, args.rows, args.positive_threshold)
        buckets = {}
        for query, candidate in zip(frame['query'].astype(str), frame['candidate'].astype(str), strict=True):
            buckets.setdefault(query, []).append(candidate)
    print(
        f'task={args.task} dataset={args.dataset} queries={len(queries)} corpus={len(corpus)} device={device}',
        flush=True,
    )
    rows = []
    for name in [item.strip() for item in args.models.split(',') if item.strip()]:
        print(f'[{name}]', flush=True)
        try:
            if args.task == 'embedding':
                rows.append(_measure_encoder(name, queries, corpus, buckets, device))
            else:
                rows.append(_measure_reranker(name, buckets, queries, _negatives, corpus, device, args.batch_size))
        except Exception as exc:
            rows.append({'model': name, 'error': f'{type(exc).__name__}: {exc}'})
    report = {
        'schema': 1,
        'task': args.task,
        'dataset': args.dataset,
        'seed': SEED,
        'measured_utc': datetime.now(UTC).isoformat(timespec='seconds'),
        'machine': gpu,
        'rows': rows,
    }
    out = (
        Path(args.out)
        if args.out
        else _env.LOGS_DIR / 'model_bench' / f'retrieval_{args.task}_{datetime.now():%Y%m%d_%H%M%S}.json'
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    print(f'report={out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
