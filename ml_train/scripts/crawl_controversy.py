"""Drive a REAL two-stage Weibo comment crawl through the app's own tested execution path
(boot server → POST /api/workflow/execute → poll /api/workflow/status), NOT a hand-rolled crawler.

Two stages, because the comment crawl takes explicit post URLs (it does not auto-consume an upstream
keyword crawl):
  Stage 1  source(weibo, collect=posts, keyword=KW, target_count=NP) -> output(save)  => post urls
  Stage 2  source(weibo, collect=comments, urls=<those>, comment_limit=NC) -> output(save) => comments

Booted on the REAL data root so it uses the logged-in weibo profile/cookie. Results are saved to
ml_train/datasets/controversy_crawl.csv with provenance (keyword, source_url, crawled_at) so the run is
traceable. Bounded by default (one keyword, small counts) — scale with --keywords.

    cd backend && python ../ml_train/scripts/crawl_controversy.py --keywords 网暴 --posts 12 --per-post 15
"""

import argparse
import csv
import glob
import os
import subprocess
import sys
import time

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ml_train
REPO = os.path.dirname(ROOT)  # repo root (holds backend/ and data/)
DATA = os.path.join(ROOT, 'datasets')
BACKEND = os.path.abspath(os.path.join(REPO, 'backend'))
EXPORT_DIR = os.path.abspath(os.path.join(REPO, 'data', 'exports'))
BASE = 'http://127.0.0.1:5000'


def boot_server():
    env = dict(os.environ, PORT='5000')
    proc = subprocess.Popen(
        [sys.executable, 'app.py'], cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
    )
    for _ in range(40):
        try:
            if requests.get(f'{BASE}/api/config', timeout=2).status_code < 500:
                return proc
        except requests.RequestException:
            pass
        if proc.poll() is not None:
            raise RuntimeError('server exited during boot')
        time.sleep(1)
    raise RuntimeError('server did not come up in 40s')


def execute(workflow, name):
    r = requests.post(
        f'{BASE}/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name, 'queue': False}, timeout=30
    )
    body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {'raw': r.text}
    if r.status_code != 200:
        raise RuntimeError(f'execute refused ({r.status_code}): {body}')
    return body


def wait_done(timeout=360):
    """Poll until the run stops; return the final status body (raises on a failed run)."""
    deadline = time.time() + timeout
    time.sleep(2)
    while time.time() < deadline:
        s = requests.get(f'{BASE}/api/workflow/status', timeout=10).json()
        if not s.get('running'):
            logs = ' | '.join(str(l) for l in (s.get('global_logs') or [])[-12:])
            if '失败' in logs or 'error' in logs.lower():
                print('  status tail:', logs[:400])
            return s
        time.sleep(4)
    raise TimeoutError(f'run did not finish in {timeout}s')


def _wf(nodes, conns):
    return {'settings': {'mode': 'serial', 'headless': True, 'use_profile': True}, 'nodes': nodes, 'connections': conns}


def _source(nid, params):
    return {'id': nid, 'type': 'source', 'params': dict(params, enabled=True)}


def _output(nid, filename):
    return {
        'id': nid,
        'type': 'output',
        'params': {
            'operation': 'save',
            'format': 'csv',
            'filename': filename,
            'filename_timestamp': False,
            'enabled': True,
        },
    }


def newest_export(prefix):
    files = [f for f in glob.glob(os.path.join(EXPORT_DIR, f'{prefix}*.csv'))]
    return max(files, key=os.path.getmtime) if files else ''


