"""Fine-tune a Chinese-base BERT for the tendency node's ``bert`` mode, on the LLM-distilled
six-class stance corpus (Objective Statement / Praise/Affirmation / Criticism/Questioning /
Controversy/Reflection / Advocacy/Call-to-action / Satire/Mockery).

Standalone and project-local, like train_sentiment_bert.py / train_emotion_bert.py: it reads only the
distilled CSV beside it, writes an ordinary HuggingFace model directory, and imports nothing
from backend/. The distilled corpus comes from ml_train/scripts/distill_tendency_labels.py — because tendency
has no public dataset, its labels are the node's OWN llm path, so the bert mode learns the exact
taxonomy the analyzer reads.

    # laptop, after distill_tendency_labels.py has produced ml_train/datasets/tendency_distilled.csv:
    .venv/Scripts/python.exe ml_train/scripts/train_tendency_bert_v1.py

Why the analyzer needs no label change:
    ml_train/models/tendency_stance_v1/   (config + tokenizer + weights + id2label)
    tendency.py loads it with  pipeline('text-classification', model=<that path>)
    and reads the argmax label directly, so id2label below uses the SAME strings as
    TendencyAnalyzer.valid_labels. They contain spaces and slashes — fine as HF label names;
    the analyzer matches the returned label against its set, not by substring.
"""

import argparse
import os
import random
import time

import numpy as np
import pandas as pd

os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')

from transformers import (  # noqa: E402  (env var above must precede the import)
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
DATA = os.path.join(ROOT, 'datasets')
MODELS = os.path.join(ROOT, 'models')
# Keep every downloaded artifact inside the project, never the C: user cache (~/.cache/huggingface).
os.environ.setdefault('HF_HOME', os.path.join(ROOT, '.hf-cache'))

# A FIXED order so id2label is reproducible across re-trains; these are the analyzer's own labels.
TENDENCY_LABELS = [
    'Advocacy/Call-to-action',
    'Controversy/Reflection',
    'Criticism/Questioning',
    'Objective Statement',
    'Praise/Affirmation',
    'Satire/Mockery',
]
ID2LABEL = {i: name for i, name in enumerate(TENDENCY_LABELS)}
LABEL2ID = {name: i for i, name in enumerate(TENDENCY_LABELS)}
MAX_LENGTH = 128  # a Weibo comment is short; 128 subwords keeps 8GB of VRAM safe.
SEED = 42


def load_rows(in_csv):
    df = pd.read_csv(in_csv, usecols=['text', 'tendency'])
    keep = [(str(t).strip(), lab) for t, lab in zip(df['text'], df['tendency'], strict=True) if str(t).strip()]
    keep = [(t, lab) for t, lab in keep if lab in LABEL2ID]  # a stray label is dropped, never guessed
    return [t for t, _ in keep], [lab for _, lab in keep]


def main():
    parser = argparse.ArgumentParser(description='Fine-tune a Chinese BERT for the six-class tendency scheme.')
    parser.add_argument('--in', dest='in_csv', default=os.path.join(DATA, 'tendency_distilled.csv'))
    parser.add_argument('--base', default='hfl/chinese-roberta-wwm-ext')
    parser.add_argument('--out', default=os.path.join(MODELS, 'tendency_stance_v1'))
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=16, help='per device; 16 at fp16 stays under 8GB')
    parser.add_argument('--grad-accum', type=int, default=2)
    parser.add_argument('--lr', type=float, default=2e-5)
    parser.add_argument('--val-size', type=float, default=0.05)
    parser.add_argument(
        '--limit', type=int, default=0, help='use only the first N rows (0=all) — pre-flight the whole code path fast'
    )
    parser.add_argument(
        '--balance',
        action='store_true',
        help='subsample every class down to the smallest class count — lifts macro-F1 when one stance dominates',
    )
    args = parser.parse_args()

    texts, label_names = load_rows(args.in_csv)
    if args.limit:
        texts, label_names = texts[: args.limit], label_names[: args.limit]
    label_ids = [LABEL2ID[name] for name in label_names]
    counts = np.bincount(label_ids, minlength=len(TENDENCY_LABELS)).tolist()
    print(f'{len(texts)} rows; class balance {dict(zip(TENDENCY_LABELS, counts))}')
    if len(set(label_ids)) < len(TENDENCY_LABELS):
        print('  WARNING: not all six classes are present; macro-F1 will understate the missing ones')

    if args.balance:
        # Trim the majority (mostly Objective Statement) to the smallest class, so the loss is
        # not dominated by one stance and macro-F1 reflects all six. Costs rows, buys balance.
        by_class: dict[int, list[int]] = {}
        for i, lab in enumerate(label_ids):
            by_class.setdefault(lab, []).append(i)
        keep_n = min(len(v) for v in by_class.values())
        rng = random.Random(SEED)
        kept = sorted(idx for v in by_class.values() for idx in (rng.sample(v, keep_n) if len(v) > keep_n else v))
        texts = [texts[i] for i in kept]
        label_names = [label_names[i] for i in kept]
        label_ids = [label_ids[i] for i in kept]
        counts = np.bincount(label_ids, minlength=len(TENDENCY_LABELS)).tolist()
        print(f'balanced to {keep_n} per class; now {len(texts)} rows {dict(zip(TENDENCY_LABELS, counts))}')

    index = list(range(len(texts)))
    random.Random(SEED).shuffle(index)
    n_val = max(1, int(len(index) * args.val_size))
    val_idx, train_idx = index[:n_val], index[n_val:]

    tokenizer = AutoTokenizer.from_pretrained(args.base)

    def encode(rows):
        feats = tokenizer([texts[i] for i in rows], truncation=True, max_length=MAX_LENGTH, padding=False)
        feats['labels'] = [label_ids[i] for i in rows]
        return feats

    def to_dataset(rows):
        enc = encode(rows)
        return [{k: enc[k][i] for k in enc} for i in range(len(rows))]

    def compute_metrics(eval_pred):
        logits, y = eval_pred
        pred = np.argmax(logits, axis=1)
        acc = float((pred == y).mean())
        f1s = []
        for c in range(len(TENDENCY_LABELS)):
            tp = int(((pred == c) & (y == c)).sum())
            fp = int(((pred == c) & (y != c)).sum())
            fn = int(((pred != c) & (y == c)).sum())
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        return {'accuracy': acc, 'f1_macro': float(np.mean(f1s))}

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=len(TENDENCY_LABELS), id2label=ID2LABEL, label2id=LABEL2ID
    )

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
        logging_steps=100,
        report_to='none',
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=to_dataset(train_idx),
        eval_dataset=to_dataset(val_idx),
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
    )

    start = time.time()
    trainer.train()
    metrics = trainer.evaluate()
    print(f'\nfine-tuned in {(time.time() - start) / 60:.1f} min')
    print(f'held-out: accuracy={metrics["eval_accuracy"]:.4f}  macro-F1={metrics["eval_f1_macro"]:.4f}')

    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f'saved HF model -> {args.out}')
    print('Now set the tendency node to mode "bert" and paste that path as its model name.')


if __name__ == '__main__':
    main()
