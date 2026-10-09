"""Fine-tune a Chinese-base BERT for Weibo sentiment, so the sentiment node's ``bert``
mode can answer 正面/负面 at the accuracy the word-bag sklearn model cannot reach.

Run it on the machine that has the optional torch/transformers stack installed (they live in
requirements-optional.txt and are deliberately NOT in CI; sentiment.py's bert mode refuses
BY NAME when they are missing and never silently falls back). This script is standalone — it
reads only the CSVs beside it and writes an ordinary HuggingFace model directory, and it does
not import anything from backend/. Nothing in backend/ points at this file (AGENTS.md).

    # laptop, after installing a CUDA build of torch + transformers:
    .venv/Scripts/python.exe ml_train/scripts/train_sentiment_bert.py

What it produces, and why the analyzer needs no change:
    ml_train/models/sentiment_weibosenti_bin/   (config + tokenizer + weights + id2label)
    sentiment.py loads it with  pipeline('sentiment-analysis', model=<that path>)
    and _signed_polarity reads the label by substring, so id2label below uses the exact words
    it looks for — {0: 'negative', 1: 'positive'}. Fill the node's "bert 模型名" field with the
    absolute path to that directory and the bert mode runs on it.

Data (both are labelled 正/负 only — the third value 中性 is left to SnowNLP's thresholds,
by the user's decision; do not invent neutral rows here):
    weibo_senti_100k.csv   label 1 -> positive, 0 -> negative   (~100k, the default corpus)
    weibo_clean_265k.csv   label 0(喜悦) -> positive; 1(愤怒)/2(厌恶)/3(低落) -> negative
                             — 200k+ more, already jieba-tokenised with spaces; --with-clean adds
                             it (spaces are harmless to a subword tokenizer). Off by default: the
                             public set is cleaner, mixing is worth measuring before trusting.
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
ID2LABEL = {0: 'negative', 1: 'positive'}
LABEL2ID = {label: index for index, label in ID2LABEL.items()}
MAX_LENGTH = 128  # a Weibo post is short; 128 subwords covers it and keeps 8GB of VRAM safe.


def load_sentences(args):
    senti = pd.read_csv(os.path.join(DATA, 'weibo_senti_100k.csv'), usecols=['label', 'review'])
    texts = list(senti['review'].astype(str))
    labels = [int(x) for x in senti['label']]

    if args.with_clean:
        clean = pd.read_csv(os.path.join(DATA, 'weibo_clean_265k.csv'), usecols=['label', 'text'])
        # 0 喜悦 -> positive(1); 1/2/3 -> negative(0)
        texts += list(clean['text'].astype(str))
        labels += [1 if int(x) == 0 else 0 for x in clean['label']]

    keep = [(t, y) for t, y in zip(texts, labels, strict=True) if t.strip()]
    if args.limit:
        keep = keep[: args.limit]
    return [t for t, _ in keep], [y for _, y in keep]


def main():
    parser = argparse.ArgumentParser(description='Fine-tune a Chinese BERT for Weibo sentiment (positive/negative).')
    parser.add_argument(
        '--base', default='hfl/chinese-roberta-wwm-ext', help='HF base model name or path (base ~100M fits 8GB VRAM)'
    )
    parser.add_argument('--out', default=os.path.join(MODELS, 'sentiment_weibosenti_bin'))
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=16, help='per device; 16 at fp16 stays under 8GB')
    parser.add_argument('--grad-accum', type=int, default=2)
    parser.add_argument('--lr', type=float, default=2e-5)
    parser.add_argument('--with-clean', action='store_true', help='also fold in datasets/weibo_clean_265k.csv')
    parser.add_argument('--val-size', type=float, default=0.05)
    parser.add_argument(
        '--limit', type=int, default=0, help='use only the first N rows (0=all) — pre-flight the whole code path fast'
    )
    args = parser.parse_args()

    texts, labels = load_sentences(args)
    print(f'{len(texts)} rows; class balance {np.bincount(labels).tolist()} -> {dict(ID2LABEL)}')

    index = list(range(len(texts)))
    random.Random(SEED).shuffle(index)
    n_val = max(1, int(len(index) * args.val_size))
    val_idx, train_idx = index[:n_val], index[n_val:]

    tokenizer = AutoTokenizer.from_pretrained(args.base)

    def encode(rows):
        feats = tokenizer([texts[i] for i in rows], truncation=True, max_length=MAX_LENGTH, padding=False)
        feats['labels'] = [labels[i] for i in rows]
        return feats

    def to_dataset(rows):
        enc = encode(rows)
        return [{k: enc[k][i] for k in enc} for i in range(len(rows))]

    # A tiny metrics fn so Trainer logs accuracy + macro-F1 on the held-out slice every eval.
    def compute_metrics(eval_pred):
        logits, y = eval_pred
        pred = np.argmax(logits, axis=1)
        acc = float((pred == y).mean())
        f1s = []
        for c in (0, 1):
            tp = int(((pred == c) & (y == c)).sum())
            fp = int(((pred == c) & (y != c)).sum())
            fn = int(((pred != c) & (y == c)).sum())
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        return {'accuracy': acc, 'f1_macro': float(np.mean(f1s))}

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=2, id2label=ID2LABEL, label2id=LABEL2ID
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
        fp16=True,  # half precision: an 8GB laptop fits a base model at batch 16
        eval_strategy='epoch',
        save_strategy='epoch',
        load_best_model_at_end=True,
        metric_for_best_model='f1_macro',
        logging_steps=100,
        report_to='none',  # no wandb: a laptop run must not require an external tracker
    )

    train_dataset = to_dataset(train_idx)
    val_dataset = to_dataset(val_idx)
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        # encode() left padding=False (variable length) to save memory; this pads each batch
        # to its own longest row — the default collator would instead choke on ragged rows.
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        # transformers 5 renamed Trainer's `tokenizer=` to `processing_class=`.
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
    print('Now set the sentiment node to mode "bert" and paste that path as its model name.')


SEED = 42


if __name__ == '__main__':
    main()
