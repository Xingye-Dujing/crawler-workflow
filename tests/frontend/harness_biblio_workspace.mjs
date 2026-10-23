/* The Bibliometrics Workspace dock, driven against the REAL canvas.js + workflow.js + app.js.
 *
 * The panel exists so a finished run's bibliometrics table is readable after a restart, a page
 * reload, or a canvas that has since been rewired. Everything it prints — which runs hold such a
 * node, what shape the stored table is, how many rows there are, which artefacts were registered —
 * is the server's answer, so what a browser test can actually catch is the panel inventing an
 * opinion anyway:
 *
 *   · an unknown shape must read as the catalogue's 「输出形态未知」, never as 节点表 — a wrong
 *     label states a fact the stored columns do not support;
 *   · a refusal is printed with the server's own words, and no table is painted for it:
 *     "that run has no such node" and "that node stored nothing" are different facts;
 *   · the paging line describes the WHOLE table while the rows are one page of it, and the
 *     Previous/Next buttons follow the stored offset rather than hope;
 *   · a filter that trims the page says how many rows it left, without rewriting the total;
 *   · 「在画布中定位」 on a node the canvas no longer holds says so — a button that does nothing
 *     reads as a broken app;
 *   · artefact links carry the name the server resolved, percent-encoded, because the browser
 *     never assembles a path.
 *
 * The panel paints its body with one `innerHTML` assignment, and the DOM stub parses only part of
 * what it is handed (`<button … disabled>` and `<tbody>` rows do not come back as descendants), so
 * the cases read the assigned markup string itself — the exact bytes a browser would receive —
 * and use real element queries only where the stub does build them (the two selects).
 *
 * Wording is compared against `I18n.t(...)` evaluated in the same sandbox — never a pasted
 * sentence.
 *
 * Usage: node harness_biblio_workspace.mjs <jsDir>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [jsDir] = process.argv.slice(2);

const NODE = {
    node_id: 'node-2',
    title: '关键词图谱',
    status: 'done',
    row_count: 38,
    component_name: '',
    files: [{ name: 'a b/graph 1.graphml', kind: 'biblio_graphml', node_id: 'node-2' }],
};
const RUNS = {
    ok: true,
    runs: [
        {
            run_id: 'run-7',
            workflow_name: '文献计量演示',
            started_at: '2026-10-23 12:00',
            status: 'completed',
            nodes: [NODE, { node_id: 'node-8', title: '作者图谱', status: 'done', row_count: 5, component_name: '', files: [] }],
        },
        {
            run_id: 'run-3',
            workflow_name: '',
            started_at: '2026-10-22 09:00',
            status: 'failed',
            nodes: [{ node_id: 'node-2', title: '关键词图谱', status: 'partial', row_count: 0, component_name: '', files: [] }],
        },
    ],
};
const TABLE = {
    ok: true,
    run_id: 'run-7',
    node_id: 'node-2',
    title: '关键词图谱',
    status: 'done',
    shape: 'nodes',
    columns: ['节点', '频次', '聚类标签'],
    rows: [
        { 节点: '数字治理', 频次: 12, 聚类标签: '甲组' },
        { 节点: '数据要素', 频次: 7, 聚类标签: '乙组' },
        { 节点: '公共服务', 频次: 3, 聚类标签: '甲组' },
    ],
    total: 500,
    offset: 0,
    limit: 200,
    files: NODE.files,
};

function world(answers) {
    const sandbox = {
        ...baseSandbox(),
        console: { log() {}, warn() {}, error() {} },
        localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    const sources = ['canvas.js', 'workflow.js', 'app.js']
        .map((name) => fs.readFileSync(path.join(jsDir, name), 'utf8'))
        .join('\n;\n');
    vm.runInContext(
        `${sources}\n;globalThis.__x = { canvas, I18n, biblioWorkspace,` +
            ' body: () => document.getElementById("biblio-mgr-body"),' +
            ' setPanelOpen: (v) => { const p = document.getElementById("biblio-panel");' +
            '   if (!p) return false; p.classList[v ? "add" : "remove"]("open"); return true; } };',
        sandbox
    );
    const requests = [];
    /* `fetchJSON` reads `.text()` and parses it itself, so the stub answers the way the real
       route does — a `json()`-only stub would be a fixture artifact, not a response. */
    sandbox.fetch = (url) => {
        const u = String(url);
        requests.push(u);
        const payload = u.indexOf('/api/biblio/table') >= 0 ? answers.table : answers.runs;
        return Promise.resolve({ text: () => Promise.resolve(JSON.stringify(payload)), status: 200 });
    };
    return {
        x: sandbox.__x,
        requests,
        html: () => String(sandbox.__x.body().innerHTML),
        toast: () => {
            const el = sandbox.document.getElementById('toast');
            return el ? String(el.textContent) : '';
        },
    };
}

