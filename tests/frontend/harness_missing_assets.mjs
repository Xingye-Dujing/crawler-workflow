/* What the UI does when a bundle it needs is not on the page.
 *
 * The figure area depends on files the app serves itself (/vendor + /geo). Two things can go
 * wrong there, and each used to look the same on screen: nothing. Either the chart library is
 * missing (a damaged install, a file that did not ship) or a basemap could not be read. A blank
 * panel reads as "this node produced no chart", which is a different fact and one the user cannot
 * act on — so every render path now paints a sentence that names the file.
 *
 * These cases run the REAL workflow.js twice: once with an ECharts stub in the sandbox, once with
 * no ECharts at all (the way a missing <script> leaves the page). Pinned:
 *
 *   · preview, full-screen window, dashboard cell and history panel each say which file is absent,
 *     and none of them throws;
 *   · the vector export refuses by name and sends NO request (an empty .svg on disk would be a
 *     file that lies about being a figure);
 *   · a basemap that will not register is refused ON THE FIGURE — the drawn option carries the
 *     sentence, so an exported PNG carries the reason too;
 *   · a failed basemap read names the file and the HTTP status, and is retried on the next
 *     figure rather than cached as a permanent failure;
 *   · a preview whose library is missing still offers its LaTeX: the source is real, only the
 *     browser-side painter is gone.
 *
 * Usage: node harness_missing_assets.mjs <jsDir> <panelMarkupFile>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [jsDir, panelMarkupPath] = process.argv.slice(2);
const panelMarkup = fs.readFileSync(panelMarkupPath, 'utf8');

const RENDER_BAR = { ok: true, engine: 'echarts', option: { series: [{ type: 'bar' }] }, latex: 'FIGURE', latex_table: 'TABLE' };
const RENDER_MAP = {
    ok: true,
    engine: 'echarts',
    option: { series: [{ type: 'map', map: 'china', data: [{ name: '北京市', value: 1 }] }] },
};
const GEO = { type: 'FeatureCollection', features: [] };

function settle() {
    return new Promise((r) => setImmediate(r));
}

async function ticks(n) {
    for (let i = 0; i < (n || 8); i += 1) await settle();
}

function world(render, options) {
    const opts = options || {};
    const library = opts.library !== false;
    const requests = [];
    const created = [];
    const registered = [];
    const mapAnswers = opts.mapAnswers || [{ ok: true, status: 200, body: GEO }];
    let mapCall = 0;

    /* The shared DOM stub ships its own ECharts (several harnesses need one), so "no library"
       means deleting it: leaving it in place would run the normal draw path under a stub this
       harness does not record, and every case below would measure the stub, not the product. */
    const sandbox = { ...baseSandbox() };
    if (library) {
        sandbox.echarts = {
            init(el) {
                const inst = {
                    host: el,
                    applied: [],
                    cleared: 0,
                    setOption(opt) { inst.applied.push(opt); },
                    clear() { inst.cleared += 1; },
                    resize() {},
                    dispose() {},
                };
                created.push(inst);
                return inst;
            },
            registerMap(name, payload) { registered.push({ name, payload }); },
        };
    } else {
        delete sandbox.echarts;
    }
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);

    sandbox.document.body.innerHTML = panelMarkup;
    sandbox.document.world.forEach((el) => {
        if (el.id) sandbox.document.registry.set(el.id, el);
    });

    const sources = ['canvas.js', 'workflow.js', 'app.js']
        .map((name) => fs.readFileSync(path.join(jsDir, name), 'utf8'))
        .join('\n;\n');
    vm.runInContext(
        `${sources}\n;globalThis.__x = { canvas, dataNodes, dashboard, I18n,` +
            ' applyEchartsOption, ensureMapRegistered, hasChartLibrary, chartLibraryMissingMessage,' +
            ' savePreviewVector, getPreviewOption: () => _chartPreviewOption,' +
            ' openChartFullscreen, closeChartFullscreen,' +
            ' getFullscreenOption: () => _chartFullscreenOption };',
        sandbox
    );

    sandbox.fetch = (url, init) => {
        const u = String(url);
        requests.push({ url: u, body: init && init.body ? String(init.body) : '' });
        if (u.indexOf('/api/visualize/render') >= 0) {
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(render) });
        }
        if (u.indexOf('/geo/') >= 0) {
            const answer = mapAnswers[Math.min(mapCall, mapAnswers.length - 1)];
            mapCall += 1;
            return Promise.resolve({
                ok: answer.ok,
                status: answer.status,
                json: () => Promise.resolve(answer.body),
            });
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    };

    const toast = () => {
        const el = sandbox.document.getElementById('toast');
        return { text: el.textContent, shown: el.classList.contains('show') };
    };

    return { sandbox, x: sandbox.__x, requests, created, registered, toast };
}

function addChart(w, id, title) {
    const c = w.x.canvas;
    c.nodes[id] = {
        id,
        type: 'visualize',
        title: title || '图1 关键词柱状图',
        params: { chart_type: 'bar', x_field: '城市', engine: 'echarts' },
    };
    // A visualize node previews what its upstream produced, so the connection is part of the
    // fixture, not decoration: without it the preview path asks nothing and no instance appears.
    c.nodes['src-1'] = { id: 'src-1', type: 'analysis', title: '上游', params: {} };
    c.connections = (c.connections || []).filter((conn) => conn.to !== id);
    c.connections.push({ from: 'src-1', to: id });
}

