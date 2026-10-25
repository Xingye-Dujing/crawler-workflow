"""Measure the exported ONNX packs against the torch model on labelled rows — the int8 decision.

``export_onnx_bert.py`` proves the graph reproduces torch on the trace batch. That is not the
question the user is asking: the models were fine-tuned for accuracy, and quantising weights can
move a decision. So this scores the SAME labelled rows three ways — the torch pipeline on CPU, the
fp32 graph, the int8 graph — through the product's own loader (``analyzers.sentiment.BertClassifier``
with ``runtime='onnx'``), and prints accuracy and macro-F1 for each plus the agreement between them.

    .venv/Scripts/python.exe ml_train/scripts/eval_onnx_parity.py                 # every pack
    ... --only sentiment_weibosenti_bin --rows 300 --batches 8,16,32

The rule the numbers are read against (the user's decision, recorded here so the script states its
own threshold): ship int8 when it loses no more than 0.003 macro-F1 against fp32 AND agrees with
the torch argmax on at least 99% of rows; otherwise that model ships as fp32.

Nothing here is asserted in CI: the corpora are gitignored and the torch stack is optional. These
are measurements to report, not a green to manufacture.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')

ML_TRAIN = Path(__file__).resolve().parents[1]
BACKEND = ML_TRAIN.parent / 'backend'
MODELS = ML_TRAIN / 'models'
ONNX_ROOT = MODELS / 'onnx'
DATA = ML_TRAIN / 'datasets'
SMP_DIR = DATA / 'ewect_smp2020'
HF_CACHE = ML_TRAIN / '.hf-cache'
os.environ.setdefault('HF_HOME', str(HF_CACHE))
sys.path.insert(0, str(BACKEND))

SEED = 42
MAX_LENGTH = 128

#: the training script's own folding of the published labels onto the project's names
SMP2PROJECT = {
    'angry': 'Anger',
    'fear': 'Fear',
    'happy': 'Joy',
    'neutral': 'Neutral',
    'sad': 'Sadness',
    'surprise': 'Surprise',
}
TENDENCY_LABELS = (
    'Advocacy/Call-to-action',
    'Controversy/Reflection',
    'Criticism/Questioning',
    'Objective Statement',
    'Praise/Affirmation',
    'Satire/Mockery',
)


def corpus_for(operation: str):
    """(texts, gold_labels) for one operation, from the labelled data the trainers used."""
    import random

    import pandas as pd

    if operation == 'sentiment':
        frame = pd.read_csv(DATA / 'weibo_senti_100k.csv', usecols=['label', 'review'])
        pairs = [
            (str(row), ('positive' if int(label) == 1 else 'negative'))
            for label, row in zip(frame['label'], frame['review'], strict=True)
        ]
    elif operation == 'tendency':
        frame = pd.read_csv(DATA / 'controversy_labeled.csv', usecols=['text', 'tendency'])
        pairs = [
            (str(text).strip(), str(label).strip())
            for text, label in zip(frame['text'], frame['tendency'], strict=True)
            if str(label).strip() in TENDENCY_LABELS
        ]
    elif operation == 'emotion':
        # EWD/SMP2020 ships its JSON arrays with a ``.txt`` extension, and only the ``*_labeled``
        # copies carry the label (the bare ones are the leaderboard files). Same reader the emotion
        # trainer uses — see ``train_emotion_bert.load_records``.
        holders = sorted(SMP_DIR.rglob('*_labeled.txt'))
        if not holders:
            raise SystemExit(f'EWD 标注文件不在预期的位置：{SMP_DIR} 下找不到 *_labeled.txt')
        pairs = []
        for holder in holders:
            for row in json.loads(holder.read_text(encoding='utf-8')):
                label = SMP2PROJECT.get(str(row.get('label') or '').strip().lower())
                content = str(row.get('content') or '').strip()
                if label and content:
                    pairs.append((content, label))
    else:
        raise SystemExit(f'没有为操作 {operation} 准备带标注语料')
    if not pairs:
        raise SystemExit(f'操作 {operation} 的语料读出来是空的，无法对照')
    random.seed(SEED)
    random.shuffle(pairs)
    return [text for text, _ in pairs], [label for _, label in pairs]


def score_rows(rows, golds, labels):
    """Accuracy and macro-F1 for one predicted label sequence."""
    import numpy as np

    order = sorted(labels)
    matrix = np.zeros((len(order), len(order)), dtype=int)
    index = {name: position for position, name in enumerate(order)}
    correct = 0
    for got, gold in zip(rows, golds, strict=True):
        if got == gold:
            correct += 1
        if got in index and gold in index:
            matrix[index[gold]][index[got]] += 1
    f1s = []
    for position, _name in enumerate(order):
        true_positive = matrix[position][position]
        predicted = matrix[:, position].sum()
        actual = matrix[position, :].sum()
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / actual if actual else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return correct / len(golds), float(sum(f1s) / len(f1s))


def run_batches(classifier, texts, batch: int):
    """Answers plus throughput for one batch size, in the order the rows arrived."""
    labels, probs, started = [], [], time.perf_counter()
    for start in range(0, len(texts), batch):
        chunk = texts[start : start + batch]
        answers = classifier.predict(chunk)
        labels.extend(str(item['label']) for item in answers)
        probs.extend(float(item['score']) for item in answers)
    return labels, probs, len(texts) / (time.perf_counter() - started)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--only', action='append', default=None, help='restrict to this source model directory name')
    parser.add_argument('--rows', type=int, default=150, help='labelled rows to score per model')
    parser.add_argument('--batches', default='8,16,32', help='comma separated batch sizes to time')
    args = parser.parse_args(argv)

    import numpy as np
    from transformers import pipeline

    from analyzers.sentiment import BertClassifier, bert_runtime

    if bert_runtime() != 'torch':
        print('这台机器没有 torch/transformers，无法做 torch 对照（本脚本需要可选栈）', file=sys.stderr)
        return 2

    packs = sorted(ONNX_ROOT.glob('*_onnx_*'))
    if not packs:
        print(f'还没有导出产物：{ONNX_ROOT} 是空的，先跑 export_onnx_bert.py', file=sys.stderr)
        return 2
    batches = [int(item) for item in args.batches.split(',') if item.strip()]
    failures = 0
    for folder in packs:
        sidecar = json.loads((folder / 'cixi_bert.json').read_text(encoding='utf-8'))
        source = Path(sidecar.get('source') or (MODELS / folder.name.rsplit('_onnx_', 1)[0]))
        if args.only and source.name not in args.only:
            continue
        operation = sidecar['operation']
        precision = sidecar['precision']
        texts, golds = corpus_for(operation)
        texts, golds = texts[: args.rows], golds[: args.rows]
        labels_order = sorted({str(value) for value in sidecar['id2label'].values()} | set(golds))

        classifier = BertClassifier(str(folder), task='text-classification', runtime='onnx', max_length=MAX_LENGTH)
        # The rows/s this call measured is not thrown away: the timing loop below reports the same
        # batch size, so printing it twice would only give two numbers to disagree.
        onnx_labels, onnx_probs, _ = run_batches(classifier, texts, batches[0])

        torch_call = pipeline('text-classification', model=str(source), device=-1)
        torch_labels, torch_probs = [], []
        for start in range(0, len(texts), batches[0]):
            answers = torch_call(
                texts[start : start + batches[0]],
                batch_size=len(texts[start : start + batches[0]]),
                truncation=True,
                max_length=MAX_LENGTH,
            )
            torch_labels.extend(str(item['label']) for item in answers)
            torch_probs.extend(float(item['score']) for item in answers)

        agree = sum(1 for a, b in zip(onnx_labels, torch_labels, strict=True) if a == b) / len(texts)
        probability_gap = float(np.abs(np.asarray(onnx_probs) - np.asarray(torch_probs)).max())
        torch_accuracy, torch_f1 = score_rows(torch_labels, golds, labels_order)
        onnx_accuracy, onnx_f1 = score_rows(onnx_labels, golds, labels_order)

        timings = []
        for batch in batches:
            _labels, _probs, rate = run_batches(classifier, texts, batch)
            timings.append(f'{batch}→{rate:.1f} 行/秒')
        cold = time.perf_counter()
        BertClassifier(str(folder), task='text-classification', runtime='onnx', max_length=MAX_LENGTH)
        cold_seconds = time.perf_counter() - cold
        del torch_call

        verdict = '可用 int8' if precision == 'int8' and abs(onnx_f1 - torch_f1) <= 0.003 and agree >= 0.99 else ''
        if precision == 'int8' and not verdict:
            verdict = '退回 fp32'
            failures += 1
        print(
            f'{source.name} [{precision}]  与 torch 判定一致率 {agree:.4f}  概率最大差 {probability_gap:.4f}\n'
            f'    torch CPU: accuracy {torch_accuracy:.4f} macro-F1 {torch_f1:.4f}\n'
            f'    onnx     : accuracy {onnx_accuracy:.4f} macro-F1 {onnx_f1:.4f}  ΔF1 {onnx_f1 - torch_f1:+.4f}\n'
            f'    吞吐 {", ".join(timings)}（batch={batches[0]} 计时），冷加载 {cold_seconds:.2f} s，'
            f'图 {sidecar["bytes"] / 1024 / 1024:.1f} MB  {verdict}',
            flush=True,
        )
    print(f'对照完成：{len(packs)} 个目录，需要退回 fp32 的 int8 包 {failures} 个')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