async function scenario(answers) {
    const w = world(answers);
    await w.x.biblioWorkspace.refresh();
    return w;
}

/* The DOM stub's tag parser skips an element that carries a bare boolean attribute
   (`selected`, `disabled`), so the option list is read off the assigned markup — the exact
   bytes a browser is handed — rather than through a query that cannot see them. */
function optionLabels(match) {
    if (!match) return [];
    return [...String(match[0]).matchAll(/<option value="([^"]*)"[^>]*>([^<]*)</g)].map((m) => `${m[1]}|${m[2]}`);
}

const out = {};

// 1 · nothing recorded yet: the panel says so, in the interface's own words.
{
    const w = await scenario({ runs: { ok: true, runs: [] }, table: TABLE });
    out.empty = {
        saidSo: w.html().indexOf(w.x.I18n.t('biblioWs.noRuns')) >= 0,
        asked: w.requests.length,
        hasTable: w.html().indexOf('<table') >= 0,
    };
}

// 2 · the two pickers list exactly what the server listed, with the first of them selected.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE } });
    const html = w.html();
    const runSelect = /<select[^>]*pickRun[\s\S]*?<\/select>/.exec(html);
    const nodeSelect = /<select[^>]*pickNode[\s\S]*?<\/select>/.exec(html);
    out.pickers = {
        runOptions: optionLabels(runSelect),
        nodeOptions: optionLabels(nodeSelect),
        runSelected: html.indexOf('value="run-7" selected') >= 0,
        nodeSelected: html.indexOf('value="node-2" selected') >= 0,
        // The row count and the node's own status word come from the record, not the canvas.
        showsRowCounts: html.indexOf(String(NODE.row_count)) >= 0,
        tableAsked: w.requests.filter((u) => u.indexOf('/api/biblio/table') >= 0).length,
    };
}

// 3 · the shape chip repeats the server's shape; an unreadable shape is admitted as unknown.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE } });
    const w2 = await scenario({ runs: RUNS, table: { ...TABLE, shape: '' } });
    const w3 = await scenario({ runs: RUNS, table: { ...TABLE, shape: 'dual_map' } });
    out.shape = {
        nodes: w.html().indexOf(w.x.I18n.t('biblioWs.shape.nodes')) >= 0,
        dual: w3.html().indexOf(w3.x.I18n.t('biblioWs.shape.dual_map')) >= 0,
        unknown: w2.html().indexOf(w2.x.I18n.t('biblioWs.shapeUnknown')) >= 0,
        // A shape the server did not name must not be answered with a guessed word.
        notGuessed: w2.html().indexOf(w2.x.I18n.t('biblioWs.shape.nodes')) < 0,
    };
}

// 4 · a refusal is printed with the server's words and paints no table.
{
    const refusal = 'run-7 has no node node-99: pick another run';
    const w = await scenario({ runs: RUNS, table: { ok: false, error: refusal } });
    out.refusal = {
        printed: w.html().indexOf(refusal) >= 0,
        hasTable: w.html().indexOf('<table') >= 0,
        askedOnce: w.requests.filter((u) => u.indexOf('/api/biblio/table') >= 0).length === 1,
    };
}

// 5 · the paging line describes the whole table; the buttons follow the stored offset.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE } });
    const first = w.html();
    await w.x.biblioWorkspace.page(1);
    const second = w.html();
    const asked = w.requests.filter((u) => u.indexOf('/api/biblio/table') >= 0).pop();
    out.paging = {
        line: first.indexOf(w.x.I18n.t('biblioWs.page', { from: 1, to: 200, total: 500 })) >= 0,
        prevDisabledAtFirst: /onclick="biblioWorkspace\.page\(-1\)" disabled/.test(first),
        prevEnabledAfter: /onclick="biblioWorkspace\.page\(-1\)" disabled/.test(second) === false,
        nextUrl: asked,
    };
}

