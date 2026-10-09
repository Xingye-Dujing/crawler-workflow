"""INDEPENDENT second attempt at the six-class tendency classifier — a MODERN Chinese encoder,
class-weighted loss, and an honest human-labelled holdout. This file does NOT replace or import
``train_tendency_bert_v1.py``; the old Chinese-RoBERTa track stays exactly as it was, writes to its own
``models/tendency_stance_v1/``, and stays selectable. This one writes to ``models/tendency_stance_v2_cyberbully/``
(「网暴模型」, registered for the 「已注册模型」 dropdown).
The two are chosen at deploy time from the tendency node's 「已注册模型」 dropdown, or by pasting
its ``ml_train/models/…`` path into 「bert 模型名」 — the analyzer takes a path, so nothing in backend/ changes.

Why a separate track (the three decisions this encodes):
  ① modern *Chinese* encoder instead of ``hfl/chinese-roberta-wwm-ext`` (2019). Default is
     ``thenlper/gte-base-zh`` (Alibaba DAMO, 2023, BERT-framework, base-size → fits 8GB). Other
     ``--base`` values worth comparing are listed in the ``--base`` help.
  ② class weights first (cheap, no new data): ``--class-weights`` up-weights the rare
     Controversy/Reflection in the loss. Only if that is not enough do you synthesize more
     Controversy rows with Qwen — and you validate the whole thing on a HUMAN holdout, not the
     distilled labels (the old 0.681 is measured on Qwen's own labels, so it scores imitation).
  ③ NO English ModernBERT — ``answerdotai/ModernBERT-*`` and ``Alibaba-NLP/gte-modernbert-base``
     are English-tokenized and fail on Chinese. A genuine *Chinese* ModernBERT
     (``feynmanzhao/chinese-modernbert-large-wwm``) is a legitimate ``--base`` candidate, but it is
     large → drop ``--batch-size`` to 8 and raise ``--grad-accum`` to stay under 8GB.

    # 1. build a human-label template (stratified per class) and hand-correct it:
    .venv/Scripts/python.exe ml_train/scripts/make_holdout.py
    # 2. modern base + class weights, honest eval on the human holdout:
    .venv/Scripts/python.exe ml_train/scripts/train_tendency_bert_v2.py \
        --class-weights --holdout ml_train/datasets/tendency_holdout_labeled.csv
    # 3. same but a large modern encoder (VRAM-tuned):
    .venv/Scripts/python.exe ml_train/scripts/train_tendency_bert_v2.py \
        --base feynmanzhao/chinese-modernbert-large-wwm --batch-size 8 --grad-accum 4 \
        --class-weights --holdout ml_train/datasets/tendency_holdout_labeled.csv
"""

import argparse
import json
import os
import random
import time

import numpy as np
import pandas as pd
import torch

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

# The SAME fixed label order as the old track and the analyzer — id2label must match TendencyAnalyzer.valid_labels.
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


def load_labeled(csv_path, text_col='text', label_col='tendency'):
    """Read (text, label) pairs, dropping blanks and any label outside the six — a stray is never guessed."""
    df = pd.read_csv(csv_path, usecols=[text_col, label_col])
    out = []
    for text, lab in zip(df[text_col], df[label_col], strict=True):
        text = str(text).strip()
        if text and str(lab).strip() in LABEL2ID:
            out.append((text, str(lab).strip()))
    return out


class WeightedTrainer(Trainer):
    """A Trainer that can swap the default CE for class-weighted CE, or a class-weighted focal loss.

    ``--balance`` (subsample) and class weights are two answers to the same imbalance; weights add
    no data loss, so they are tried first. ``--loss focal`` further down-weights the already-easy
    examples (by ``(1 - p_true)^gamma``) so the rare, confusable Controversy class dominates the
    gradient — the cheap next lever if class weights alone do not lift it enough.
    """

    def __init__(self, class_weights=None, focal_gamma=None, soft_alpha=None, soft_temp=2.0, **kwargs):
        super().__init__(**kwargs)
        self._class_weights = class_weights
        self._focal_gamma = focal_gamma
        self._soft_alpha = soft_alpha
        self._soft_temp = soft_temp

    def _hard_loss(self, logits, labels, weight):
        if self._focal_gamma is not None:
            logp = torch.nn.functional.log_softmax(logits, dim=-1)
            ce = torch.nn.functional.nll_loss(logp, labels, reduction='none')  # per-sample, unweighted
            p_true = logp.gather(1, labels.unsqueeze(1)).squeeze(1).exp()
            focal = ((1.0 - p_true) ** self._focal_gamma) * ce
            if weight is not None:
                w = weight[labels]
                return (focal * w).sum() / w.sum()
            return focal.mean()
        return torch.nn.functional.cross_entropy(logits, labels, weight=weight)

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop('labels')
        soft = inputs.pop('soft', None)
        outputs = model(**inputs)
        logits = outputs.logits
        weight = self._class_weights.to(logits.device) if self._class_weights is not None else None
        hard = self._hard_loss(logits, labels, weight)
        if soft is not None and self._soft_alpha is not None:
            t = self._soft_temp or 2.0
            logq = torch.nn.functional.log_softmax(logits / t, dim=-1)
            soft_term = -(soft.to(logits.device) * logq).sum(dim=1).mean() * (t * t)
            loss = self._soft_alpha * hard + (1.0 - self._soft_alpha) * soft_term
        else:
            loss = hard
        return (loss, outputs) if return_outputs else loss


