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

const PROJECTS = {
    ok: true,
    projects: [
        {
            project_id: 'p-1',
            name: '数字治理五年',
            snapshots: [
                {
                    snapshot_id: 's-1', label: '2020 基线', created_at: '2026-10-20T10:00:00', shape: 'nodes',
                    node_count: 38, edge_count: 120, params_verified: 1, node_id: 'node-2',
                },
                {
                    snapshot_id: 's-2', label: '2021 增量', created_at: '2026-10-21T10:00:00', shape: 'nodes',
                    node_count: 44, edge_count: 151, params_verified: 0, node_id: 'node-2',
                },
            ],
        },
    ],
};
const DIFF = {
    ok: true,
    diff: {
        a: { label: '2020 基线', snapshot_id: 's-1' },
        b: { label: '2021 增量', snapshot_id: 's-2' },
        same_shape: true,
        same_project: true,
        params_differ: { total: 1, items: [{ name: 'slice_years', a: 2, b: 3 }] },
        nodes: {
            a: 38, b: 44, common: 30,
            added: { total: 6, items: ['数字治理', '数据要素'] },
            removed: { total: 0, items: [] },
            changed: { total: 1, items: [{ name: '公共服务', columns: { 频次: { a: 4, b: 9 } } }] },
        },
        edges: {
            a: 120, b: 151,
            added: { total: 31, items: [{ source: '甲', target: '乙' }] },
            removed: { total: 0, items: [] },
            weight_changed: { total: 0, items: [] },
        },
        clusters: {
            a: 4, b: 5, added: { total: 1, items: ['4'] }, removed: { total: 0, items: [] },
            relabeled: { total: 0, items: [] }, size_changed: { total: 0, items: [] },
        },
        bursts: {
            a: 3, b: 4, added: { total: 1, items: ['算法问责'] }, removed: { total: 0, items: [] },
            strength_changed: { total: 0, items: [] },
        },
    },
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
        let payload = answers.runs;
        if (u.indexOf('/api/biblio/table') >= 0) payload = answers.table;
        else if (u.indexOf('/api/biblio/projects') >= 0) payload = answers.projects || { ok: true, projects: [] };
        else if (u.indexOf('/api/biblio/compare') >= 0) payload = answers.diff || { ok: false, error: 'no diff stub' };
        return Promise.resolve({ text: () => Promise.resolve(JSON.stringify(payload)), status: 200 });
    };
    return {
        sandbox,
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
        asked: w.requests,
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

// 11 · a capture is refused BEFORE it is sent, and the button says why.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE }, projects: { ok: true, projects: [] } });
    const html = w.html();
    out.captureBlocked = {
        disabled: /onclick="biblioWorkspace\.capture\(\)" disabled/.test(html),
        reason: html.indexOf(w.x.I18n.t('biblioWs.captureNeedsProject')) >= 0,
        sent: w.requests.filter((u) => u.indexOf('/api/biblio/snapshot') >= 0).length,
    };
}

// 12 · with a project chosen the button lives, and the list shows what the project kept.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE }, projects: PROJECTS });
    const html = w.html();
    out.captureReady = {
        enabled: /onclick="biblioWorkspace\.capture\(\)" disabled/.test(html) === false,
        listsSnapshots: html.indexOf('2020 基线') >= 0 && html.indexOf('2021 增量') >= 0,
        // The create button must be a closed element: an unbalanced quote in an `onclick`
        // once turned the rest of the bar into text, and only a browser noticed.
        createButton: /onclick="biblioWorkspace\.createProject\(\)">[^<]*<\/button>/.test(html),
        noStrayMarkup: html.indexOf('</button></div><div class="') < 0,
        // The verified/unverified flag is the server's claim about provenance, printed as such.
        paramsWords: [w.x.I18n.t('biblioWs.paramsVerified'), w.x.I18n.t('biblioWs.paramsUnverified')].every(
            (word) => html.indexOf(word) >= 0
        ),
        compareDisabledWithoutBaseline:
            (html.match(/onclick="biblioWorkspace\.compareWith\('s-1'\)" disabled/g) || []).length === 1,
    };
}

// 13 · setting a baseline enables comparing the other capture, and the diff prints the server's.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE }, projects: PROJECTS, diff: DIFF });
    w.x.biblioWorkspace.setBaseline('s-1');
    const afterBaseline = w.html();
    await w.x.biblioWorkspace.compareWith('s-2');
    const html = w.html();
    out.diff = {
        compareEnabled: /onclick="biblioWorkspace\.compareWith\('s-2'\)" disabled/.test(afterBaseline) === false,
        title: html.indexOf(w.x.I18n.t('biblioWs.diffTitle', { a: '2020 基线', b: '2021 增量' })) >= 0,
        paramsLine: html.indexOf('slice_years: 2 → 3') >= 0,
        nodesLine: html.indexOf(w.x.I18n.t('biblioWs.line.nodesAdded', { total: 6 })) >= 0,
        changedCell: html.indexOf('公共服务') >= 0 && html.indexOf('频次: 4 → 9') >= 0,
        // 31 links were added but only one is listed: the cap has to say so.
        capped: html.indexOf(w.x.I18n.t('biblioWs.capped', { shown: 1, total: 31 })) >= 0,
        askedUrl: w.requests.filter((u) => u.indexOf('/api/biblio/compare') >= 0).pop(),
    };
    w.x.biblioWorkspace.clearDiff();
    out.diff.hidden = w.html().indexOf(w.x.I18n.t('biblioWs.diffTitle', { a: '2020 基线', b: '2021 增量' })) < 0;
}

