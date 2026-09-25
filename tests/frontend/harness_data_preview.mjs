/* Drives the REAL Data Preview of workflow.js (`dataPreview`) under node.
 *
 * The panel is the only place a user can read the rows a node actually produced,
 * and nothing had ever executed it: which limit it asks the server for per output
 * format, how its cursor moves and where it stops, what `_render` writes into the
 * page's own table, and what happens when the answer is empty or is a refusal.
 * Those are exactly the four ways this panel has been reported broken — a preview
 * that paged past the end, a preview that said "failed" over an empty table, and a
 * cell that reached the page as markup instead of text (a crawled column value
 * carries HTML, per `data_cleaner`'s own docstring, and a table of that without
 * `escapeHtml` runs it — see AGENTS.md rule 48).
 *
 * Usage: node harness_data_preview.mjs <jsDir> <scenarios.json> <panelMarkupFile>
 * scenarios = [ { "id", "payload", "columns", "rows", "steps": [...], "lang",
 *                 "fails": bool, "error": str, "transport": "reject" } ]
 *
 * The panel markup is not invented here: the driver passes the real
 * `#data-preview-panel` block cut out of `index.html`, so the ids and the
 * `.panel-header` the render path looks for are the ones the page has. (The stub
 * otherwise hands out a fresh auto-created element for any id, which would let a
 * renamed id in either file pass while the panel wrote into nothing.)
 *
 * Two pieces of the browser are supplied rather than trusted:
 *   · `fetch` is a recorder — the preview is a paginated *conversation*, so the
 *     requests are the assertion (limit chosen by format, offset moved by the
 *     cursor), and the reply is built by slicing the scenario's dataset at the
 *     offset the panel asked for, the way `/api/data/preview` does;
 *   · the toast is read back from `#toast`, which is where the real `showToast`
 *     writes: an empty answer and a refusal must be told apart, and the error
 *     channel is the only place that difference is visible.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [jsDir, scenarioPath, panelMarkupPath] = process.argv.slice(2);
const scenarios = JSON.parse(fs.readFileSync(scenarioPath, 'utf8'));
const panelMarkup = fs.readFileSync(panelMarkupPath, 'utf8');

/* The panel's own ids must resolve to the fixture's elements, not to the fresh
   stubs `getElementById` hands out on a miss: a product id that index.html does
   not declare would then be written into an element nobody can see, and the test
   would read that one back and call it a pass. */
function syncIds(sandbox) {
    sandbox.document.world.forEach((el) => {
        if (el.id) sandbox.document.registry.set(el.id, el);
    });
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/* The stub keeps `innerHTML` exactly as the product wrote it and does not resolve
   character references, so a parsed text node still reads `&lt;b&gt;` here where a
   browser would hand back `<b>`. Decoding at the READ boundary is what lets the
   test state "this cell shows the value" instead of asserting an escaping the user
   never sees. `&amp;` goes last, or `&amp;lt;` (an escaped `&lt;`) would decode
   twice and hide a missing escape. */
function decode(text) {
    return String(text)
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&amp;/g, '&');
}

function textOf(el) {
    return el ? decode(el.textContent) : null;
}

/** The table the renderer wrote, read back as cells — not as a markup string. */
function readTable(wrap) {
    const table = wrap.querySelector('table.data-preview-table');
    if (!table) return null;
    const head = table.querySelector('thead');
    const body = table.querySelector('tbody');
    return {
        headers: head
            ? head.querySelectorAll('th').map((th) => ({ text: decode(th.textContent), kids: th.children.length }))
            : [],
        rows: (body ? body.children : []).map((tr) =>
            tr.children.map((td) => ({ text: decode(td.textContent), kids: td.children.length })),
        ),
    };
}

function readWorld(sandbox) {
    const doc = sandbox.document;
    const panel = doc.getElementById('data-preview-panel');
    const wrap = doc.getElementById('data-preview-table-wrap');
    const pre = wrap.querySelector('pre.data-preview-text');
    const header = panel.querySelector('.panel-header');
    return {
        panelClass: Array.from(panel.classList),
        uiInit: panel.dataset._uiInit === undefined ? null : panel.dataset._uiInit,
        resizeHandles: panel.querySelectorAll('.resize-handle').length,
        /* Counted, not assumed: `makeDraggable` hangs a listener on the header every
           time it runs, so a re-render that re-ran the setup is visible here as a
           second handler even though the handle element itself is reused. */
        dragListeners: header && header._events && header._events.mousedown ? header._events.mousedown.length : 0,
        meta: textOf(doc.getElementById('data-preview-meta')),
        pageLabel: textOf(doc.getElementById('data-preview-page-label')),
        pagerDisplay: doc.getElementById('data-preview-pager').style.display,
        spinner: !!wrap.querySelector('.loading-container'),
        table: readTable(wrap),
        preText: pre ? decode(pre.textContent) : null,
        prePresent: !!pre,
        wrapHtml: wrap.innerHTML,
        toast: textOf(doc.getElementById('toast')),
        toastShown: doc.getElementById('toast').classList.contains('show'),
        state: {
            offset: sandbox.dataPreview._offset,
            limit: sandbox.dataPreview._limit,
            total: sandbox.dataPreview._total,
        },
    };
}