// 5b · a table that fits one page has no second page to fall off into.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE, total: 164 } });
    const asked = w.requests.length;
    const html = w.html();
    await w.x.biblioWorkspace.page(1);
    out.singlePage = {
        nextDisabled: /onclick="biblioWorkspace\.page\(1\)" disabled/.test(html),
        noExtraRequest: w.requests.length === asked,
        offsetUntouched: w.x.biblioWorkspace._offset === 0,
    };
}

// 6 · a filter trims the page and says how many it left, without rewriting the total.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE } });
    w.x.biblioWorkspace.filter('数据');
    const html = w.html();
    out.filter = {
        kept: html.indexOf('数据要素') >= 0,
        dropped: html.indexOf('数字治理') < 0 && html.indexOf('公共服务') < 0,
        saidHowMany: html.indexOf(w.x.I18n.t('biblioWs.filtered', { shown: 1 })) >= 0,
        totalStillServers: html.indexOf(w.x.I18n.t('biblioWs.page', { from: 1, to: 200, total: 500 })) >= 0,
    };
}

// 7 · locating a node the canvas no longer holds says so; a node that is there gets centred.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE } });
    w.x.biblioWorkspace.locate();
    const missing = w.toast();
    w.x.canvas.nodes['node-2'] = { id: 'node-2', type: 'biblio', title: '关键词图谱', params: {} };
    let centred = '';
    w.x.canvas.centerOnNode = (id) => {
        centred = String(id);
    };
    w.x.biblioWorkspace.locate();
    out.locate = {
        saidSo: missing === w.x.I18n.t('biblioWs.locateMissing', { nid: 'node-2' }),
        centred,
    };
}

// 8 · artefact links carry the server-resolved name, percent-encoded, never a built path.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE } });
    /* The files row reads the NODE's registered artefacts (they came with the run list), so
       the "no artefacts" case has to empty them there — an empty table.files is a different
       fact and the panel must not pretend otherwise. */
    const bare = JSON.parse(JSON.stringify(RUNS));
    bare.runs[0].nodes[0].files = [];
    const w2 = await scenario({ runs: bare, table: { ...TABLE, files: [] } });
    out.files = {
        link: w.html().indexOf('/api/exports/download?name=a%20b%2Fgraph%201.graphml') >= 0,
        noFilesSaidSo: w2.html().indexOf(w2.x.I18n.t('biblioWs.noFiles')) >= 0,
    };
}

// 9 · an empty stored table names the node instead of painting nothing.
{
    const note = 'node-2：该节点没有已存行';
    const w = await scenario({
        runs: RUNS,
        table: { ...TABLE, rows: [], columns: [], total: 0, shape: '', note },
    });
    const html = w.html();
    out.emptyTable = {
        notePrinted: html.indexOf(note) >= 0,
        noRowsPainted: html.indexOf('<tbody') < 0,
        unknownAdmitted: html.indexOf(w.x.I18n.t('biblioWs.shapeUnknown')) >= 0,
    };
}

// 10 · switching language repaints the panel: every word in it is built here.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE } });
    /* `onLanguageChange` only repaints an OPEN dock (a closed panel repaints on open), so the
       scenario opens it the way the toggle does — by adding the class, not by re-fetching. */
    w.x.body().textContent;
    if (!w.x.setPanelOpen(true)) throw new Error('the dock element is missing from the stub world');
    const before = w.html();
    w.x.I18n.lang = w.x.I18n.lang === 'zh' ? 'en' : 'zh';
    const other = w.x.I18n.t('biblioWs.shape.nodes');
    w.x.biblioWorkspace.onLanguageChange();
    const after = w.html();
    out.language = {
        changed: before !== after,
        otherWordInAfter: after.indexOf(other) >= 0,
        otherWordNotInBefore: before.indexOf(other) < 0,
    };
}

process.stdout.write(JSON.stringify(out));