def load_soft(soft_csv):
    """Map each text -> its 6-class teacher distribution, in TENDENCY_LABELS order."""
    sdf = pd.read_csv(soft_csv)
    prob_cols = [f'prob_{l}' for l in TENDENCY_LABELS]
    missing = [c for c in prob_cols if c not in sdf.columns]
    if missing:
        raise ValueError(f'soft csv missing columns: {missing}')
    out = {}
    for text, *probs in zip(sdf['text'].astype(str), *[sdf[c] for c in prob_cols], strict=True):
        vec = [float(p) for p in probs]
        s = sum(vec) or 1.0
        out[text.strip()] = [v / s for v in vec]  # renormalise (draws may have summed < k on errors)
    return out


class SoftCollator:
    """Pads the token features with the tokenizer and stacks each row's teacher vector as `soft`."""

    def __init__(self, tokenizer):
        self.base = DataCollatorWithPadding(tokenizer=tokenizer)

    def __call__(self, features):
        soft = torch.tensor([f['soft'] for f in features], dtype=torch.float)
        batch = self.base([{k: v for k, v in f.items() if k != 'soft'} for f in features])
        batch['soft'] = soft
        return batch


def report_confusion(trainer, dataset, title):
    """Print a rows=true / cols=pred matrix and the top confusable pairs — this is what tells you
    whether the weak class is a capacity problem or a label-boundary problem (Controversy bleeding
    into Criticism/Satire means the latter, and more data/more model will not fix it)."""
    out = trainer.predict(dataset)
    pred = np.argmax(out.predictions, axis=1)
    y = np.asarray(out.label_ids)
    n = len(TENDENCY_LABELS)
    m = np.zeros((n, n), dtype=int)
    for t, p in zip(y, pred, strict=True):
        m[int(t)][int(p)] += 1
    print(f'\n[{title}] confusion (rows=true, cols=pred):')
    print('true\\pred'.ljust(26) + ''.join(f'{i:>4d}' for i in range(n)))
    for i, name in enumerate(TENDENCY_LABELS):
        print(f'{name[:25]:26s}' + ''.join(f'{m[i][j]:>4d}' for j in range(n)))
    pairs = sorted(
        (
            (int(m[i][j]), TENDENCY_LABELS[i], TENDENCY_LABELS[j])
            for i in range(n)
            for j in range(n)
            if i != j and m[i][j]
        ),
        reverse=True,
    )
    print(f'[{title}] top confusions (true -> pred):')
    for cnt, t, p in pairs[:6]:
        print(f'  {cnt:3d}  {t}  ->  {p}')


