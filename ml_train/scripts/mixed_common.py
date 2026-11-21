"""Shared loading/evaluation helpers for mixed-corpus classifier experiments.

Every experiment uses the same sources, the same per-source holdout and the same metric
code, so a better number is evidence about the DATA rather than about a second split.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
SPLIT_SUFFIX = '.parquet'


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == '.parquet':
        return pd.read_parquet(path)
    if suffix == '.jsonl':
        return pd.read_json(path, lines=True)
    if suffix == '.json':
        return pd.read_json(path)
    if suffix == '.tsv':
        return pd.read_csv(path, sep='\t')
    return pd.read_csv(path)


def find_files(root: Path, split: str = '') -> list[Path]:
    files = [
        item
        for item in sorted(root.rglob('*'))
        if item.is_file() and item.suffix.lower() in {'.csv', '.parquet', '.json', '.jsonl', '.tsv'}
    ]
    if not split:
        return files
    return [item for item in files if split in item.name.lower()]


def pick_columns(frame: pd.DataFrame, text_names: tuple, label_names: tuple) -> tuple[str, str]:
    text = next((name for name in text_names if name in frame.columns), '')
    label = next((name for name in label_names if name in frame.columns), '')
    if not text or not label:
        raise ValueError(f'cannot find text/label among {list(frame.columns)}')
    return text, label


def binary_holdout(rows: list[dict], val_size: float) -> tuple[list[dict], list[dict]]:
    index = list(range(len(rows)))
    random.Random(SEED).shuffle(index)
    n_val = max(1, int(len(index) * val_size))
    val = [rows[i] for i in index[:n_val]]
    train = [rows[i] for i in index[n_val:]]
    return train, val


def metrics(truth: list[int], pred: list[int]) -> dict:
    truth_array = np.asarray(truth)
    pred_array = np.asarray(pred)
    accuracy = float((truth_array == pred_array).mean()) if len(truth_array) else 0.0
    f1s = []
    for cls in (0, 1):
        tp = int(((pred_array == cls) & (truth_array == cls)).sum())
        fp = int(((pred_array == cls) & (truth_array != cls)).sum())
        fn = int(((pred_array != cls) & (truth_array == cls)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return {'accuracy': round(accuracy, 4), 'f1_macro': round(float(np.mean(f1s)), 4), 'rows': len(truth)}


def predict(model_dir: str, texts: list[str], batch_size: int = 64, max_length: int = 128) -> list[int]:
    """Predict label ids with one HF directory; the model's own id2label decides the mapping."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(device).eval()
    out: list[int] = []
    with torch.no_grad():
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            enc = tokenizer(batch, truncation=True, max_length=max_length, padding=True, return_tensors='pt').to(device)
            logits = model(**enc).logits
            out.extend(int(item) for item in logits.argmax(dim=-1).tolist())
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return out


def save_report(report: dict, name: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{name}.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path