/** Words the catalog itself is asked for, in the language the code just ran in. */
function catalog(sandbox) {
    return vm.runInContext(
        `({
            lang: I18n.lang,
            rows: I18n.t('dataPreview.rows'),
            columns: I18n.t('dataPreview.columns'),
            failed: I18n.t('toast.previewFailed'),
        })`,
        sandbox,
    );
}

/* The same words in a named language are asked for per step (`words` beside each
   snapshot), because a language step can sit between two renders and a test that
   compares a rendered line with the catalog has to be able to ask the catalog what
   it WOULD have said — otherwise it can only paste a sentence. */

async function runScenario(sc) {
    const sandbox = { ...baseSandbox() };
    const requests = [];
    /* The recorder stands where `/api/data/preview` stands: it answers a page of
       the scenario's dataset for the offset the panel asked for, so the paging
       arithmetic is answered by the request, never by a hand-fed reply. */
    sandbox.fetch = (url, init) => {
        const options = init || {};
        const body = typeof options.body === 'string' ? JSON.parse(options.body) : {};
        requests.push({ url: String(url), method: options.method || 'GET', body });
        if (sc.transport === 'reject') {
            return Promise.reject(new Error(sc.transportError || 'network is unreachable'));
        }
        if (sc.fails) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ ok: false, error: sc.error || 'no such node' }),
            });
        }
        const rows = sc.rows || [];
        const page = rows.slice(body.offset || 0, (body.offset || 0) + (body.limit || 0));
        return Promise.resolve({
            ok: true,
            json: () =>
                Promise.resolve({
                    ok: true,
                    columns: sc.columns || [],
                    rows: page,
                    total_rows: rows.length,
                    offset: body.offset,
                    limit: body.limit,
                }),
        });
    };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    /* index.html's own order, so anything one file expects of another is the
       shipped arrangement rather than a convenience. */
    for (const file of ['custom-select.js', 'canvas.js', 'workflow.js', 'app.js']) {
        vm.runInContext(fs.readFileSync(path.join(jsDir, file), 'utf8'), sandbox, { filename: file });
    }
    sandbox.document.body.innerHTML = panelMarkup;
    syncIds(sandbox);
    if (sc.lang) vm.runInContext(`I18n.lang = ${JSON.stringify(sc.lang)};`, sandbox);

    const actions = {
        open: async (step) => {
            await sandbox.dataPreview.open(step.payload || sc.payload || {});
        },
        next: async () => {
            sandbox.dataPreview.nextPage();
            await settle();
        },
        prev: async () => {
            sandbox.dataPreview.prevPage();
            await settle();
        },
        close: async () => {
            vm.runInContext('toggleDataPreview();', sandbox);
        },
        lang: async (step) => {
            vm.runInContext(`I18n.lang = ${JSON.stringify(step.value || 'zh')};`, sandbox);
        },
    };
    const trace = [];
    for (const raw of sc.steps || []) {
        const step = typeof raw === 'string' ? { do: raw } : raw;
        const action = actions[step.do];
        if (!action) throw new Error(`${sc.id}: unknown step "${step.do}"`);
        await action(step);
        /* One snapshot per step: the paging cases are about the *sequence*, and a
           final-only reading could not tell "never moved" from "moved and came
           back". The catalog travels with it, because a language step can sit
           between two renders. */
        trace.push({
            step: step.do,
            after: readWorld(sandbox),
            words: catalog(sandbox),
            requests: requests.map((r) => ({ ...r })),
        });
    }

    return {
        world: readWorld(sandbox),
        catalog: catalog(sandbox),
        requests: requests.map((r) => ({ url: r.url, method: r.method, body: r.body })),
        trace,
    };
}

const out = {};
for (const sc of scenarios) {
    out[sc.id] = await runScenario(sc);
}
process.stdout.write(JSON.stringify(out));
