/* Runs the REAL stats.js (backend/static/js/stats.js) under node.

   ECharts is a <script> from a CDN in index.html, and this is a local tool that is
   sometimes opened offline. stats.init() used to call `echarts.init` unguarded as one
   of the first statements of the page's single DOMContentLoaded body, so a missing
   CDN killed every later step with it — the Data Source panel's capability fetch, the
   dataset re-link, the autosave interval and the 断点续跑 banner — while the screen
   showed nothing but an empty stats panel.

   Reports what each entry point did WITH and WITHOUT the library present, so the
   guard, the note it renders and the resize path are all executed for real.

   Usage: node harness_stats.mjs <path/to/stats.js> <scenarios.json>
   scenarios.json = [ { "id": "...", "echarts": true|false, "call": "init|refresh|
                        renderPie", "stats": {...} } ]

   `switchTab` is not driven here: it starts by looking up the panel's own tab
   buttons (`.tab-btn:first-child`), which the shared fake DOM does not model —
   that is page markup, not the thing under test.
*/
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const src = fs.readFileSync(process.argv[2], 'utf8');
const scenarios = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

function makeSandbox(withEcharts) {
    const sandbox = {
        ...baseSandbox(),
        I18n: { lang: 'en', t: (k) => `i18n:${k}` },
        console: { log: () => {}, error: () => {}, warn: () => {} },
    };
    const charts = [];
    /* baseSandbox() ships an echarts stand-in for the harnesses that only need the
       page not to crash. The library's PRESENCE is the subject here, so it is
       replaced with a recording one — or deleted outright, which is the offline
       case the whole guard exists for. */
    if (withEcharts) {
        sandbox.echarts = {
            init(node) {
                const chart = {
                    node,
                    options: [],
                    resized: 0,
                    setOption(o) {
                        this.options.push(o);
                    },
                    resize() {
                        this.resized++;
                    },
                };
                charts.push(chart);
                return chart;
            },
        };
    } else {
        delete sandbox.echarts;
    }
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    vm.runInContext(src + '\n;globalThis.__stats = stats;', sandbox);
    sandbox.__charts = charts;
    return sandbox;
}

const out = {};
for (const sc of scenarios) {
    const sandbox = makeSandbox(sc.echarts !== false);
    const stats = sandbox.__stats;
    const result = { threw: null, unavailable: false, charts: 0, note: '', option: null };
    try {
        if (sc.call === 'init') stats.init();
        if (sc.call === 'refresh') await stats.refresh();
        if (sc.call === 'renderPie') {
            stats.init();
            if (sandbox.__charts.length) {
                stats.renderPie(sandbox.__charts[0], sc.stats || { labels: ['Joy'], values: [3] });
                result.option = sandbox.__charts[0].options[0] || null;
            }
        }
    } catch (e) {
        result.threw = `${e && e.name}: ${(e && e.message) || e}`;
    }
    result.unavailable = !!stats.unavailable;
    /* Counted AFTER the call — the number of charts built IS the question. */
    result.charts = sandbox.__charts.length;
    result.emotionChartNull = stats.emotionChart === null;
    const box = sandbox.__byId('chart-emotion');
    const kids = (box && box.children) || [];
    result.note = kids.length ? kids[0].textContent || '' : '';
    result.noteIsElement = kids.length === 1 && !!kids[0].className;
    result.children = kids.length;
    out[sc.id] = result;
}

process.stdout.write(JSON.stringify(out));
