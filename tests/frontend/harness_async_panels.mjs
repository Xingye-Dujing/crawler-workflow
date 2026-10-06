/* Panels that answer AFTER a round trip, driven with the fetch held open.
 *
 * Three places in workflow.js look something up, await a request, then write into
 * what they found. What they captured is not what is on screen when the answer
 * lands: `openSettings` rewrites the whole form on every `updateParam`, and the
 * dashboard rebuilds its grid on refresh — so the element each of them held on to
 * can be off the page by then. Writing into an off-page element paints nothing, and
 * the only symptom is "that dropdown never appeared" / "that cell stayed empty",
 * with the panel looking idle and no error anywhere to read.
 *
 * Every case runs twice: once with the page left alone (the answer must still
 * arrive — a guard that refused everything would also pass a test that only
 * measures the refusal) and once with the redraw landing mid-flight.
 *
 * Usage: node harness_async_panels.mjs <workflow.js> <canvas.js>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [wfPath, canvasPath] = process.argv.slice(2);

const I18n = {
    lang: 'en',
    t(k) {
        return k;
    },
};

const RESUME_RUNS = [
    {
        run_id: 'run-77',
        started_at: '2026-09-25 09:00',
        rows_kept: 42,
        nodes: [{ node_id: 'src-1', title: '抓取', row_count: 42 }],
    },
];

const OLLAMA_MODELS = ['m1:latest', 'm2:7b'];

async function ticks(n) {
    for (let i = 0; i < (n || 6); i += 1) await new Promise((r) => setImmediate(r));
}

/* One world per scenario: the panel caches the markup it drew, and a shared one
   would let the second scenario read the first one's page. */
function world(provider) {
    const pending = [];
    const inits = [];
    const sandbox = {
        ...baseSandbox(),
        I18n,
        /* The process panel reads the run-level transport from here to decide
           whether a per-node Ollama model box belongs at all. */
        LLMSettings: { load: () => ({ provider: provider || 'ollama' }) },
        echarts: {
            init(el) {
                inits.push(el);
                return { setOption() {}, resize() {}, dispose() {} };
            },
        },
        canvas: {
            nodes: {},
            connections: [],
            _settingsNodeId: '',
            toWorkflowJSON: () => ({ nodes: Object.values(sandbox.canvas.nodes), connections: [], settings: {} }),
            getUpstreamNodeId: () => 'src-1',
            saveState: () => {},
            updateNodeDisplay: () => {},
            updateSettingsButton: () => {},
            closeSettingsIfStale: () => {},
        },
    };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    vm.runInContext(
        fs.readFileSync(wfPath, 'utf8') + '\n;globalThis.__x = {openSettings, renderResumeSettings, dashboard};',
        sandbox
    );
    /* Every request is captured rather than answered: a scenario decides which one is
       allowed to land, and when. */
    sandbox.fetch = (url, options) =>
        new Promise((resolve) => {
            pending.push({
                url: String(url),
                body: options && options.body ? JSON.parse(options.body) : null,
                answer: () => {
                    const u = String(url);
                    let payload = { ok: true, engine: 'echarts', option: {} };
                    let status = 200;
                    if (u.indexOf('/api/runs/resumable') >= 0) payload = { ok: true, runs: RESUME_RUNS };
                    else if (u.indexOf('/api/llm/ollama/models') >= 0) payload = { ok: true, models: OLLAMA_MODELS };
                    else if (u.indexOf('/api/visualize/render') >= 0 && sandbox.__renderAnswer) {
                        payload = sandbox.__renderAnswer;
                        if (!payload.ok) status = payload.code === 'no_run_data' ? 200 : 400;
                    }
                    resolve({ json: () => Promise.resolve(payload), status });
                },
            });
        });
    return { sandbox, x: sandbox.__x, pending, inits };
}

