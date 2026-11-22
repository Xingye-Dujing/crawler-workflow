"""Seed the isolated film data root with a realistic few-hundred-row dataset.

The film should demonstrate data, not just show a static panel: a preview that
scrolls through hundreds of real comments, an analysis node that actually labels
them. We sample real Weibo comments (with sentiment labels) from the project's
own ``ml_train`` corpus, add a city column, and overwrite the demo_reviews
dataset in the film's private datasets.db — keeping its dataset_id so the saved
showcase_sentiment canvas keeps working.

The checkout's own data/ is never touched; only the isolated copy is rewritten.
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'ml_train' / 'datasets' / 'weibo_senti_100k.csv'
DEMO_ID = 'd4feca02006f4f41'  # showcase_sentiment's Upload node
CITIES = ['杭州', '成都', '西安', '长沙', '南京', '重庆', '青岛', '厦门', '武汉', '广州']


def build_records(n: int, seed: int = 11) -> tuple[list[dict], list[str]]:
    rows: list[tuple[int, str]] = []
    with SOURCE.open(encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f)
        next(reader, None)  # header: label,review
        for row in reader:
            if len(row) < 2:
                continue
            try:
                label = int(row[0])
            except ValueError:
                continue
            text = row[1].lstrip('\ufeff').strip()
            if text:
                rows.append((label, text))
    if len(rows) < n:
        raise RuntimeError(f'weibo corpus has only {len(rows)} usable rows, need {n}')

    rng = random.Random(seed)
    sampled = rng.sample(rows, n)
    cols = ['城市', '评论']
    records: list[dict] = []
    for _label, text in sampled:
        records.append({'城市': rng.choice(CITIES), '评论': text})
    return records, cols


def encode(records: list[dict]) -> bytes:
    canonical = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    return zlib.compress(canonical.encode('utf-8'), 6)


def seed(datasets_db: Path, n: int = 600) -> int:
    if not SOURCE.is_file():
        raise FileNotFoundError(f'weibo corpus missing: {SOURCE}')
    records, cols = build_records(n)
    payload = encode(records)
    con = sqlite3.connect(str(datasets_db))
    try:
        exists = con.execute('SELECT 1 FROM datasets WHERE dataset_id=?', (DEMO_ID,)).fetchone()
        if not exists:
            raise RuntimeError(f'demo dataset {DEMO_ID} not present in {datasets_db}')
        con.execute(
            'UPDATE datasets SET columns=?, row_count=?, byte_size=?, payload=? WHERE dataset_id=?',
            (json.dumps(cols, ensure_ascii=False), len(records), len(payload), payload, DEMO_ID),
        )
        con.commit()
    finally:
        con.close()
    return len(records)


if __name__ == '__main__':
    import sys

    db = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'video' / '.data' / 'data' / 'datasets.db'
    print(f'{seed(db)} rows -> {db}')
