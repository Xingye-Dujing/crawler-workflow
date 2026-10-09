"""Teacher-ceiling check: how well does Qwen (the distillation teacher) agree with HUMAN labels?

The whole tendency corpus is Qwen-distilled, so every encoder macro-F1 so far measures imitation.
This script measures the CEILING: agreement between the distilled label and a human label on the
same text. No distilled BERT can reliably beat Qwen's own human-agreement — so this number tells
you whether to keep tuning the encoder or fix the teacher/labels instead.

Run it on the FILLED holdout (you corrected the human_label column of tendency_holdout_template.csv):

    .venv/Scripts/python.exe ml_train/scripts/eval_teacher_ceiling.py --holdout ml_train/datasets/tendency_holdout_labeled.csv

Columns expected: text, distilled_label (Qwen), human_label (you). Rows with a blank/invalid
human_label are skipped (never guessed).
"""

import argparse
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
DATA = os.path.join(ROOT, 'datasets')
LABELS = [
    'Advocacy/Call-to-action',
    'Controversy/Reflection',
    'Criticism/Questioning',
    'Objective Statement',
    'Praise/Affirmation',
    'Satire/Mockery',
]


def main():
    ap = argparse.ArgumentParser(description='Score Qwen-vs-human agreement (the distillation ceiling).')
    ap.add_argument('--holdout', default=os.path.join(DATA, 'tendency_holdout_labeled.csv'))
    ap.add_argument('--qwen-col', default='distilled_label')
    ap.add_argument('--human-col', default='human_label')
    args = ap.parse_args()

    if not os.path.isfile(args.holdout):
        print(
            f'no file: {args.holdout}\nFill human_label in tendency_holdout_template.csv and save as tendency_holdout_labeled.csv'
        )
        return
    df = pd.read_csv(args.holdout)
    for c in (args.qwen_col, args.human_col):
        if c not in df.columns:
            print(f'missing column {c!r}; have {list(df.columns)}')
            return
    df = df[df[args.human_col].isin(LABELS) & df[args.qwen_col].isin(LABELS)]
    n = len(df)
    if n == 0:
        print('no fully-labelled rows yet (human_label blank?)')
        return

    y_h = df[args.human_col].map({l: i for i, l in enumerate(LABELS)}).to_numpy()
    y_q = df[args.qwen_col].map({l: i for i, l in enumerate(LABELS)}).to_numpy()
    agree = int((y_h == y_q).sum())
    po = agree / n
    # Cohen's kappa: agreement beyond chance.
    pe = sum((np.mean(y_h == i)) * (np.mean(y_q == i)) for i in range(len(LABELS)))
    kappa = (po - pe) / (1 - pe) if pe < 1 else 0.0

    print(f'Qwen vs human on {n} labelled rows:')
    print(f'  raw agreement (accuracy) = {po:.3f}   Cohen kappa = {kappa:.3f}')
    print('  per-class: of the rows a HUMAN called X, how often Qwen agreed (recall) / precision')
    for i, lab in enumerate(LABELS):
        h = y_h == i
        q = y_q == i
        rec = (h & q).sum() / h.sum() if h.sum() else float('nan')
        prec = (h & q).sum() / q.sum() if q.sum() else float('nan')
        print(f'    {lab:26s} human_n={int(h.sum()):3d}  Qwen-recall={rec:.2f}  Qwen-precision={prec:.2f}')

    print('\n  confusion (rows=HUMAN, cols=Qwen):')
    m = np.zeros((len(LABELS), len(LABELS)), dtype=int)
    for a, b in zip(y_h, y_q, strict=True):
        m[a][b] += 1
    print('   human\\qwen'.ljust(26) + ''.join(f'{i:>4d}' for i in range(len(LABELS))))
    for i, lab in enumerate(LABELS):
        print(f'   {lab[:22]:26s}' + ''.join(f'{m[i][j]:>4d}' for j in range(len(LABELS))))

    print(
        f'\nCEILING: no distilled BERT should be expected to beat ~{po:.2f} human-agreement on this '
        f"task unless the teacher/labels improve. Compare it to the encoder's --holdout macro-F1."
    )


if __name__ == '__main__':
    main()
