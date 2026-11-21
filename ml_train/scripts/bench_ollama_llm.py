"""Compare locally pulled Ollama tags on Chinese multiple-choice AND short-label work.

One process, one daemon, fixed seeds and fixed prompts. The report records accuracy, tokens/s,
rows/s and the tag's on-disk size — a smaller model only wins if it is both fast and accurate.
No backend imports: an app-level syntax error elsewhere must not block this offline benchmark.
"""

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import _env
import pandas as pd
import requests

MCQ_PROMPT = (
    '你是一位严谨的中文多项选择题答题者。请只回答一个选项字母（A/B/C/D），不要解释。\n'
    '题目：{question}\nA. {a}\nB. {b}\nC. {c}\nD. {d}\n答案：'
)
SENTIMENT_PROMPT = '判断下面这条中文评论的情感极性。只回答“正面”或“负面”两个字，不要解释。\n评论：{text}\n极性：'
SEED = 42


def _chat(host: str, model: str, prompt: str, max_tokens: int) -> tuple[str, int, float]:
    started = time.perf_counter()
    response = requests.post(
        host + '/api/chat',
        json={
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'stream': False,
            'think': False,
            'options': {'temperature': 0, 'num_ctx': 4096, 'num_predict': max_tokens},
        },
        timeout=120,
    )
    response.raise_for_status()
    body = response.json()
    text = str((body.get('message') or {}).get('content') or '')
    return text, int(body.get('eval_count') or 0), time.perf_counter() - started


def _mcq_rows(limit: int) -> list[dict]:
    root = Path(_env.DATASETS_DIR) / 'evaluation' / 'multiple_choice' / 'ceval_val'
    files = sorted(root.rglob('*.parquet'))
    if not files:
        raise FileNotFoundError(f'{root}: run fetch_assets.py --kind datasets --only ceval-val')
    rows = []
    for path in files:
        frame = pd.read_parquet(path)
        wanted = ['question', 'A', 'B', 'C', 'D', 'answer']
        if not set(wanted).issubset(frame.columns):
            raise ValueError(f'{path}: expected {wanted}, got {list(frame.columns)}')
        for row in frame[wanted].itertuples(index=False):
            if str(row.answer).strip().upper() in {'A', 'B', 'C', 'D'}:
                rows.append(
                    {
                        'question': str(row.question),
                        'a': str(row.A),
                        'b': str(row.B),
                        'c': str(row.C),
                        'd': str(row.D),
                        'answer': str(row.answer).strip().upper(),
                        'subject': path.parent.name,
                    }
                )
    random.Random(SEED).shuffle(rows)
    return rows[:limit]


def _sentiment_rows(limit: int) -> list[dict]:
    path = Path(_env.DATASETS_DIR) / 'weibo_senti_100k.csv'
    frame = pd.read_csv(path, usecols=['label', 'review'])
    by_label: dict[int, list[str]] = {0: [], 1: []}
    for label, text in zip(frame['label'], frame['review'], strict=True):
        text = str(text).strip()
        if text:
            by_label[int(label)].append(text)
    rng = random.Random(SEED)
    for group in by_label.values():
        rng.shuffle(group)
    half = max(1, limit // 2)
    rows = [{'text': text, 'answer': '正面'} for text in by_label[1][:half]]
    rows += [{'text': text, 'answer': '负面'} for text in by_label[0][:half]]
    rng.shuffle(rows)
    return rows


def _score(model: str, host: str, suite: str, rows: list[dict], max_tokens: int) -> dict:
    correct = 0
    tokens = 0
    seconds = 0.0
    samples = []
    for row in rows:
        prompt = MCQ_PROMPT.format(**row) if suite == 'multiple_choice' else SENTIMENT_PROMPT.format(**row)
        try:
            answer, used_tokens, elapsed = _chat(host, model, prompt, max_tokens)
            tokens += used_tokens
            seconds += elapsed
        except Exception as exc:
            answer, used_tokens = '', 0
            samples.append({'error': f'{type(exc).__name__}: {exc}'})
            continue
        if suite == 'multiple_choice':
            match = re.search(r'\b([ABCD])\b', answer.upper())
            predicted = match.group(1) if match else ''
        else:
            predicted = '正面' if '正面' in answer[:6] else ('负面' if '负面' in answer[:6] else '')
        correct += int(predicted == row['answer'])
        if len(samples) < 5:
            samples.append({'expected': row['answer'], 'predicted': predicted, 'raw': answer[:80]})
    return {
        'model': model,
        'suite': suite,
        'rows': len(rows),
        'accuracy': round(correct / max(1, len(rows)), 4),
        'tokens': tokens,
        'seconds': round(seconds, 2),
        'tokens_per_sec': round(tokens / max(0.01, seconds), 1),
        'calls_per_sec': round(len(rows) / max(0.01, seconds), 2),
        'samples': samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', required=True, help='comma-separated Ollama tags')
    parser.add_argument('--host', default=os.environ.get('OLLAMA_HOST') or 'http://localhost:11434')
    parser.add_argument('--mcq-rows', type=int, default=100)
    parser.add_argument('--sentiment-rows', type=int, default=60)
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    host = args.host.rstrip('/')

    tags = {row['name']: row for row in requests.get(host + '/api/tags', timeout=10).json().get('models', [])}
    mcq = _mcq_rows(args.mcq_rows)
    sentiment = _sentiment_rows(args.sentiment_rows)
    print(f'mcq={len(mcq)} sentiment={len(sentiment)}', flush=True)

    results = []
    for model in [item.strip() for item in args.models.split(',') if item.strip()]:
        size_gb = round(int(tags.get(model, {}).get('size') or 0) / 1e9, 2)
        try:
            _chat(host, model, MCQ_PROMPT.format(**mcq[0]), 8)
        except Exception as exc:
            results.append({'model': model, 'error': f'{type(exc).__name__}: {exc}'})
            print(f'[{model}] ERROR {exc}', flush=True)
            continue
        print(f'[{model}] {size_gb}GB', flush=True)
        for suite, rows, max_tokens in (
            ('multiple_choice', mcq, 8),
            ('sentiment', sentiment, 4),
        ):
            result = _score(model, host, suite, rows, max_tokens)
            result['size_gb'] = size_gb
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)

    report = {
        'schema': 1,
        'seed': SEED,
        'host': host,
        'measured_utc': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
        'results': results,
    }
    out = (
        Path(args.out)
        if args.out
        else Path(_env.LOGS_DIR) / 'llm_bench' / f'ollama_{time.strftime("%Y%m%d_%H%M%S")}.json'
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'report={out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
