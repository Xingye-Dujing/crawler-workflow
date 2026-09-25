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

async function ticks(n) {
    for (let i = 0; i < (n || 6); i += 1) await new Promise((r) => setImmediate(r));
}

/* One world per scenario: the panel caches the markup it drew, and a shared one
   would let the second scenario read the first one's page. */
function world() {
    const pending = [];
    const inits = [];
    const sandbox = {
        ...baseSandbox(),
        I18n,
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
                    const payload =
                        String(url).indexOf('/api/runs/resumable') >= 0
                            ? { ok: true, runs: RESUME_RUNS }
                            : { ok: true, engine: 'echarts', option: {} };
                    resolve({ json: () => Promise.resolve(payload) });
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

const resume = { calm: await resumeCase(false), raced: await resumeCase(true) };
const dash = { calm: await dashCase(false, 'false'), raced: await dashCase(true, 'false') };
/* The switch as the render request sees it. The board asked for a chart of the
   tokenized column whenever the stored value was the TEXT 'false' — `!!'false'` is
   true — which is the same reading the backend already corrected. */
const spellings = ['false', 'true', '', false, true];
const sent = {};
for (const spelling of spellings) {
    const one = await dashCase(false, spelling);
    sent[JSON.stringify(spelling)] = one.sent;
}

process.stdout.write(JSON.stringify({ resume, dash, sent }));
