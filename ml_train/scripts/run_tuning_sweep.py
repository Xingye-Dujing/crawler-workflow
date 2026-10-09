"""Tuning sweep on the WINNING encoder (chinese-roberta-wwm-ext + class weights), run SEQUENTIALLY on
the one GPU. Independent experiment driver; shells out to train_tendency_bert_v2.py and reads the
RESULT_JSON + the --confusion block each run prints. Never touches the old track; deletes checkpoints.

Answers the two open questions with data:
  * focal vs plain class-weighted CE — does focal lift the rare Controversy class further?
  * LR / epochs — is 2e-5 / 3 epochs the right point, or does a lower LR + more epochs (or higher LR) help?
  * and the confusion matrix — is Controversy a capacity problem or a label-boundary problem (what
    does it get misread as), which decides the label-merge step.

    .venv/Scripts/python.exe ml_train/scripts/run_tuning_sweep.py
Writes ml_train/logs/tendency_tuning.md and prints the table + the confusion matrix.
"""

import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
LOGS = os.path.join(ROOT, 'logs')
TRAIN = os.path.join(HERE, 'train_tendency_bert_v2.py')
WORK = os.path.join(HERE, '_tune_out')
WINNER = ['--base', 'hfl/chinese-roberta-wwm-ext', '--class-weights']

os.environ['HF_HOME'] = os.path.join(ROOT, '.hf-cache')
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

CONFIGS = [
    ('ce_base', [*WINNER, '--confusion']),
    ('focal', [*WINNER, '--loss', 'focal']),
    ('focal_lr1e5_ep4', [*WINNER, '--loss', 'focal', '--lr', '1e-5', '--epochs', '4']),
    ('focal_lr3e5', [*WINNER, '--loss', 'focal', '--lr', '3e-5']),
]


def run_one(name, extra):
    out_dir = os.path.join(WORK, name)
    os.makedirs(out_dir, exist_ok=True)
    cmd = [sys.executable, TRAIN, '--no-save', '--out', out_dir, *extra]
    print(f'=== {name}: {" ".join(extra)} ===', flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    log = (proc.stdout or '') + '\n----STDERR----\n' + (proc.stderr or '')
    with open(os.path.join(LOGS, f'tune_{name}.log'), 'w', encoding='utf-8') as fh:
        fh.write(log)
    shutil.rmtree(out_dir, ignore_errors=True)
    res = None
    for line in (proc.stdout or '').splitlines():
        if line.startswith('RESULT_JSON '):
            res = json.loads(line[len('RESULT_JSON ') :])
            res['name'] = name
    conf = re.search(r'\[DEV\] confusion.*?(?=\nRESULT_JSON|\Z)', proc.stdout or '', re.S)
    return res or {'name': name, 'error': (proc.stderr or proc.stdout or 'no result').strip()[-160:]}, (
        conf.group(0) if conf else ''
    )


def main():
    os.makedirs(WORK, exist_ok=True)
    results, confusion = [], ''
    for name, extra in CONFIGS:
        res, conf = run_one(name, extra)
        results.append(res)
        if conf:
            confusion = conf
    shutil.rmtree(WORK, ignore_errors=True)

    ok = [r for r in results if 'error' not in r]
    ok.sort(key=lambda r: r['dev_f1_macro'], reverse=True)
    best = ok[0] if ok else None

    lines = [
        '# 倾向六分类 · 冠军(wwmext+类权重) 调参对比\n',
        '| 配置 | loss | lr | epochs | dev macro-F1 | Controversy F1 |',
        '|---|---|---|---|---|---|',
    ]
    for r in results:
        if 'error' in r:
            lines.append(f'| {r["name"]} | — | — | — | — | ERROR {r["error"][:60]} |')
            continue
        lines.append(
            f'| {r["name"]} | {r["loss"]} | {r["lr"]} | {r["epochs"]} | '
            f'**{r["dev_f1_macro"]:.4f}** | {r["dev_f1_controversy"]} |'
        )
    lines.append('')
    if best:
        lines.append(
            f'**最佳 dev macro-F1：`{best["name"]}` = {best["dev_f1_macro"]:.4f}，'
            f'Controversy F1={best["dev_f1_controversy"]}。**\n'
        )
    if confusion:
        lines.append('## 混淆矩阵（冠军基线，rows=true / cols=pred）\n')
        lines.append('```\n' + confusion.strip() + '\n```\n')
    md = '\n'.join(lines)
    with open(os.path.join(LOGS, 'tendency_tuning.md'), 'w', encoding='utf-8') as fh:
        fh.write(md)
    print('\n' + md)


if __name__ == '__main__':
    main()
