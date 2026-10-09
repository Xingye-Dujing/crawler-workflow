"""Fixed-eval A/B: does the batch2 crawl (13 events) actually help, or was the earlier number just a
shifted val split? Holds out ONE fixed real-labelled val (from the original 7721 corpus), then trains:
  A = original-train + batch1
  B = original-train + batch1 + batch2
Both evaluated on the SAME fixed val → the only difference is batch2's rows, so the delta is clean.

    .venv/Scripts/python.exe ml_train/scripts/eval_ab_batch2.py
"""

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
from selftrain_tendency import build_ds, train_model  # noqa: E402
from train_tendency_bert_v2 import LABEL2ID, SEED, TENDENCY_LABELS  # noqa: E402


def _rows(df):
    return df['text'].astype(str).str.strip().tolist(), [LABEL2ID[t] for t in df['tendency']]


def _class_weights(labels):
    counts = np.bincount(labels, minlength=len(TENDENCY_LABELS)).astype(float)
    counts[counts == 0] = 1.0
    w = 1.0 / counts
    return torch.tensor(w / w.mean(), dtype=torch.float32)


def main():
    base = 'hfl/chinese-roberta-wwm-ext'
    # 7721-row pre-crawl snapshot; pruned in the ml_train cleanup as a leftover backup, so this
    # one-off A/B can no longer be re-run without re-creating it — the recorded result lives in
    # docs/tendency_model_comparison.md. Kept consistent (not silently repointed to the live corpus)
    # so it stays honest about WHAT it compared.
    orig = pd.read_csv(os.path.join(DATA, 'tendency_distilled_pre_crawl.csv'))
    orig = orig[orig['tendency'].isin(LABEL2ID)]
    lab = pd.read_csv(os.path.join(DATA, 'controversy_labeled.csv'))  # batch1 (first 487) + batch2
    lab = lab[lab['tendency'].isin(LABEL2ID)]
    batch1 = lab.iloc[:487]
    batch2 = lab.iloc[487:]

    texts = orig['text'].astype(str).str.strip().tolist()
    labels = [LABEL2ID[t] for t in orig['tendency']]
    idx = list(range(len(texts)))
    random.Random(SEED).shuffle(idx)
    n_val = max(1, int(len(idx) * 0.05))
    val_idx, tr_idx = idx[:n_val], idx[n_val:]
    val_t, val_l = [texts[i] for i in val_idx], [labels[i] for i in val_idx]
    orig_tr = orig.iloc[tr_idx]

    arm_a = pd.concat([orig_tr, batch1], ignore_index=True)
    arm_b = pd.concat([orig_tr, batch1, batch2], ignore_index=True)
    print(
        f'FIXED val = {len(val_t)} rows (Controversy {sum(1 for l in val_l if l == LABEL2ID["Controversy/Reflection"])})',
        flush=True,
    )
    print(
        f'A rows={len(arm_a)} (Controversy {int((arm_a["tendency"] == "Controversy/Reflection").sum())}) | '
        f'B rows={len(arm_b)} (Controversy {int((arm_b["tendency"] == "Controversy/Reflection").sum())})',
        flush=True,
    )

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(base)
    val_ds = build_ds(tok, val_t, val_l)

    a_t, a_l = _rows(arm_a)
    tr_a = train_model(base, tok, build_ds(tok, a_t, a_l), val_ds, _class_weights(a_l), 3, 2e-5)
    ra = tr_a.evaluate()
    print(
        f'A (no batch2)  macro-F1={ra["eval_f1_macro"]:.4f}  Controversy F1={ra["eval_f1_controversy"]:.4f}', flush=True
    )

    b_t, b_l = _rows(arm_b)
    tr_b = train_model(base, tok, build_ds(tok, b_t, b_l), val_ds, _class_weights(b_l), 3, 2e-5)
    rb = tr_b.evaluate()
    print(
        f'B (with batch2) macro-F1={rb["eval_f1_macro"]:.4f}  Controversy F1={rb["eval_f1_controversy"]:.4f}',
        flush=True,
    )

    print(
        f'\nBATCH2 EFFECT on the SAME fixed val:  macro {rb["eval_f1_macro"] - ra["eval_f1_macro"]:+.4f}  '
        f'Controversy {rb["eval_f1_controversy"] - ra["eval_f1_controversy"]:+.4f}'
    )
    print('noise floor ~±0.011 — a delta below that is not a real effect.')


if __name__ == '__main__':
    main()
