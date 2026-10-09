"""Soft-label distillation capture: for each already-distilled text, sample the local LLM k times at
temperature>0 and tally the answers into a 6-class probability vector — the teacher's DISTRIBUTION,
not just its argmax. Training the encoder to match that (KL) is the soft-label distillation step:
it carries the teacher's uncertainty structure, which usually helps the rare/ambiguous class most.

Reuses the node's OWN analyzer + LLM transport (exactly like distill_tendency_labels.py), so the taxonomy and
prompt match what the bert mode is read against. Resumable: texts already in the output are skipped.

    .venv/Scripts/python.exe ml_train/scripts/distill_tendency_softlabel.py --samples 5 --temp 0.6 --workers 6

Input : ml_train/datasets/tendency_distilled.csv   (text, tendency) — the hard-labelled corpus
Output: ml_train/datasets/tendency_distilled_soft.csv  (text, tendency, prob_<label> x6)
"""

import argparse
import csv
import os
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


def main():
    ap = argparse.ArgumentParser(description='Capture soft (k-sampled) tendency distributions from the local LLM.')
    ap.add_argument('--in', dest='in_csv', default=os.path.join(DATA, 'tendency_distilled.csv'))
    ap.add_argument('--out', default=os.path.join(DATA, 'tendency_distilled_soft.csv'))
    ap.add_argument('--samples', type=int, default=5, help='LLM draws per text (self-consistency)')
    ap.add_argument('--temp', type=float, default=0.6, help='sampling temperature; 0 would collapse to the hard label')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--model', default='qwen3.5:9b')
    ap.add_argument('--host', default='http://localhost:11434')
    ap.add_argument('--limit', type=int, default=0, help='process only the first N texts (0=all) — measure throughput')
    args = ap.parse_args()

    analyzer = TendencyAnalyzer()
    labels = list(analyzer.valid_labels)
    idx = {lab: i for i, lab in enumerate(labels)}
    client = LLMClient(
        provider='ollama',
        model=args.model,
        host=args.host,
        temperature=args.temp,
        max_tokens=48,
        max_chars=300,
        timeout=120,
    )

    df = pd.read_csv(args.in_csv, usecols=['text', 'tendency'])
    df = df[df['text'].astype(str).str.strip() != '']
    done = set()
    if os.path.isfile(args.out):
        with open(args.out, encoding='utf-8', newline='') as fh:
            done = {r['text'] for r in csv.DictReader(fh)}
    rows = [
        (str(t).strip(), lab) for t, lab in zip(df['text'], df['tendency'], strict=True) if str(t).strip() not in done
    ]
    if args.limit:
        rows = rows[: args.limit]
    print(f'{len(df)} distilled texts; {len(done)} already soft; sampling {len(rows)} x {args.samples}', flush=True)

    lock = threading.Lock()
    new_file = not os.path.isfile(args.out)
    out_fh = open(args.out, 'a', encoding='utf-8', newline='')
    writer = csv.writer(out_fh)
    if new_file:
        writer.writerow(['text', 'tendency'] + [f'prob_{l}' for l in labels])
        out_fh.flush()

    state = {'i': 0, 'err': 0}

    def one(item):
        text, hard = item
        counts = [0] * len(labels)
        answered = 0
        for _ in range(args.samples):
            try:
                reply = client.chat(analyzer.build_tendency_prompt(text))
            except LLMError:
                with lock:
                    state['err'] += 1
                continue
            parsed = analyzer.parse_tendency_response(reply)
            lab = parsed[0] if parsed and parsed[0] in idx else None
            if lab is not None:
                counts[idx[lab]] += 1
                answered += 1
        denom = answered or 1
        probs = [round(c / denom, 4) for c in counts]
        if answered == 0:  # every draw errored/unparseable: fall back to the hard label one-hot
            probs = [1.0 if i == idx.get(hard, -1) else 0.0 for i in range(len(labels))]
        with lock:
            writer.writerow([text, hard] + probs)
            out_fh.flush()
            state['i'] += 1
            if state['i'] % 100 == 0:
                print(f'  {state["i"]}/{len(rows)}  err_draws={state["err"]}', flush=True)

    start = time.time()
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(one, rows))
    out_fh.close()
    mins = (time.time() - start) / 60
    rate = len(rows) / mins if mins else 0
    print(f'\nsoft-distilled {state["i"]} texts in {mins:.1f} min ({rate:.1f} texts/min, {args.samples} draws each)')
    print(f'-> {args.out}')


if __name__ == '__main__':
    main()