/* ─── 续跑 node: the two dropdowns it fills from the server ───────────────── */
async function resumeCase(redrawMidFlight) {
    const w = world();
    w.sandbox.canvas.nodes['res-1'] = {
        id: 'res-1',
        type: 'resume',
        title: '续跑',
        params: { resume_run_id: '', resume_node_id: '', resume_limit: 0 },
    };
    w.x.openSettings('res-1');
    if (redrawMidFlight) {
        /* Any parameter edit does this: `updateParam` calls `openSettings`, which
           rewrites the form and replaces the holder the pending request was going to
           fill. The answer is still on its way to the element that used to be there. */
        w.x.openSettings('res-1');
    }
    w.pending[0].answer();
    await ticks();
    const holder = w.sandbox.document.getElementById('resume-pick');
    return {
        drawn: String(holder.innerHTML || '').indexOf('run-77') >= 0,
        /* Proves the scenario is honest rather than a stub artifact: the holder the page
           answers to is the SECOND one when the form was redrawn, and the first is gone. */
        holderNode: holder.dataset ? holder.dataset.node : null,
        asked: w.pending.length,
    };
}

/* ─── dashboard cells ────────────────────────────────────────────────────── */
async function dashCase(redrawMidFlight, tokenize) {
    const w = world();
    w.sandbox.canvas.nodes['v-1'] = {
        id: 'v-1',
        type: 'visualize',
        title: '图',
        params: { chart_type: 'bar', x_field: '城市', engine: 'echarts', tokenize },
    };
    w.x.dashboard.open();
    await ticks(2);
    if (redrawMidFlight) {
        /* A refresh, a language switch, or reopening the panel: the grid is emptied and
           rebuilt, so every cell the in-flight requests hold is off the page. */
        w.sandbox.document.getElementById('dashboard-grid').innerHTML = '';
    }
    w.pending[0].answer();
    await ticks();
    return {
        inits: w.inits.length,
        /* An instance registered for a cell nobody can see is resized on every window
           resize for the life of the page and never disposed. */
        instances: Object.keys(w.x.dashboard._instances).length,
        sent: w.pending[0].body ? w.pending[0].body.tokenize : 'no request',
    };
}

/* ─── process node: the per-node Ollama model box ───────────────────────── */
async function modelCase(provider, redrawMidFlight, current) {
    const w = world(provider);
    const params = { text_column: '正文', mode: 'llm' };
    if (current !== undefined) params.model = current;
    w.sandbox.canvas.nodes['pr-1'] = { id: 'pr-1', type: 'process', operation: 'emotion', title: '情感', params };
    w.x.openSettings('pr-1');
    if (redrawMidFlight) {
        /* Editing any field rewrites the form while the tag list is in flight; the
           loader must look the select up again after the await and fill the element
           that is actually on screen, not the one it started with. */
        w.x.openSettings('pr-1');
    }
    if (w.pending.length) w.pending[0].answer();
    await ticks();
    const content = String(w.sandbox.document.getElementById('settings-content').innerHTML || '');
    const selMarkup = String(w.sandbox.document.getElementById('node-model-pr-1').innerHTML || '');
    return {
        asked: w.pending.length,
        hasSelect: content.indexOf('node-model-pr-1') >= 0,
        follow: selMarkup.indexOf('settings.followGlobalModel') >= 0,
        filled: selMarkup.indexOf('m1:latest') >= 0 && selMarkup.indexOf('m2:7b') >= 0,
        kept: current === undefined ? null : selMarkup.indexOf(String(current)) >= 0,
    };
}

/* ─── stack_pct: the share chart the panel offers and the board forwards ── */
async function stackCase() {
    const w = world();
    w.sandbox.canvas.nodes['st-1'] = {
        id: 'st-1',
        type: 'visualize',
        title: '占比堆叠图',
        params: { chart_type: 'stack_pct', engine: 'echarts', x_field: '阶段', stack_fields: '积极占比, 中性占比, 消极占比' },
    };
    w.x.openSettings('st-1');
    const content = String(w.sandbox.document.getElementById('settings-content').innerHTML || '');
    w.x.dashboard.open();
    await ticks(3);
    for (const p of w.pending) p.answer();
    await ticks();
    const render = w.pending.map((p) => p.body).find((b) => b && b.chart_type) || {};
    return {
        /* The panel is generated from CHART_TYPES, so the option must be there — and the
           stack_fields box is the one input this type needs beyond the x axis. */
        offersType: content.indexOf('chart.stack_pct') >= 0,
        hasStackInput: content.indexOf('stack_fields') >= 0,
        bodyChartType: render.chart_type,
        bodyStackFields: render.stack_fields,
    };
}

