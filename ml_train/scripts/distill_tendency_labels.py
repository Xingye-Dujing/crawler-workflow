"""Distill a tendency-labelled corpus from the local LLM, to fine-tune the tendency node's
``bert`` mode (train_tendency_bert_v1.py).

Why distillation: unlike emotion (which had the public SMP2020-EWECT corpus), tendency has no
released six-class dataset. So we ask the very model the node's ``llm`` mode uses — qwen3.5
on Ollama — to label a pile of real Weibo text, keep only the rows it answers cleanly, and let
a BERT learn that mapping. The BERT then does in one forward pass what ``llm`` mode pays a row
of generation for.

This is the accepted one-off probe location (ml_train/ is gitignored, nothing in backend/
points here), but it imports backend's TendencyAnalyzer on purpose: the distilled label set,
prompt and parser must be EXACTLY the node's, or the fine-tuned model would teach the bert
mode a different taxonomy than the one it is read against.

    # laptop, Ollama running with the named model pulled:
    .venv/Scripts/python.exe ml_train/scripts/distill_tendency_labels.py \
        --n 15000 --cap 3500 --workers 6 --model qwen3.5:9b

Feedstock is ``datasets/weibo_clean_265k.csv`` (265k real Weibo comments; its own ``label`` column is
the EMOTION scheme and is ignored — we only reuse ``text``). Re-running skips texts already in
the output, so an interrupted pass resumes instead of re-paying. Only rows whose reply parses
to one of the six tendency labels are written; everything else is counted as a miss, never
guessed. ``--cap`` bounds each class so ``Objective Statement`` (the default for short/vague
text) cannot swamp the rare stances.
"""

import argparse
import csv
import os
import random
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
REPO = os.path.dirname(ROOT)  # repo root (holds backend/)
DATA = os.path.join(ROOT, 'datasets')
sys.path.insert(0, os.path.join(REPO, 'backend'))

import pandas as pd  # noqa: E402

from analyzers.llm_client import LLMClient, LLMError  # noqa: E402
from analyzers.tendency import TendencyAnalyzer  # noqa: E402

SEED = 42


def load_texts(in_csv, min_len):
    df = pd.read_csv(in_csv, usecols=['text'])
    texts = [str(t).strip() for t in df['text'] if str(t).strip() and len(str(t).strip()) >= min_len]
    seen, uniq = set(), []
    for t in texts:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def load_done(out_csv):
    if not os.path.isfile(out_csv):
        return set()
    with open(out_csv, encoding='utf-8', newline='') as fh:
        return {row['text'] for row in csv.DictReader(fh)}


def main():
    parser = argparse.ArgumentParser(description='Distill tendency labels from the local LLM.')
    parser.add_argument('--in', dest='in_csv', default=os.path.join(DATA, 'weibo_clean_265k.csv'))
    parser.add_argument('--out', default=os.path.join(DATA, 'tendency_distilled.csv'))
    parser.add_argument('--n', type=int, default=15000, help='sample size (0 = every not-yet-done text)')
    parser.add_argument('--cap', type=int, default=3500, help='max rows per class (0 = no cap)')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--host', default='http://localhost:11434')
    parser.add_argument('--min-len', type=int, default=4, help='skip texts shorter than this')
    parser.add_argument('--max-chars', type=int, default=300, help='truncate each text to this before asking')
    args = parser.parse_args()

    analyzer = TendencyAnalyzer()
    valid = set(analyzer.valid_labels)
    client = LLMClient(
        provider='ollama',
        model=args.model,
        host=args.host,
        temperature=0.0,
        max_tokens=48,
        max_chars=args.max_chars,
        timeout=120,
    )

    uniq = load_texts(args.in_csv, args.min_len)
    done = load_done(args.out)
    todo = [t for t in uniq if t not in done]
    random.Random(SEED).shuffle(todo)
    if args.n:
        todo = todo[: args.n]
    print(f'{len(uniq)} unique texts; {len(done)} already distilled; asking {len(todo)} now')

    counts = {label: 0 for label in analyzer.valid_labels}
    # Seed the per-class tallies from what is already on disk so --cap holds across resumes.
    if done:
        with open(args.out, encoding='utf-8', newline='') as fh:
            for row in csv.DictReader(fh):
                lab = row.get('tendency')
                if lab in counts:
                    counts[lab] += 1

    lock = threading.Lock()
    writing = not os.path.isfile(args.out)
    out_fh = open(args.out, 'a', encoding='utf-8', newline='')  # append: resume-friendly
    writer = csv.writer(out_fh)
    if writing:
        writer.writerow(['text', 'tendency'])
        out_fh.flush()

    state = {'answered': 0, 'miss': 0, 'dropped_cap': 0, 'error': 0, 'i': 0}

    def one(text):
        with lock:
            # Check the cap before paying for a call: a full class should stop being sampled.
            over = [label for label in counts if args.cap and counts[label] >= args.cap]
        if len(over) == len(analyzer.valid_labels):
            return
        try:
            reply = client.chat(analyzer.build_tendency_prompt(text))
        except LLMError:
            with lock:
                state['error'] += 1
            return
        parsed = analyzer.parse_tendency_response(reply)
        label = parsed[0] if parsed and parsed[0] in valid else None
        with lock:
            state['i'] += 1
            if label is None:
                state['miss'] += 1
            elif args.cap and counts[label] >= args.cap:
                state['dropped_cap'] += 1
            else:
                writer.writerow([text, label])
                out_fh.flush()
                counts[label] += 1
                state['answered'] += 1
            if state['i'] % 200 == 0:
                print(
                    f'  {state["i"]}/{len(todo)}  answered={state["answered"]} '
                    f'miss={state["miss"]} err={state["error"]} dropped_cap={state["dropped_cap"]}'
                )

    start = time.time()
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(one, todo))
    out_fh.close()

    mins = (time.time() - start) / 60
    print(f'\ndistilled in {mins:.1f} min')
    print(
        f'answered={state["answered"]}  parse-miss={state["miss"]}  errors={state["error"]}  dropped-cap={state["dropped_cap"]}'
    )
    total_on_disk = sum(counts.values())
    print(f'class distribution (on disk, n={total_on_disk}): {dict(sorted(counts.items(), key=lambda x: -x[1]))}')
    print(f'-> {args.out}')


if __name__ == '__main__':
    main()
