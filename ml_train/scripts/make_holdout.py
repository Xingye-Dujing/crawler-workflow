"""Build a HUMAN-labelling template for the six-class tendency scheme, so the v2 track can be judged
on truth rather than on Qwen's own labels (the old 0.681 is a distilled-label eval = imitation score).

Stratified: samples up to ``--per-class`` rows from each of the six stances already present in
``tendency_distilled.csv`` and writes a CSV with an empty ``human_label`` column to fill in. The rare
Controversy/Reflection class is reported explicitly — if it cannot reach ``--per-class``, that is the
real ceiling you are fighting, and the number this prints is what tells you whether class weights,
synthesis, or more crawling is the actual lever.

    .venv/Scripts/python.exe ml_train/scripts/make_holdout.py --per-class 60
    # -> ml_train/datasets/tendency_holdout_template.csv  (fill the human_label column, save as
    #    ml_train/datasets/tendency_holdout_labeled.csv, then pass it to scripts/train_tendency_bert_v2.py --holdout)

Independent of the old track: it only reads the distilled CSV and writes a new template file.
"""

import argparse
import os
import random

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
DATA = os.path.join(ROOT, 'datasets')

# The analyzer's exact six label strings — the human_label column must use these, spaces and slashes included.
TENDENCY_LABELS = [
    'Advocacy/Call-to-action',
    'Controversy/Reflection',
    'Criticism/Questioning',
    'Objective Statement',
    'Praise/Affirmation',
    'Satire/Mockery',
]


def main():
    parser = argparse.ArgumentParser(
        description='Sample a stratified human-label holdout template from the distilled CSV.'
    )
    parser.add_argument('--in', dest='in_csv', default=os.path.join(DATA, 'tendency_distilled.csv'))
    parser.add_argument('--out', default=os.path.join(DATA, 'tendency_holdout_template.csv'))
    parser.add_argument('--per-class', type=int, default=60, help='rows to draw per stance (capped by what exists)')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()

    df = pd.read_csv(args.in_csv, usecols=['text', 'tendency'])
    df = df[df['text'].astype(str).str.strip() != '']
    df = df[df['tendency'].isin(TENDENCY_LABELS)]  # a stray label is dropped, never guessed

    rng = random.Random(args.seed)
    sampled = []
    print(f'distilled pool: {len(df)} rows across {df["tendency"].nunique()}/6 stances')
    for label in TENDENCY_LABELS:
        pool = df[df['tendency'] == label]['text'].astype(str).str.strip().tolist()
        take = min(args.per_class, len(pool))
        picked = rng.sample(pool, take) if take else []
        flag = '' if take >= args.per_class else f'  <-- ONLY {len(pool)} available (rare class)'
        print(f'  {label:28s} pool={len(pool):5d}  sampled={take}{flag}')
        sampled += [(t, label, '') for t in picked]

    out = pd.DataFrame(sampled, columns=['text', 'distilled_label', 'human_label'])
    out.to_csv(args.out, index=False, encoding='utf-8-sig')  # BOM so Excel opens the Chinese cleanly
    print(f'\nwrote {len(out)} rows -> {args.out}')
    print('Fill human_label with one of these EXACT strings, then save as tendency_holdout_labeled.csv:')
    for label in TENDENCY_LABELS:
        print(f'  {label}')


if __name__ == '__main__':
    main()
