"""Fine-tune a Chinese-base BERT for the emotion node's ``bert`` mode, on the project's
SMP2020-EWECT six-class emotion scheme (Anger / Fear / Joy / Neutral / Sadness / Surprise).

Standalone and project-local, exactly like train_sentiment_bert.py: it reads only the SMP2020-EWECT
JSON beside it, writes an ordinary HuggingFace model directory, and imports nothing from
backend/. Nothing in backend/ points at this file (AGENTS.md). torch/transformers/accelerate
are the optional stack (requirements-optional); the emotion analyzer's bert mode refuses BY
NAME when they are missing and never falls back to the LLM or sklearn path.

    # laptop, CUDA torch + transformers + accelerate installed:
    .venv/Scripts/python.exe ml_train/scripts/train_emotion_bert.py

Why the analyzer needs no label change:
    ml_train/models/emotion_ewect_six/   (config + tokenizer + weights + id2label)
    emotion.py loads it with  pipeline('text-classification', model=<that path>)
    and reads the argmax label directly, so id2label below uses the SAME strings as
    EmotionAnalyzer.valid_labels — see EMOTION_LABELS, which mirrors that list.

Data (SMP2020-EWECT, general-Weibo track):
    train/usual_train.txt            27,768 rows, JSON [{id, content, label}], the corpus
    eval（刷榜数据集）/usual_eval_labeled.txt   2,000 official labelled rows, scored as a
                                     true held-out after training (skipped if absent)
    The dataset's labels are lowercase English (happy/angry/sad/fear/surprise/neutral);
    SMP2PROJECT folds them onto the project's capitalized display names so the model and
    the analyzer speak one vocabulary. ``--with-virus`` adds the pandemic track if wanted
    (it is a different topic distribution, so it is off by default — mix only after measuring).
"""

import argparse
import json
import os
import random
import time

import numpy as np

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

SMP_DIR = os.path.join(DATA, 'ewect_smp2020')

# The six categories the emotion node answers, in a FIXED order so id2label is reproducible
# across re-trains. This list must stay equal to EmotionAnalyzer.valid_labels.
EMOTION_LABELS = ['Anger', 'Fear', 'Joy', 'Neutral', 'Sadness', 'Surprise']
ID2LABEL = {i: name for i, name in enumerate(EMOTION_LABELS)}
LABEL2ID = {name: i for i, name in enumerate(EMOTION_LABELS)}
# The dataset spells its labels in lowercase English; fold them onto the project's names.
SMP2PROJECT = {
    'angry': 'Anger',
    'fear': 'Fear',
    'happy': 'Joy',
    'neutral': 'Neutral',
    'sad': 'Sadness',
    'surprise': 'Surprise',
}
MAX_LENGTH = 128  # a Weibo post is short; 128 subwords covers it and keeps 8GB of VRAM safe.
SEED = 42


def load_records(paths):
    """Read the SMP JSON files into (texts, labels), dropping anything with no usable label.

    Each file is a JSON array of ``{id, content, label}``. A row whose label is not in
    SMP2PROJECT (the confused/``None`` rows the task adds to the published test sets) is
    skipped rather than guessed — an unmapped label would silently renumber the whole class.
    """
    texts, labels = [], []
    for path in paths:
        with open(path, encoding='utf-8') as fh:
            rows = json.load(fh)
        for row in rows:
            content = str(row.get('content') or '').strip()
            label = SMP2PROJECT.get(str(row.get('label') or '').strip().lower())
            if content and label:
                texts.append(content)
                labels.append(label)
    return texts, labels


def main():
    parser = argparse.ArgumentParser(description='Fine-tune a Chinese BERT for the SMP 6-class emotion scheme.')
    parser.add_argument(
        '--base', default='hfl/chinese-roberta-wwm-ext', help='HF base model name or path (base ~100M fits 8GB VRAM)'
    )
    parser.add_argument('--out', default=os.path.join(MODELS, 'emotion_ewect_six'))
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=16, help='per device; 16 at fp16 stays under 8GB')
    parser.add_argument('--grad-accum', type=int, default=2)
    parser.add_argument('--lr', type=float, default=2e-5)
    parser.add_argument('--with-virus', action='store_true', help='also fold in the pandemic (virus) train track')
    parser.add_argument('--val-size', type=float, default=0.05)
    parser.add_argument(
        '--limit', type=int, default=0, help='use only the first N rows (0=all) — pre-flight the whole code path fast'
    )
    args = parser.parse_args()

    train_paths = [os.path.join(SMP_DIR, 'train', 'usual_train.txt')]
    if args.with_virus:
        train_paths.append(os.path.join(SMP_DIR, 'train', 'virus_train.txt'))
    texts, label_names = load_records(train_paths)
    if args.limit:
        texts, label_names = texts[: args.limit], label_names[: args.limit]
    label_ids = [LABEL2ID[name] for name in label_names]
    counts = np.bincount(label_ids, minlength=len(EMOTION_LABELS)).tolist()
    print(f'{len(texts)} rows; class balance {dict(zip(EMOTION_LABELS, counts))}')

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

    # Macro-F1 over all six classes + accuracy, logged every eval and used to pick the best epoch.
    def compute_metrics(eval_pred):
        logits, y = eval_pred
        pred = np.argmax(logits, axis=1)
        acc = float((pred == y).mean())
        f1s = []
        for c in range(len(EMOTION_LABELS)):
            tp = int(((pred == c) & (y == c)).sum())
            fp = int(((pred == c) & (y != c)).sum())
            fn = int(((pred != c) & (y == c)).sum())
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        return {'accuracy': acc, 'f1_macro': float(np.mean(f1s))}

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=len(EMOTION_LABELS), id2label=ID2LABEL, label2id=LABEL2ID
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

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=to_dataset(train_idx),
        eval_dataset=to_dataset(val_idx),
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
    print(f'held-out(split): accuracy={metrics["eval_accuracy"]:.4f}  macro-F1={metrics["eval_f1_macro"]:.4f}')

    # A second, honest number on the official labelled validation set, if it is on disk. The
    # split held-out came from the same file we trained the shuffle of; this one did not.
    official = os.path.join(SMP_DIR, 'eval（刷榜数据集）', 'usual_eval_labeled.txt')
    if os.path.isfile(official):
        o_texts, o_label_names = load_records([official])
        if o_texts:
            o_rows = list(range(len(o_texts)))
            o_ids = [LABEL2ID[name] for name in o_label_names]
            enc = tokenizer([t for t in o_texts], truncation=True, max_length=MAX_LENGTH, padding=False)
            enc['labels'] = o_ids
            o_ds = [{k: enc[k][i] for k in enc} for i in o_rows]
            om = trainer.evaluate(o_ds)
            print(
                f'official eval ({len(o_ds)} rows): accuracy={om["eval_accuracy"]:.4f}  macro-F1={om["eval_f1_macro"]:.4f}'
            )

    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f'saved HF model -> {args.out}')
    print('Now set the emotion node to mode "bert" and paste that path as its model name.')


if __name__ == '__main__':
    main()