def crawl_keyword(keyword, posts, per_post, open_n, stamp, start_time='', end_time=''):
    pslug = ''.join(ch for ch in keyword if ch.isalnum()) or 'kw'
    posts_file = f'cixi_posts_{pslug}'
    comments_file = f'cixi_comments_{pslug}'
    for f in glob.glob(os.path.join(EXPORT_DIR, f'{posts_file}*.csv')) + glob.glob(
        os.path.join(EXPORT_DIR, f'{comments_file}*.csv')
    ):
        os.remove(f)

    print(
        f'--- Stage 1: crawl {posts} posts for 「{keyword}」 window={start_time or "-"}..{end_time or "-"} ---',
        flush=True,
    )
    execute(
        _wf(
            [
                _source(
                    'n1',
                    {
                        'platform': 'weibo',
                        'collect': 'posts',
                        'keyword': keyword,
                        'target_count': posts,
                        'start_time': start_time or '',
                        'end_time': end_time or '',
                        'account': 'default',
                        'format': 'csv',
                    },
                ),
                _output('n2', f'{posts_file}.csv'),
            ],
            [{'from': 'n1', 'to': 'n2'}],
        ),
        f'posts_{pslug}',
    )
    wait_done()
    pf = newest_export(posts_file)
    if not pf:
        print('  no posts export found; skipping')
        return []
    posts_df = pd.read_csv(pf, dtype=str)
    url_col = next((c for c in ('链接', 'url', '微博链接') if c in posts_df.columns), None)
    if not url_col:
        print('  no url column')
        return []
    # Open the comment-RICH threads first: a fresh keyword page is mostly 0-comment posts, so
    # sorting by the site's own 评论数 makes stage 2 spend its browser walks on threads that
    # actually have comments (the first run yielded ~4 because it opened the thin top of the list).
    max_n = '?'
    if '评论数' in posts_df.columns:
        posts_df['_n'] = pd.to_numeric(posts_df['评论数'], errors='coerce').fillna(0)
        posts_df = posts_df.sort_values('_n', ascending=False)
        max_n = int(posts_df['_n'].max())
    urls = [u for u in posts_df[url_col].dropna().astype(str) if u.startswith('http')][:open_n]
    print(f'  {len(posts_df)} posts; opening top {len(urls)} by 评论数 (max={max_n})', flush=True)
    if not urls:
        return []

    print(f'--- Stage 2: crawl up to {per_post} comments x {len(urls)} posts ---', flush=True)
    execute(
        _wf(
            [
                _source(
                    'n1',
                    {
                        'platform': 'weibo',
                        'collect': 'comments',
                        'urls': '\n'.join(urls),
                        'comment_limit': per_post,
                        'account': 'default',
                        'format': 'csv',
                    },
                ),
                _output('n2', f'{comments_file}.csv'),
            ],
            [{'from': 'n1', 'to': 'n2'}],
        ),
        f'comments_{pslug}',
    )
    wait_done()
    cf = newest_export(comments_file)
    if not cf:
        print('  no comments export found')
        return []
    cdf = pd.read_csv(cf, dtype=str)
    text_col = next((c for c in ('评论内容', '评论', '正文', '内容', 'text') if c in cdf.columns), None)
    src_col = next((c for c in ('链接', 'source_url', 'url', '文章链接') if c in cdf.columns), None)
    rows = []
    for _, r in cdf.iterrows():
        text = str(r[text_col]).strip() if text_col and pd.notna(r[text_col]) else ''
        if len(text) >= 5:
            rows.append(
                {
                    'text': text,
                    'keyword': keyword,
                    'source_url': str(r[src_col]) if src_col and pd.notna(r[src_col]) else '',
                    'crawled_at': stamp,
                }
            )
    print(f'  saved {len(rows)} comment rows from {os.path.basename(cf)}', flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser(description='Two-stage weibo comment crawl via the real server.')
    ap.add_argument('--keywords', default='网暴')
    ap.add_argument(
        '--plan',
        default='',
        help='events as "keyword:2025-08-01:2025-08-31;keyword2:start:end" — each event\'s heat window (overrides --keywords)',
    )
    ap.add_argument('--posts', type=int, default=60, help='posts to crawl in stage 1 (widen the net)')
    ap.add_argument('--open', dest='open_n', type=int, default=25, help='comment-rich posts to open in stage 2')
    ap.add_argument('--per-post', type=int, default=15)
    ap.add_argument('--out', default=os.path.join(DATA, 'controversy_crawl.csv'))
    args = ap.parse_args()

    if args.plan.strip():
        jobs = []
        for part in args.plan.split(';'):
            seg = [s.strip() for s in part.split(':')]
            if seg and seg[0]:
                jobs.append((seg[0], seg[1] if len(seg) > 1 else '', seg[2] if len(seg) > 2 else ''))
    else:
        jobs = [(k.strip(), '', '') for k in args.keywords.split(',') if k.strip()]

    stamp = time.strftime('%Y-%m-%d %H:%M')
    proc = boot_server()
    print('server booted (real data root, weibo profile)', flush=True)
    # Append each event's rows to the output IMMEDIATELY, so a mid-run throttle/wall keeps the
    # completed events instead of losing all 13 to one crash at the end.
    new_file = not os.path.isfile(args.out)
    out_fh = open(args.out, 'a', encoding='utf-8', newline='')
    writer = csv.writer(out_fh)
    if new_file:
        writer.writerow(['text', 'keyword', 'source_url', 'crawled_at'])
        out_fh.flush()
    total = 0
    try:
        for kw, st, en in jobs:
            try:
                rows = crawl_keyword(kw, args.posts, args.per_post, args.open_n, stamp, st, en)
            except Exception as e:  # noqa: BLE001  (one bad event must not abort the rest of the plan)
                print(f'!! {kw} failed: {type(e).__name__}: {str(e)[:160]}', flush=True)
                rows = []
            for r in rows:
                writer.writerow([r['text'], r['keyword'], r['source_url'], r.get('crawled_at', stamp)])
            out_fh.flush()
            total += len(rows)
            print(f'== {kw}: +{len(rows)} comments (running total {total}) ==', flush=True)
    finally:
        out_fh.close()
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        print('server stopped', flush=True)

    print(f'\nTOTAL appended {total} comment rows this run -> {args.out}')


if __name__ == '__main__':
    main()
