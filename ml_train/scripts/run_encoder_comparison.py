"""Run the tendency v2 encoder comparison SEQUENTIALLY (one GPU) and rank the configs.

Independent experiment driver — it only shells out to ``train_tendency_bert_v2.py`` and reads back the
``RESULT_JSON`` line each run prints. It never touches the old track, and deletes each run's checkpoint
dir afterwards (TrainingArguments writes a checkpoint per epoch; we keep only the metrics).

Every config is scored on the SAME distilled-label dev split, so the ranking is apples-to-apples:
  * wwmext        — the current 2019 base, no weights (the ~0.681 anchor)
  * wwmext_cw     — same base + class weights   → isolates the ② (imbalance) effect
  * gte           — modern Chinese base, no weights
  * gte_cw        — modern Chinese base + weights → isolates the ① (encoder) effect at fixed weights
  * cmb_large_cw  — Chinese ModernBERT (large) + weights, batch8/grad-accum4 → the ① "modern large" bet

    .venv/Scripts/python.exe ml_train/scripts/run_encoder_comparison.py
Writes ml_train/logs/tendency_comparison.md and prints the ranked table.
"""

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
LOGS = os.path.join(ROOT, 'logs')
TRAIN = os.path.join(HERE, 'train_tendency_bert_v2.py')
WORK = os.path.join(HERE, '_cmp_out')

os.environ['HF_HOME'] = os.path.join(ROOT, '.hf-cache')
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

CONFIGS = [
    ('wwmext', ['--base', 'hfl/chinese-roberta-wwm-ext']),
    ('wwmext_cw', ['--base', 'hfl/chinese-roberta-wwm-ext', '--class-weights']),
    ('gte', ['--base', 'thenlper/gte-base-zh']),
    ('gte_cw', ['--base', 'thenlper/gte-base-zh', '--class-weights']),
    (
        'cmb_large_cw',
        [
            '--base',
            'feynmanzhao/chinese-modernbert-large-wwm',
            '--class-weights',
            '--batch-size',
            '8',
            '--grad-accum',
            '4',
        ],
    ),
]


def run_one(name, extra):
    out_dir = os.path.join(WORK, name)
    os.makedirs(out_dir, exist_ok=True)
    cmd = [sys.executable, TRAIN, '--no-save', '--out', out_dir, *extra]
    print(f'\n=== {name}: {" ".join(extra)} ===', flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    log_path = os.path.join(LOGS, f'cmp_{name}.log')
    with open(log_path, 'w', encoding='utf-8') as fh:
        fh.write(proc.stdout or '')
        fh.write('\n----STDERR----\n')
        fh.write(proc.stderr or '')
    shutil.rmtree(out_dir, ignore_errors=True)  # keep metrics only, drop epoch checkpoints
    for line in (proc.stdout or '').splitlines():
        if line.startswith('RESULT_JSON '):
            res = json.loads(line[len('RESULT_JSON ') :])
            res['name'] = name
            return res
    err = (proc.stderr or proc.stdout or '').strip().splitlines()
    return {'name': name, 'error': (err[-1] if err else f'no RESULT_JSON, rc={proc.returncode}')}


def main():
    os.makedirs(WORK, exist_ok=True)
    results = [run_one(name, extra) for name, extra in CONFIGS]
    shutil.rmtree(WORK, ignore_errors=True)

    ok = [r for r in results if 'error' not in r]
    ok.sort(key=lambda r: r['dev_f1_macro'], reverse=True)
    best = ok[0] if ok else None

    lines = [
        '# 倾向六分类 v2 编码器对比（同一 distilled dev 划分，macro-F1 降序）\n',
        '| 配置 | base | 类权重 | dev acc | dev macro-F1 | Controversy F1 |',
        '|---|---|---|---|---|---|',
    ]
    for r in results:
        if 'error' in r:
            lines.append(f'| {r["name"]} | — | — | — | — | ERROR: {r["error"][:80]} |')
            continue
        cw = '是' if r['class_weights'] else '否'
        lines.append(
            f'| {r["name"]} | {r["base"]} | {cw} | {r["dev_acc"]:.4f} | **{r["dev_f1_macro"]:.4f}** | {r["dev_f1_controversy"]} |'
        )
    lines.append('')
    if best:
        lines.append(
            f'**最佳（按 dev macro-F1）：`{best["name"]}` = `{best["base"]}`'
            f'{" + 类权重" if best["class_weights"] else ""}，macro-F1={best["dev_f1_macro"]:.4f}，'
            f'Controversy F1={best["dev_f1_controversy"]}。'
        )
        lines.append('\n逐类 F1（最佳配置）：')
        for k, v in best['dev_f1_per_class'].items():
            lines.append(f'- {k}: {v}')
    md = '\n'.join(lines) + '\n'
    with open(os.path.join(LOGS, 'tendency_comparison.md'), 'w', encoding='utf-8') as fh:
        fh.write(md)
    print('\n' + md)


if __name__ == '__main__':
    main()
