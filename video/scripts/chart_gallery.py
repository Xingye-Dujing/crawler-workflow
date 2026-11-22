#!/usr/bin/env python3
"""Render every chart type as a real figure for the promo's feature gallery.

Each figure is produced by the app's own ``/api/visualize/render`` (the exact
same path the visualize node and Chart Studio use), then drawn by ECharts in a
real browser at full frame and captured as a lossless 2x PNG. Nothing is
redrawn — these are the product's real charts on real data.

Data sources (all real, from the isolated film data root):
  * console charts: the 600-row comment dataset / XHS figure table / inline data
  * bibliometric charts: the 108 rows the showcase_biblio run's biblio node filed.

Usage:
    python video/scripts/chart_gallery.py            # all charts
    python video/scripts/chart_gallery.py --only knowledge_graph,bar
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
GALLERY = ROOT / 'video' / 'public' / 'real' / 'gallery'

# load the capture helpers (Browser, start_server, http_json, stop_process_tree)
_spec = importlib.util.spec_from_file_location('browser_capture', HERE / 'browser_capture.py')
cap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cap)

# ---------------------------------------------------------------------------
# Data: console charts use inline rows; biblio charts use the filed node-7 rows.
# ---------------------------------------------------------------------------
CONSOLE_ROWS = [
    {'类别': '正面', '年份': '2020', '数值': 13, '数值2': 6, '城市': '北京', '文本': '菜品很新鲜，服务周到'},
    {'类别': '负面', '年份': '2021', '数值': 10, '数值2': 4, '城市': '上海', '文本': '味道一般，不会再来'},
    {'类别': '中性', '年份': '2022', '数值': 1, '数值2': 2, '城市': '广州', '文本': '还行吧，凑合'},
    {'类别': '正面', '年份': '2023', '数值': 18, '数值2': 9, '城市': '深圳', '文本': '非常满意，下次还来'},
    {'类别': '负面', '年份': '2024', '数值': 7, '数值2': 3, '城市': '杭州', '文本': '上菜慢，价格贵'},
    {'类别': '正面', '年份': '2025', '数值': 22, '数值2': 11, '城市': '成都', '文本': '味道正宗，环境好'},
]

# chart_type -> (family, extra params)
CONSOLE_CHARTS: dict[str, dict] = {
    'bar': {'x_field': '类别', 'y_field': '数值'},
    'line': {'x_field': '年份', 'y_field': '数值'},
    'dual_line': {'x_field': '年份', 'y_field': '数值', 'y2_field': '数值2'},
    'stack_pct': {'x_field': '年份', 'stack_fields': '数值,数值2'},
    'pie': {'x_field': '类别', 'y_field': '数值'},
    'scatter': {'x_field': '数值', 'y_field': '数值2'},
    'histogram': {'x_field': '数值'},
    'box': {'x_field': '类别', 'y_field': '数值'},
    'heatmap': {'x_field': '类别', 'y_field': '城市', 'value_field': '数值'},
    'sankey': {'x_field': '类别', 'y_field': '城市', 'value_field': '数值'},
    'network': {'x_field': '类别', 'y_field': '城市', 'value_field': '数值'},
    'wordcloud': {'x_field': '文本', 'tokenize': True},
    'map': {'x_field': '城市', 'value_field': '数值'},
    'topic_map': {'x_field': '数值', 'y_field': '数值2', 'label_field': '类别', 'value_field': '数值'},
    'topic_terms': {'x_field': '类别', 'y_field': '数值', 'y2_field': '数值2'},
    'model_agreement': {'agreement_label_field': '标签'},  # uses MODEL_ROWS below
}

# A tidy multi-model agreement table: 3 models labelling the same 10 rows.
MODEL_ROWS: list[dict] = []
for i, lab in enumerate(
    [
        'positive',
        'positive',
        'negative',
        'neutral',
        'positive',
        'negative',
        'neutral',
        'positive',
        'negative',
        'neutral',
    ]
):
    MODEL_ROWS.append({'模型': 'BERT', '标签': lab, '原行': i})
    MODEL_ROWS.append({'模型': 'SnowNLP', '标签': lab if i % 3 else 'neutral', '原行': i})
    MODEL_ROWS.append({'模型': '机器学习', '标签': lab if i % 4 else 'positive', '原行': i})
BIBLIO_CHARTS: list[str] = [
    'knowledge_graph',
    'cluster_timeline',
    'burst',
    'timezone',
    'circular',
    'landscape',
    'biblio_heatmap',
    'graph3d',
    'concentric',
]


def filed_biblio_rows(data_root: Path) -> list[dict]:
    db = data_root / 'data' / 'runs.db'
    con = sqlite3.connect(str(db))
    try:
        rid = con.execute('SELECT run_id FROM runs LIMIT 1').fetchone()
        if not rid:
            raise RuntimeError('no run in runs.db; run showcase_biblio first')
        rows = [
            json.loads(r[0])
            for r in con.execute(
                'SELECT payload FROM node_rows WHERE run_id=? AND node_id=? ORDER BY seq',
                (rid[0], 'node-7'),
            )
        ]
    finally:
        con.close()
    if not rows:
        raise RuntimeError('biblio node-7 filed no rows')
    return rows


def render_and_shot(b: cap.Browser, chart_type: str, rows: list[dict], params: dict, name: str) -> None:
    payload = {
        'data': rows,
        'chart_type': chart_type,
        'engine': 'echarts',
        'emit_latex': False,
        'emit_latex_table': False,
        **params,
    }
    body = json.dumps(payload, ensure_ascii=False)
    # Render in-browser: fetch the app's real option, paint with ECharts in a
    # full-viewport div, then screenshot losslessly.
    expr = (
        '(async () => {'
        'const body=' + json.dumps(body, ensure_ascii=False) + ';'
        "const r=await fetch('/api/visualize/render',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:body});"
        'const j=await r.json();'
        "if(!j.ok) return {ok:false,error:j.error||('http '+r.status)};"
        "let old=document.getElementById('cxi-gallery');"
        'if(old) old.remove();'
        "const d=document.createElement('div');d.id='cxi-gallery';"
        "d.style.cssText='position:fixed;left:0;top:0;width:100vw;height:100vh;"
        "background:#ffffff;z-index:999999;';"
        'document.body.appendChild(d);'
        "if(j.engine==='matplotlib'){"
        "  const im=document.createElement('img');im.src=j.image;"
        "  im.style.cssText='width:100%;height:100%;object-fit:contain';d.appendChild(im);"
        '} else {'
        '  if(' + json.dumps(chart_type) + "==='map' || " + json.dumps(chart_type) + "==='geo_map') {"
        "    try { await ensureMapRegistered('china'); await ensureMapRegistered('world'); } catch(e) {}"
        '  }'
        '  const c=echarts.init(d);c.setOption(j.option,true);'
        '  window.__galleryChart=c;'
        '}'
        'return {ok:true,engine:j.engine};'
        '})()'
    )
    res = b.js(expr)
    if not res or not res.get('ok'):
        raise RuntimeError(f'{chart_type}: render failed: {res}')
    time.sleep(1.2)
    b.shot(name)
    b.js("(() => { const d=document.getElementById('cxi-gallery'); if(d) d.remove(); })()")
    time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', default=None, help='comma-separated chart types')
    parser.add_argument('--data-root', default=ROOT / 'video' / '.data', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--url', default=None, help='existing server URL (no server started)')
    args = parser.parse_args()

    GALLERY.mkdir(parents=True, exist_ok=True)
    server = None
    if args.url:
        url = args.url.rstrip('/') + '/'
    else:
        data_root = args.data_root.resolve()
        port = args.port or cap.free_port()
        server = cap.start_server(data_root, port)
        url = f'http://127.0.0.1:{port}/'
    try:
        b = cap.Browser(url, 'film', GALLERY, headless=True)
        try:
            b.open(url)
            b.sleep(1.0)
            biblio = filed_biblio_rows(args.data_root.resolve())
            only = set(args.only.split(',')) if args.only else None
            jobs: list[tuple[str, list[dict], dict]] = []
            for ct, params in CONSOLE_CHARTS.items():
                if only is None or ct in only:
                    rows = MODEL_ROWS if ct == 'model_agreement' else CONSOLE_ROWS
                    jobs.append((ct, rows, params))
            for ct in BIBLIO_CHARTS:
                if only is None or ct in only:
                    jobs.append((ct, biblio, {}))
            done = 0
            for ct, rows, params in jobs:
                print(f'  chart: {ct}')
                try:
                    render_and_shot(b, ct, rows, params, f'chart-{ct}.png')
                    done += 1
                except Exception as exc:  # noqa: BLE001
                    print(f'    ! {ct}: {str(exc)[:160]}')
            print(f'  {done}/{len(jobs)} charts rendered')
        finally:
            b.close()
    finally:
        if server is not None:
            cap.stop_process_tree(*server)
    return 0


if __name__ == '__main__':
    sys.exit(main())