function noteText(w, hostId) {
    const host = w.sandbox.document.getElementById(hostId);
    const note = (host.children || []).find((child) => (child.className || '').indexOf('chart-missing') >= 0);
    return note ? note.textContent : '';
}

/* Elements the product builds at runtime are not in the extracted markup, so they are found by
   walking every element the stub has ever handed out — the same index the stub's own
   ``querySelectorAll`` uses. */
function findByClass(w, cls) {
    return (w.sandbox.document.world || []).filter((el) => String(el.className || '').indexOf(cls) >= 0);
}

const out = {};

/* ── the chart library is not on the page ─────────────────────────────── */

async function previewWithoutLibrary() {
    const w = world(RENDER_BAR, { library: false });
    addChart(w, 'v-1');
    await w.x.dataNodes.previewVisualize('v-1');
    await ticks();
    const bars = findByClass(w, 'latex-action-bar');
    return {
        note: noteText(w, 'chart-preview-echarts'),
        expected: w.x.I18n.t('chart.noLibrary', { file: '/vendor/echarts.min.js' }),
        hasLibrary: w.x.hasChartLibrary(),
        optionKept: !!w.x.getPreviewOption(),
        latexBarOffered: bars.length > 0,
        instances: w.created.length,
    };
}

async function previewWithLibrary() {
    const w = world(RENDER_BAR);
    addChart(w, 'v-2');
    await w.x.dataNodes.previewVisualize('v-2');
    await ticks();
    return { note: noteText(w, 'chart-preview-echarts'), instances: w.created.length, drawn: w.created[0].applied.length };
}

async function fullscreenWithoutLibrary() {
    const w = world(RENDER_BAR, { library: false });
    addChart(w, 'v-3');
    await w.x.dataNodes.previewVisualize('v-3');
    await ticks();
    await w.x.openChartFullscreen('v-3');
    await ticks();
    return {
        note: noteText(w, 'chart-fullscreen-echarts'),
        optionKept: !!w.x.getFullscreenOption(),
        instances: w.created.length,
    };
}

async function dashboardWithoutLibrary() {
    const w = world(RENDER_BAR, { library: false });
    addChart(w, 'v-4');
    w.x.dashboard.open();
    await ticks(12);
    const notes = findByClass(w, 'dashboard-cell-note');
    const text = notes.map((el) => el.textContent).join(' ');
    return {
        names_library: text.indexOf('echarts.min.js') >= 0,
        cells: findByClass(w, 'dashboard-cell').length,
        text: text.slice(0, 160),
        instances: w.created.length,
    };
}

async function vectorWithoutLibrary() {
    const w = world(RENDER_BAR, { library: false });
    addChart(w, 'v-5');
    await w.x.dataNodes.previewVisualize('v-5');
    await ticks();
    const before = w.requests.length;
    const filename = await w.x.savePreviewVector();
    /* Read the toast WITHOUT draining macrotasks: the DOM stub remaps setTimeout to 0 ms, so an
       ``await ticks()`` here lets showToast's own hide fire first and ``text`` would read empty. */
    const toast = w.toast().text;
    const maps = w.requests.length - before;
    return {
        filename,
        toast,
        expected: w.x.I18n.t('chart.noLibrary', { file: '/vendor/echarts.min.js' }),
        export_requests: maps,
    };
}

/* ── a basemap that cannot be read ────────────────────────────────────── */

async function mapRefusalNamesTheFile() {
    const w = world(RENDER_MAP, { mapAnswers: [{ ok: false, status: 404, body: 'not found' }] });
    addChart(w, 'v-6');
    await w.x.dataNodes.previewVisualize('v-6');
    await ticks();
    const refusal = await w.x.ensureMapRegistered('china');
    await ticks();
    const again = await w.x.ensureMapRegistered('china');
    const maps = w.requests.filter((entry) => entry.url.indexOf('/geo/') >= 0);
    const drawn = w.created[0] ? w.created[0].applied[0] : null;
    return {
        refusal,
        has_file: refusal.indexOf('/geo/china.json') >= 0,
        has_status: refusal.indexOf('404') >= 0,
        retried: maps.length > 1,
        map_requests: maps.length,
        redrawn: again === refusal,
        drawn_is_refusal: !!drawn && !!drawn.title && !drawn.series,
    };
}

async function mapRegistersAndDraws() {
    const w = world(RENDER_MAP);
    addChart(w, 'v-7');
    await w.x.dataNodes.previewVisualize('v-7');
    await ticks();
    const refusal = await w.x.ensureMapRegistered('china');
    await ticks();
    const drawn = w.created[0] ? w.created[0].applied[0] : null;
    return {
        refusal,
        registered: w.registered.map((entry) => entry.name),
        drawn_has_series: !!drawn && !!(drawn.series || []).length,
    };
}

async function unknownBasemapIsRefused() {
    const w = world(RENDER_BAR);
    const refusal = await w.x.ensureMapRegistered('mars');
    await ticks();
    return { refusal, asked: w.requests.filter((entry) => entry.url.indexOf('/geo/mars') >= 0).length };
}

out.preview_without_library = await previewWithoutLibrary();
out.preview_with_library = await previewWithLibrary();
out.fullscreen_without_library = await fullscreenWithoutLibrary();
out.dashboard_without_library = await dashboardWithoutLibrary();
out.vector_without_library = await vectorWithoutLibrary();
out.map_refusal_names_the_file = await mapRefusalNamesTheFile();
out.map_registers_and_draws = await mapRegistersAndDraws();
out.unknown_basemap_is_refused = await unknownBasemapIsRefused();

process.stdout.write(JSON.stringify(out));