def main():
    parser = argparse.ArgumentParser(
        description='Modern-Chinese-encoder six-class tendency classifier (independent v2).'
    )
    parser.add_argument('--in', dest='in_csv', default=os.path.join(DATA, 'tendency_distilled.csv'))
    parser.add_argument(
        '--out',
        default=os.path.join(MODELS, 'tendency_stance_v2_cyberbully'),
        help='a NEW dir — never overwrites the old models/tendency_stance_v1',
    )
    parser.add_argument(
        '--base',
        default='thenlper/gte-base-zh',
        help=(
            'modern Chinese encoder. base-size (8GB-safe): thenlper/gte-base-zh, hfl/chinese-macbert-base. '
            'large (use --batch-size 8 --grad-accum 4): hfl/chinese-roberta-wwm-ext-large, '
            'feynmanzhao/chinese-modernbert-large-wwm. NEVER answerdotai/ModernBERT-* or Alibaba-NLP/gte-modernbert-* '
            '(English tokenizers).'
        ),
    )
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=16, help='per device; 16 at fp16 fits a base model under 8GB')
    parser.add_argument('--grad-accum', type=int, default=2)
    parser.add_argument('--lr', type=float, default=2e-5)
    parser.add_argument(
        '--val-size', type=float, default=0.05, help='distilled-label dev split, used only to pick the best checkpoint'
    )
    parser.add_argument(
        '--class-weights',
        action='store_true',
        help='inverse-frequency class weights in the loss — the cheap fix for the rare Controversy class',
    )
    parser.add_argument(
        '--holdout',
        default='',
        help='a HUMAN-labelled csv (text + label) for the honest final metric; its rows are removed from training',
    )
    parser.add_argument('--holdout-label-col', default='human_label', help='the corrected-label column in --holdout')
    parser.add_argument(
        '--limit', type=int, default=0, help='use only the first N rows (0=all) — pre-flight the code path fast'
    )
    parser.add_argument(
        '--no-save', action='store_true', help='skip writing the model dir (comparison runs: metrics only)'
    )
    parser.add_argument(
        '--loss',
        choices=['ce', 'focal'],
        default='ce',
        help='focal loss down-weights easy examples; try it on the rare Controversy class',
    )
    parser.add_argument('--focal-gamma', type=float, default=2.0)
    parser.add_argument(
        '--confusion',
        action='store_true',
        help='print the dev (and holdout) confusion matrix + top confusable pairs — locates the bottleneck',
    )
    parser.add_argument(
        '--soft-csv', default='', help='teacher soft-label csv (text + prob_<label> x6) for distillation'
    )
    parser.add_argument('--distill-alpha', type=float, default=0.5, help='weight of the hard term vs the soft term')
    parser.add_argument('--distill-temp', type=float, default=2.0, help='distillation temperature')
    args = parser.parse_args()

    rows = load_labeled(args.in_csv)
    texts, label_names = [t for t, _ in rows], [lab for _, lab in rows]
    if args.limit:
        texts, label_names = texts[: args.limit], label_names[: args.limit]

    # Load the human holdout FIRST and carve it out of training, so the honest number is not contaminated.
    holdout = load_labeled(args.holdout, label_col=args.holdout_label_col) if args.holdout else []
    holdout_texts = {t for t, _ in holdout}
    if holdout:
        n_before = len(texts)
        kept = [(t, lab) for t, lab in zip(texts, label_names, strict=True) if t not in holdout_texts]
        texts, label_names = [t for t, _ in kept], [lab for _, lab in kept]
        print(
            f'holdout: {len(holdout)} human rows; removed {n_before - len(texts)} overlapping train rows; train now {len(texts)}'
        )

    label_ids = [LABEL2ID[name] for name in label_names]
    counts = np.bincount(label_ids, minlength=len(TENDENCY_LABELS)).tolist()
    print(f'base={args.base}  {len(texts)} train rows; class balance {dict(zip(TENDENCY_LABELS, counts))}')
    if len(set(label_ids)) < len(TENDENCY_LABELS):
        print('  WARNING: a class is absent from train; macro-F1 will understate it')

    class_weights = None
    if args.class_weights:
        # inverse frequency, normalized to mean 1 so the loss scale (and the LR) stay comparable across runs.
        freq = np.array(counts, dtype=float)
        freq[freq == 0] = 1.0
        w = 1.0 / freq
        w = w / w.mean()
        class_weights = torch.tensor(w, dtype=torch.float32)
        print(f'class weights (mean-1 inverse freq): {dict(zip(TENDENCY_LABELS, [round(x, 3) for x in w]))}')

    index = list(range(len(texts)))
    random.Random(SEED).shuffle(index)
    n_val = max(1, int(len(index) * args.val_size))
    val_idx, train_idx = index[:n_val], index[n_val:]

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    soft_map = load_soft(args.soft_csv) if args.soft_csv else None

    def _soft_for(text, label):
        v = soft_map.get(str(text).strip()) if soft_map is not None else None
        if v is None:  # a text with no teacher vector falls back to the hard one-hot
            v = [1.0 if i == LABEL2ID[label] else 0.0 for i in range(len(TENDENCY_LABELS))]
        return v

    def encode(rows_texts, rows_labels):
        feats = tokenizer(rows_texts, truncation=True, max_length=MAX_LENGTH, padding=False)
        feats['labels'] = rows_labels
        return feats

    def to_dataset(rows):
        enc = encode([texts[i] for i in rows], [label_ids[i] for i in rows])
        out = [{k: enc[k][i] for k in enc} for i in range(len(rows))]
        if soft_map is not None:
            for j, i in enumerate(rows):
                out[j]['soft'] = _soft_for(texts[i], label_names[i])
        return out

    def holdout_dataset():
        enc = encode([t for t, _ in holdout], [LABEL2ID[lab] for _, lab in holdout])
        out = [{k: enc[k][i] for k in enc} for i in range(len(holdout))]
        if soft_map is not None:
            for j, (t, lab) in enumerate(holdout):
                out[j]['soft'] = _soft_for(t, lab)
        return out

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
        return {'accuracy': acc, 'f1_macro': float(np.mean(f1s)), 'f1_per_class': f1s}

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=len(TENDENCY_LABELS), id2label=ID2LABEL, label2id=LABEL2ID
    )
    # Keep fp32 master weights: a checkpoint that loads its params in half precision makes the fp16
    # GradScaler abort with "Attempting to unscale FP16 gradients". .float() pins them to fp32 and lets
    # the Trainer's autocast own the low-precision math. Ada (RTX 4060) supports bf16, which needs no
    # scaler at all and is more stable than fp16 — prefer it, fall back to fp16 elsewhere.
    model = model.float()
    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()

    training_args = TrainingArguments(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size * 2,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        warmup_ratio=0.1,
        weight_decay=0.01,
        bf16=use_bf16,
        fp16=not use_bf16,
        eval_strategy='epoch',
        save_strategy='epoch',
        save_total_limit=1,  # keep only the best checkpoint; per-epoch saves otherwise pile up ~400MB each
        load_best_model_at_end=True,
        metric_for_best_model='f1_macro',
        logging_steps=100,
        report_to='none',
        # Keep the custom `soft` teacher column: the default would strip any column not in
        # the model's forward signature before the collator runs, and the distillation target would vanish.
        remove_unused_columns=False,
    )

    collator = SoftCollator(tokenizer) if soft_map is not None else DataCollatorWithPadding(tokenizer=tokenizer)
    dev_ds = to_dataset(val_idx)
    trainer = WeightedTrainer(
        class_weights=class_weights,
        focal_gamma=args.focal_gamma if args.loss == 'focal' else None,
        soft_alpha=args.distill_alpha if soft_map is not None else None,
        soft_temp=args.distill_temp,
        model=model,
        args=training_args,
        train_dataset=to_dataset(train_idx),
        eval_dataset=dev_ds,
        data_collator=collator,
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
    )

    start = time.time()
    trainer.train()
    dev = trainer.evaluate()
    dev_per = {n: round(float(f), 4) for n, f in zip(TENDENCY_LABELS, dev.get('eval_f1_per_class') or [], strict=False)}
    print(f'\nfine-tuned in {(time.time() - start) / 60:.1f} min')
    print(f'DEV (distilled labels): accuracy={dev["eval_accuracy"]:.4f}  macro-F1={dev["eval_f1_macro"]:.4f}')
    for name, f1 in dev_per.items():
        print(f'    {name:28s} F1={f1:.3f}')
    if args.confusion:
        report_confusion(trainer, dev_ds, 'DEV')

    result = {
        'base': args.base,
        'class_weights': bool(args.class_weights),
        'loss': args.loss,
        'lr': args.lr,
        'epochs': args.epochs,
        'batch_size': args.batch_size,
        'grad_accum': args.grad_accum,
        'out': os.path.basename(args.out),
        'dev_acc': round(float(dev['eval_accuracy']), 4),
        'dev_f1_macro': round(float(dev['eval_f1_macro']), 4),
        'dev_f1_controversy': dev_per.get('Controversy/Reflection'),
        'dev_f1_per_class': dev_per,
    }
    if holdout:
        ho_ds = holdout_dataset()
        ho = trainer.evaluate(ho_ds)
        ho_per = {
            n: round(float(f), 4) for n, f in zip(TENDENCY_LABELS, ho.get('eval_f1_per_class') or [], strict=False)
        }
        print(f'HOLDOUT (human labels): accuracy={ho["eval_accuracy"]:.4f}  macro-F1={ho["eval_f1_macro"]:.4f}')
        if args.confusion:
            report_confusion(trainer, ho_ds, 'HOLDOUT')
        result['holdout_acc'] = round(float(ho['eval_accuracy']), 4)
        result['holdout_f1_macro'] = round(float(ho['eval_f1_macro']), 4)
        result['holdout_f1_per_class'] = ho_per
    else:
        print('  (no --holdout: macro-F1 is on Qwen-distilled labels → scores imitation, not truth)')
    print('RESULT_JSON ' + json.dumps(result, ensure_ascii=False))

    if args.no_save:
        print('(--no-save: skipped writing the model dir — comparison run, metrics above only)')
        return
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f'saved HF model -> {args.out}')
    print(
        'Register its ml_train/models/… path (name 「网暴模型」) so the 「已注册模型」 dropdown lists it; the old models/tendency_stance_v1 stays intact.'
    )


if __name__ == '__main__':
    main()