/* ─── emit_latex: the two checkboxes the panel shows and the payload forwards ── */
async function latexCase() {
    const w = world();
    // No emit_latex/emit_latex_table in params: figure and table both default ON.
    w.sandbox.canvas.nodes['lt-1'] = {
        id: 'lt-1',
        type: 'visualize',
        title: '柱图',
        params: { chart_type: 'bar', engine: 'echarts', x_field: '城市', y_field: '分数' },
    };
    w.x.openSettings('lt-1');
    const content = String(w.sandbox.document.getElementById('settings-content').innerHTML || '');
    w.x.dashboard.open();
    await ticks(3);
    for (const p of w.pending) p.answer();
    await ticks();
    const render = w.pending.map((p) => p.body).find((b) => b && b.chart_type) || {};
    return {
        panelHasEmitCheckbox: content.indexOf("'emit_latex'") >= 0 && content.indexOf('settings.emitLatex') >= 0,
        panelHasTableCheckbox: content.indexOf("'emit_latex_table'") >= 0 && content.indexOf('settings.emitLatexTable') >= 0,
        bodyEmitLatex: render.emit_latex,
        bodyEmitTable: render.emit_latex_table,
    };
}

/* ─── no_run_data: a cell whose upstream connected but never ran is a note, not a fault ── */
async function noDataCase() {
    const w = world();
    /* getUpstreamNodeId returns 'src-1', so the board does fetch — and the server answers the
       expected-empty state (200 + code). The cell must read as a muted note, and the internal
       reference string must never reach the page. */
    w.sandbox.__renderAnswer = { ok: false, code: 'no_run_data', error: 'No tabular result available for node: src-1' };
    w.sandbox.canvas.nodes['nd-1'] = {
        id: 'nd-1',
        type: 'visualize',
        title: '图',
        params: { chart_type: 'bar', x_field: '城市', engine: 'echarts' },
    };
    w.x.dashboard.open();
    await ticks(3);
    for (const p of w.pending) p.answer();
    await ticks();
    const grid = w.sandbox.document.getElementById('dashboard-grid');
    const cell = grid.querySelector('.dashboard-cell-body');
    const html = cell ? String(cell.innerHTML || '') : '';
    return {
        friendly: html.indexOf('chart.noRunData') >= 0,
        noteClass: html.indexOf('dashboard-cell-note') >= 0,
        rawLeaked: html.indexOf('No tabular result') >= 0,
        redError: html.indexOf('dashboard-cell-error') >= 0,
    };
}

const resume = { calm: await resumeCase(false), raced: await resumeCase(true) };
const stack = await stackCase();
const latex = await latexCase();
const noData = await noDataCase();
const dash = { calm: await dashCase(false, 'false'), raced: await dashCase(true, 'false') };
const model = {
    ollamaCalm: await modelCase('ollama', false, ''),
    ollamaRaced: await modelCase('ollama', true, ''),
    // A stored tag the daemon no longer lists must survive as itself, not collapse to the default.
    ollamaOffList: await modelCase('ollama', false, 'gone:tag'),
    openrouter: await modelCase('openrouter', false, ''),
};
/* The switch as the render request sees it. The board asked for a chart of the
   tokenized column whenever the stored value was the TEXT 'false' — `!!'false'` is
   true — which is the same reading the backend already corrected. */
const spellings = ['false', 'true', '', false, true];
const sent = {};
for (const spelling of spellings) {
    const one = await dashCase(false, spelling);
    sent[JSON.stringify(spelling)] = one.sent;
}

process.stdout.write(JSON.stringify({ resume, stack, latex, noData, dash, model, sent }));
