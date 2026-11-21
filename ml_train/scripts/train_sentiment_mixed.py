"""Fine-tune a binary Chinese sentiment model on the OLD corpus plus the NEW sources.

The deployed checkpoints were trained on weibo_senti_100k (and optionally the noisy 265k
clean set). This experiment adds ChnSentiCorp, JDReview, OnlineShopping and waimai, keeps a
per-source holdout, and scores BOTH the old deployed model and the new one on the same rows.
It writes to a NEW folder by default; the old checkpoints are backed up separately by
``backup_assets.py`` (verify with ``--verify`` before trusting the backup).

    .venv/Scripts/python.exe ml_train/scripts/train_sentiment_mixed.py
    .venv/Scripts/python.exe ml_train/scripts/train_sentiment_mixed.py --base hfl/chinese-roberta-wwm-ext

Nothing in backend/ imports this script; the analyzer only sees the resulting HF folder.
"""

import argparse
import os
import random
import time
from pathlib import Path

import _env
import numpy as np
import pandas as pd
from mixed_common import SEED, binary_holdout, find_files, metrics, pick_columns, predict, read_table, save_report
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'datasets')
MODELS = os.path.join(ROOT, 'models')
SENTIMENT_DIR = os.path.join(DATA, 'classification', 'sentiment')
ID2LABEL = {0: 'negative', 1: 'positive'}
LABEL2ID = {value: key for key, value in ID2LABEL.items()}
MAX_LENGTH = 128


def _weibo() -> list[dict]:
    frame = pd.read_csv(os.path.join(DATA, 'weibo_senti_100k.csv'), usecols=['label', 'review'])
    return [
        {'text': str(text), 'label': int(label), 'source': 'weibo'}
        for text, label in zip(frame['review'], frame['label'], strict=True)
        if str(text).strip()
    ]


def _source_rows(name: str, text_col: str, label_col: str, polarities: dict[int, int]) -> list[dict]:
    """Rows of one external source, with the source's own label spelling folded to 0/1."""
    root = os.path.join(SENTIMENT_DIR, name)
    rows = []
    for path in find_files(Path(root), 'train'):
        frame = read_table(path)
        text_name, label_name = pick_columns(frame, (text_col,), (label_col,))
        for text, label in zip(frame[text_name], frame[label_name], strict=True):
            text = str(text).strip()
            if not text:
                continue
            try:
                raw = int(label)
            except (TypeError, ValueError):
                continue
            if raw in polarities:
                rows.append({'text': text, 'label': polarities[raw], 'source': name})
    return rows


def _external_test(name: str, text_col: str, label_col: str, polarities: dict[int, int]) -> list[dict]:
    root = os.path.join(SENTIMENT_DIR, name)
    rows = []
    for path in find_files(Path(root), 'test'):
        frame = read_table(path)
        text_name, label_name = pick_columns(frame, (text_col,), (label_col,))
        for text, label in zip(frame[text_name], frame[label_name], strict=True):
            text = str(text).strip()
            try:
                raw = int(label)
            except (TypeError, ValueError):
                continue
            if text and raw in polarities:
                rows.append({'text': text, 'label': polarities[raw], 'source': name})
    return rows


