"""Self-training (pseudo-labelling) for the tendency classifier — uses the UNLABELLED real corpus.

Round: train on the labelled corpus → predict the unlabelled pool → keep only high-confidence
pseudo-labels → retrain on labelled-train + pseudo → evaluate on the SAME fixed real-labelled val
split. Because the pseudo rows enter TRAIN only and the eval set is unchanged real labels, the
before/after macro-F1 is a fair comparison (the model is not grading its own output).

Honest caveat: pseudo-labels can amplify the model's own mistakes (esp. the fuzzy Controversy class),
so the confidence threshold is high by default and the real gain should still be confirmed on the
human holdout later.

    .venv/Scripts/python.exe ml_train/scripts/selftrain_tendency.py --unlabeled-n 10000 --thr 0.9

Reuses train_bert_tendency_v2's labels + WeightedTrainer so the taxonomy and the class-weighted loss
are identical to the comparison runs.
"""

import argparse
import os
import random

os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
DATA = os.path.join(ROOT, 'datasets')
os.environ.setdefault('HF_HOME', os.path.join(ROOT, '.hf-cache'))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import torch  # noqa: E402
from train_tendency_bert_v2 import (  # noqa: E402
    ID2LABEL,
    LABEL2ID,
    MAX_LENGTH,
    SEED,
    TENDENCY_LABELS,
    WeightedTrainer,
)
from transformers import (  # noqa: E402
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    TrainingArguments,
)


def macro_metrics(eval_pred):
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
    return {'accuracy': acc, 'f1_macro': float(np.mean(f1s)), 'f1_controversy': f1s[LABEL2ID['Controversy/Reflection']]}


def build_ds(tokenizer, texts, labels):
    if not texts:
        return []
    enc = tokenizer(texts, truncation=True, max_length=MAX_LENGTH, padding=False)
    enc['labels'] = labels
    return [{k: enc[k][i] for k in enc} for i in range(len(texts))]


def train_model(base, tokenizer, train_rows, val_rows, class_weights, epochs, lr):
    model = AutoModelForSequenceClassification.from_pretrained(
        base, num_labels=len(TENDENCY_LABELS), id2label=ID2LABEL, label2id=LABEL2ID
    ).float()
    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    args = TrainingArguments(
        output_dir=os.path.join(HERE, '_st_out'),
        num_train_epochs=epochs,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=32,
        gradient_accumulation_steps=2,
        learning_rate=lr,
        warmup_ratio=0.1,
        weight_decay=0.01,
        bf16=use_bf16,
        fp16=not use_bf16,
        eval_strategy='epoch',
        save_strategy='epoch',
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model='f1_macro',
        logging_steps=200,
        report_to='none',
    )
    trainer = WeightedTrainer(
        class_weights=class_weights,
        model=model,
        args=args,
        train_dataset=train_rows,
        eval_dataset=val_rows,
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        processing_class=tokenizer,
        compute_metrics=macro_metrics,
    )
    trainer.train()  # actually fit — constructing alone leaves the model untrained
    return trainer


def main():
    ap = argparse.ArgumentParser(description='Self-training with pseudo-labels over the unlabelled pool.')
    ap.add_argument('--corpus', default=os.path.join(DATA, 'tendency_distilled.csv'))
    ap.add_argument('--pool', default=os.path.join(DATA, 'weibo_clean_265k.csv'))
    ap.add_argument('--base', default='hfl/chinese-roberta-wwm-ext')
    ap.add_argument('--unlabeled-n', type=int, default=10000)
    ap.add_argument('--thr', type=float, default=0.9)
    ap.add_argument('--epochs', type=int, default=3)
    ap.add_argument('--lr', type=float, default=2e-5)
    args = ap.parse_args()

    df = pd.read_csv(args.corpus, usecols=['text', 'tendency'])
    df = df[df['tendency'].isin(LABEL2ID)]
    texts = df['text'].astype(str).str.strip().tolist()
    labels = [LABEL2ID[t] for t in df['tendency']]
    index = list(range(len(texts)))
    random.Random(SEED).shuffle(index)
    n_val = max(1, int(len(index) * 0.05))
    val_idx, train_idx = index[:n_val], index[n_val:]
    counts = np.bincount([labels[i] for i in train_idx], minlength=len(TENDENCY_LABELS)).tolist()
    freq = np.array(counts, dtype=float)
    freq[freq == 0] = 1.0
    w = (1.0 / freq) / (1.0 / freq).mean()
    class_weights = torch.tensor(w, dtype=torch.float32)

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    lab_train = build_ds(tokenizer, [texts[i] for i in train_idx], [labels[i] for i in train_idx])
    lab_val = build_ds(tokenizer, [texts[i] for i in val_idx], [labels[i] for i in val_idx])

    print('=== round 0: baseline (labelled only) ===', flush=True)
    tr0 = train_model(args.base, tokenizer, lab_train, lab_val, class_weights, args.epochs, args.lr)
    b = tr0.evaluate()
    print(f'BASELINE  macro-F1={b["eval_f1_macro"]:.4f}  Controversy F1={b["eval_f1_controversy"]:.4f}', flush=True)

    # Unlabelled pool = pool texts not already in the corpus.
    pool = pd.read_csv(args.pool, usecols=['text'])['text'].astype(str).str.strip()
    have = set(texts)
    todo = [t for t in pool if t and t not in have and len(t) >= 4]
    random.Random(SEED).shuffle(todo)
    todo = todo[: args.unlabeled_n]
    print(f'=== pseudo-labelling {len(todo)} unlabelled texts (thr={args.thr}) ===', flush=True)
    pred_ds = build_ds(tokenizer, todo, [0] * len(todo))
    out = tr0.predict(pred_ds)
    probs = torch.softmax(torch.tensor(out.predictions), dim=-1).numpy()
    conf = probs.max(axis=1)
    argmax = probs.argmax(axis=1)
    pseudo = [(todo[i], int(argmax[i])) for i in range(len(todo)) if conf[i] >= args.thr]
    kept = np.bincount([p[1] for p in pseudo], minlength=len(TENDENCY_LABELS)).tolist() if pseudo else [0] * 6
    print(
        f'kept {len(pseudo)}/{len(todo)} confident pseudo-labels; by class {dict(zip(TENDENCY_LABELS, kept))}',
        flush=True,
    )

    st_train = lab_train + build_ds(tokenizer, [t for t, _ in pseudo], [c for _, c in pseudo])
    print('=== round 1: self-trained (labelled + pseudo, eval on same real val) ===', flush=True)
    tr1 = train_model(args.base, tokenizer, st_train, lab_val, class_weights, args.epochs, args.lr)
    s = tr1.evaluate()
    print(f'SELFTRAIN macro-F1={s["eval_f1_macro"]:.4f}  Controversy F1={s["eval_f1_controversy"]:.4f}', flush=True)
    print(
        f'\nDELTA vs baseline:  macro-F1 {s["eval_f1_macro"] - b["eval_f1_macro"]:+.4f}  '
        f'Controversy F1 {s["eval_f1_controversy"] - b["eval_f1_controversy"]:+.4f}'
    )
    print('noise floor ~±0.011 — only deltas clearly above that are real.')


if __name__ == '__main__':
    main()