// 14 · an identical pair says "no difference" instead of printing five empty headings.
{
    const empty = await scenario({ runs: RUNS, table: { ...TABLE }, projects: PROJECTS });
    const none = { total: 0, items: [] };
    empty.x.biblioWorkspace._diff = {
        a: { label: 'A' }, b: { label: 'B' }, same_shape: true, same_project: true,
        params_differ: none,
        nodes: { a: 38, b: 38, common: 38, added: none, removed: none, changed: none },
        edges: { a: 120, b: 120, added: none, removed: none, weight_changed: none },
        clusters: { a: 4, b: 4, added: none, removed: none, relabeled: none, size_changed: none },
        bursts: { a: 3, b: 3, added: none, removed: none, strength_changed: none },
    };
    empty.x.biblioWorkspace.render();
    out.diffQuiet = {
        saidSo: empty.html().indexOf(empty.x.I18n.t('biblioWs.diffNone')) >= 0,
        // Counted by the heading element, not by its word: 「Nodes」 is also a table column
        // header on this same panel, so a substring test would fail for the wrong reason.
        noHeadings: (empty.html().match(/class="sched-status"/g) || []).length === 0,
    };
}

// 15 · a table header is interface text, and the stored column name stays reachable.
{
    const dual = {
        ...TABLE,
        shape: 'dual_map',
        columns: ['map', 'source', 'weight', 'x', 'y', 'label', 'cluster_id'],
        rows: [{ map: 'journal', source: '甲刊', target: '', weight: 14, x: 150, y: 50, label: '甲刊', cluster_id: 'c-1' }],
    };
    const w = await scenario({ runs: RUNS, table: dual });
    const html = w.html();
    const heads = [...html.matchAll(/<th title="([^"]*)"[^>]*>([^<]*)<\/th>/g)].map((m) => [m[1], m[2]]);
    out.headers = {
        pairs: heads,
        rawKey: html.indexOf('biblio.col.') >= 0,
        // Each word is exactly what this language's catalogue says for that stored name.
        agreed: heads.map(([name, word]) => word === w.x.I18n.t('biblio.col.' + name) || name === word),
        unknownKept: heads.some(([name, word]) => name === 'cluster_id' && word === 'cluster_id'),
    };
}

// 16 · the fields survive the repaint their own typing causes.
{
    const w = await scenario({ runs: RUNS, table: { ...TABLE } });
    const html = w.html();
    /* The node DOM stub has no activeElement and no caret, so the two halves of the rule are
       driven directly: which field `render` asks about, and what it does with the answer. */
    w.sandbox.document.activeElement = {
        getAttribute: (k) => (k === 'data-biblio-keep' ? 'search' : null),
        selectionStart: 2,
        selectionEnd: 2,
    };
    const inside = w.x.biblioWorkspace._focusedField({ contains: () => true });
    const outside = w.x.biblioWorkspace._focusedField({ contains: () => false });
    w.sandbox.document.activeElement = { getAttribute: () => null, selectionStart: 0, selectionEnd: 0 };
    const unmarked = w.x.biblioWorkspace._focusedField({ contains: () => true });
    const hits = [];
    const fake = { focus: () => hits.push('focus'), setSelectionRange: (a, b) => hits.push([a, b]) };
    w.x.biblioWorkspace._restoreFocus({ querySelector: (sel) => { hits.push(sel); return fake; } }, inside);
    w.x.biblioWorkspace._restoreFocus({ querySelector: () => null }, inside);
    w.x.biblioWorkspace._restoreFocus({ querySelector: () => fake }, '');
    /* The pickers are rebuilt with the body, so the panel owes CustomSelect a look — measured
       behind a patched global, because this harness does not load custom-select.js at all. */
    let refreshes = 0;
    w.sandbox.CustomSelect = { refreshAll: () => { refreshes += 1; }, ownsPopup: () => false };
    w.x.biblioWorkspace.render();
    out.fields = {
        marked: ['search', 'label'].every((k) => html.indexOf(`data-biblio-keep="${k}"`) >= 0),
        askedInside: inside && inside.name === 'search' && inside.start === 2,
        askedOutside: outside === '',
        askedUnmarked: unmarked === '',
        restore: hits,
        refreshes,
    };
}

process.stdout.write(JSON.stringify(out));