def collect() -> tuple[list[dict], dict[str, list[dict]]]:
    """Training rows plus a per-source external test set; label maps are explicit evidence."""
    # 1 = positive / 0 = negative for these sources; JDReview names 0=POS.
    sources = {
        'chnsenticorp_8k': ('text', 'label', {0: 0, 1: 1}),
        'jd_review': ('text', 'label', {0: 1, 1: 0}),
        'online_shopping': ('text', 'label', {0: 0, 1: 1}),
        'waimai': ('text', 'label', {0: 0, 1: 1}),
    }
    rows = _weibo()
    tests = {}
    for name, (text_col, label_col, polarities) in sources.items():
        extra = _source_rows(name, text_col, label_col, polarities)
        rows += extra
        tests[name] = _external_test(name, text_col, label_col, polarities)
        print(f'{name}: {len(extra)} train rows, {len(tests[name])} test rows')
    return rows, tests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='hfl/rbt3', help='HF base model or path')
    parser.add_argument('--out', default=os.path.join(MODELS, 'sentiment_mixed_v1'))
    parser.add_argument('--baseline', default=os.path.join(MODELS, 'sentiment_rbt3'))
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--grad-accum', type=int, default=1)
    parser.add_argument('--lr', type=float, default=2e-5)
    parser.add_argument('--val-size', type=float, default=0.05)
    parser.add_argument('--max-weibo', type=int, default=100000)
    parser.add_argument('--limit', type=int, default=0, help='pre-flight only: first N total rows')
    args = parser.parse_args()

    rows, tests = collect()
    weibo = [row for row in rows if row['source'] == 'weibo'][: args.max_weibo]
    others = [row for row in rows if row['source'] != 'weibo']
    if args.limit:
        weibo, others = weibo[: args.limit], others[: args.limit]
    per_source: dict[str, list[dict]] = {}
    for row in weibo + others:
        per_source.setdefault(row['source'], []).append(row)
    train_rows, val_rows = [], []
    for name, group in per_source.items():
        train, val = binary_holdout(group, args.val_size)
        train_rows += train
        val_rows += val
        counts = np.bincount([row['label'] for row in group], minlength=2).tolist()
        print(f'{name}: {len(group)} rows, balance {dict(zip(ID2LABEL.values(), counts, strict=True))}')

    random.Random(SEED).shuffle(train_rows)
    print(f'train={len(train_rows)} val={len(val_rows)}')

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=2, id2label=ID2LABEL, label2id=LABEL2ID
    )

    def to_dataset(items):
        enc = tokenizer([row['text'] for row in items], truncation=True, max_length=MAX_LENGTH, padding=False)
        enc['labels'] = [row['label'] for row in items]
        return [{key: enc[key][i] for key in enc} for i in range(len(items))]

    def compute_metrics(eval_pred):
        logits, truth = eval_pred
        predicted = np.argmax(logits, axis=1)
        result = metrics(list(truth), list(predicted))
        return {'accuracy': result['accuracy'], 'f1_macro': result['f1_macro']}

    training_args = TrainingArguments(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size * 2,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        warmup_ratio=0.1,
        weight_decay=0.01,
        fp16=True,
        eval_strategy='epoch',
        save_strategy='epoch',
        load_best_model_at_end=True,
        metric_for_best_model='f1_macro',
        logging_steps=200,
        report_to='none',
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=to_dataset(train_rows),
        eval_dataset=to_dataset(val_rows),
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
    )
    started = time.time()
    trainer.train()
    print(f'fine-tuned in {(time.time() - started) / 60:.1f} min')
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f'saved -> {args.out}')
    # Free the trainer's copy before loading the baseline and the new model in predict().
    import torch

    del trainer, model
    torch.cuda.empty_cache()

    holdout = {
        'mixed_holdout': val_rows,
        **{name: rows for name, rows in tests.items() if rows},
    }
    report = {'schema': 1, 'base': args.base, 'out': args.out, 'epochs': args.epochs, 'sources': {}}
    for name, items in holdout.items():
        truth = [row['label'] for row in items]
        texts = [row['text'] for row in items]
        report['sources'][name] = {'rows': len(items)}
        candidates = {'new': args.out}
        if os.path.isdir(args.baseline):
            candidates['baseline'] = args.baseline
        for candidate, path in candidates.items():
            try:
                predicted = predict(path, texts)
                report['sources'][name][candidate] = metrics(truth, predicted)
            except Exception as exc:
                report['sources'][name][candidate] = {'error': f'{type(exc).__name__}: {exc}'}
        print(name, report['sources'][name])
    report_path = save_report(report, 'sentiment_mixed', Path(_env.LOGS_DIR) / 'mixed_train')
    print(f'report={report_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
