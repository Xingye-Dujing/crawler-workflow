"""Fine-tune the six-class emotion model on EWECT plus the new dialogue corpus.

EWECT remains the target distribution (Weibo comments); the dialogue corpus adds manually
annotated Neutral/Joy/Sadness/Anger/Surprise rows. The dialogue card also has 關切/厭惡/疑問,
which do NOT exist in the project's six-label scheme — they are dropped BY NAME and counted,
never folded into a neighbouring class. Fear has no rows in the new corpus (EWECT keeps its
own), which the report states rather than hiding.

    .venv/Scripts/python.exe ml_train/scripts/train_emotion_mixed.py

Writes a NEW folder by default; old checkpoints are backed up by ``backup_assets.py``.
"""

import argparse
import glob
import json
import os
import random
import time
from pathlib import Path

import _env
import numpy as np
import pandas as pd
from mixed_common import SEED, binary_holdout, predict, save_report
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
SMP_DIR = os.path.join(DATA, 'ewect_smp2020')
DIALOGUE_DIR = os.path.join(DATA, 'classification', 'emotion', 'chinese_multi_emotion_dialogue')

EMOTION_LABELS = ['Anger', 'Fear', 'Joy', 'Neutral', 'Sadness', 'Surprise']
ID2LABEL = {index: name for index, name in enumerate(EMOTION_LABELS)}
LABEL2ID = {name: index for index, name in enumerate(EMOTION_LABELS)}
SMP2PROJECT = {
    'angry': 'Anger',
    'fear': 'Fear',
    'happy': 'Joy',
    'neutral': 'Neutral',
    'sad': 'Sadness',
    'surprise': 'Surprise',
}
DIALOGUE2PROJECT = {
    '平淡語氣': 'Neutral',
    '開心語調': 'Joy',
    '憤怒語調': 'Anger',
    '驚奇語調': 'Surprise',
    '悲傷語調': 'Sadness',
}
MAX_LENGTH = 128


def load_smp(paths: list[str]) -> list[dict]:
    rows = []
    for path in paths:
        with open(path, encoding='utf-8') as handle:
            for row in json.load(handle):
                text = str(row.get('content') or '').strip()
                label = SMP2PROJECT.get(str(row.get('label') or '').strip().lower())
                if text and label:
                    rows.append({'text': text, 'label': label, 'source': 'ewect'})
    return rows


def load_dialogue() -> tuple[list[dict], dict[str, int]]:
    paths = sorted(Path(DIALOGUE_DIR).rglob('*.csv'))
    if not paths:
        raise FileNotFoundError(f'{DIALOGUE_DIR}: run fetch_assets.py --kind datasets --only dialogue-emotion')
    frame = pd.read_csv(paths[0])
    if not {'text', 'emotion'}.issubset(frame.columns):
        raise ValueError(f'{paths[0]}: expected text/emotion columns, got {list(frame.columns)}')
    rows, dropped = [], {}
    for text, raw in zip(frame['text'], frame['emotion'], strict=True):
        text = str(text).strip()
        label = DIALOGUE2PROJECT.get(str(raw).strip())
        if not text:
            continue
        if not label:
            dropped[str(raw)] = dropped.get(str(raw), 0) + 1
            continue
        rows.append({'text': text, 'label': label, 'source': 'dialogue'})
    return rows, dropped


def _smp_eval() -> list[dict]:
    paths = sorted(glob.glob(os.path.join(SMP_DIR, 'eval*', 'usual_eval_labeled.txt')))
    return load_smp(paths) if paths else []


def multiclass_metrics(truth: list[int], predicted: list[int]) -> dict:
    truth_array = np.asarray(truth)
    predicted_array = np.asarray(predicted)
    accuracy = float((truth_array == predicted_array).mean()) if len(truth_array) else 0.0
    f1s = []
    for cls in range(len(EMOTION_LABELS)):
        tp = int(((predicted_array == cls) & (truth_array == cls)).sum())
        fp = int(((predicted_array == cls) & (truth_array != cls)).sum())
        fn = int(((predicted_array != cls) & (truth_array == cls)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return {'accuracy': round(accuracy, 4), 'f1_macro': round(float(np.mean(f1s)), 4), 'rows': len(truth)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='hfl/chinese-roberta-wwm-ext')
    parser.add_argument('--out', default=os.path.join(MODELS, 'emotion_mixed_v1'))
    parser.add_argument('--baseline', default=os.path.join(MODELS, 'emotion_ewect_six'))
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--grad-accum', type=int, default=2)
    parser.add_argument('--lr', type=float, default=2e-5)
    parser.add_argument('--val-size', type=float, default=0.05)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()

    train_paths = [os.path.join(SMP_DIR, 'train', 'usual_train.txt')]
    rows = load_smp(train_paths)
    dialogue, dropped = load_dialogue()
    if args.limit:
        rows, dialogue = rows[: args.limit], dialogue[: args.limit]
    rows += dialogue
    print(f'ewect={len(rows) - len(dialogue)} dialogue={len(dialogue)} dropped={dropped}')

    train_rows, val_rows = [], []
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row['source'], []).append(row)
    for source, group in by_source.items():
        train, val = binary_holdout(group, args.val_size)
        train_rows += train
        val_rows += val
        counts = np.bincount([LABEL2ID[row['label']] for row in group], minlength=6).tolist()
        print(f'{source}: {len(group)} rows, {dict(zip(EMOTION_LABELS, counts, strict=True))}')
    random.Random(SEED).shuffle(train_rows)
    print(f'train={len(train_rows)} val={len(val_rows)}')

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=6, id2label=ID2LABEL, label2id=LABEL2ID
    )

    def to_dataset(items):
        enc = tokenizer([row['text'] for row in items], truncation=True, max_length=MAX_LENGTH, padding=False)
        enc['labels'] = [LABEL2ID[row['label']] for row in items]
        return [{key: enc[key][i] for key in enc} for i in range(len(items))]

    def compute_metrics(eval_pred):
        logits, truth = eval_pred
        result = multiclass_metrics(list(truth), list(np.argmax(logits, axis=1)))
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
    import torch

    del trainer, model
    torch.cuda.empty_cache()

    holdout = {'mixed_holdout': val_rows, 'ewect_official_eval': _smp_eval()}
    report = {'schema': 1, 'base': args.base, 'out': args.out, 'dropped_dialogue_labels': dropped, 'sources': {}}
    for name, items in holdout.items():
        if not items:
            continue
        truth = [LABEL2ID[row['label']] for row in items]
        texts = [row['text'] for row in items]
        report['sources'][name] = {'rows': len(items)}
        candidates = {'new': args.out}
        if os.path.isdir(args.baseline):
            candidates['baseline'] = args.baseline
        for candidate, path in candidates.items():
            try:
                report['sources'][name][candidate] = multiclass_metrics(truth, predict(path, texts))
            except Exception as exc:
                report['sources'][name][candidate] = {'error': f'{type(exc).__name__}: {exc}'}
        print(name, report['sources'][name])
    report_path = save_report(report, 'emotion_mixed', Path(_env.LOGS_DIR) / 'mixed_train')
    print(f'report={report_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
