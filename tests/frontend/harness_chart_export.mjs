/* Saving a drawn chart as a PNG, driven under node against the REAL page markup.
 *
 * A chart exists on screen in three places — the studio, the preview panel and a
 * dashboard cell — and only the studio could put its picture on disk. These cases run
 * the two that were added (`savePreviewImage` / `saveDashboardImage` in workflow.js):
 *
 *   · the picture comes from the ECharts instance at pixelRatio 2 on a white ground
 *     (a transparent PNG lands on paper white and reads as a broken export), or from
 *     the data URL a Matplotlib preview already handed over;
 *   · the file is named after the chart the user is looking at — the node's title.
 *     A preview of 图23 saved as `chart-preview` is an export nobody can match back
 *     to its figure, so a SECOND preview must retarget the name too;
 *   · nothing drawn is refused with `chart.saveNothing` and sends NO request: a silent
 *     button reads as "saving is broken" when the truth is that there is no picture;
 *   · a server refusal is reported as a failure, never as a filename;
 *   · a rebuilt dashboard forgets its pictures, so saving after a refresh says so
 *     instead of quietly exporting the chart the board threw away (the same off-page
 *     rule `harness_async_panels.mjs` pins for instances).
 *
 * app.js is loaded because the preview panel's first render installs a drag/resize
 * shell (`makeDraggable` / `makeResizable`) — without it the panel throws inside the
 * caller's try/catch and the scenario would measure a stub artifact, not the product.
 * The toast is read back from `#toast`, where the real `showToast` writes, and wording
 * is compared against `I18n.t(...)` evaluated in the same sandbox — never a pasted
 * sentence.
 *
 * Usage: node harness_chart_export.mjs <jsDir> <panelMarkupFile>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [jsDir, panelMarkupPath] = process.argv.slice(2);
const panelMarkup = fs.readFileSync(panelMarkupPath, 'utf8');

const RENDER_ECHARTS = { ok: true, engine: 'echarts', option: { series: [{ type: 'bar' }] } };
const RENDER_IMAGE = { ok: true, engine: 'matplotlib', image: 'data:image/png;base64,MATPLOTLIBPICTURE' };
const SAVE_OK = { ok: true, filename: 'tu23-a1b2c3.png' };
const SAVE_REFUSED = { ok: false, error: 'image too large' };

function settle() {
    return new Promise((r) => setImmediate(r));
}
async function ticks(n) {
    for (let i = 0; i < (n || 8); i += 1) await settle();
}

function world(render) {
    const requests = [];
    const created = [];
    const answers = { render: render || RENDER_ECHARTS, save: SAVE_OK };

    const sandbox = {
        ...baseSandbox(),
        echarts: {
            init(el) {
                const inst = {
                    setOption() {},
                    resize() {},
                    disposed: 0,
                    dispose() { inst.disposed += 1; },
                    getDataURL(spec) {
                        inst.lastSpec = spec;
                        return 'data:image/png;base64,FROMINSTANCE';
                    },
                };
                created.push(inst);
                return inst;
            },
        },
    };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);

    /* The ids the product writes into must be the ids the page declares: a renamed
       #chart-preview-image would otherwise resolve to a fresh stub element here and
       the save would appear to work while the page shows nothing. */
    sandbox.document.body.innerHTML = panelMarkup;
    sandbox.document.world.forEach((el) => {
        if (el.id) sandbox.document.registry.set(el.id, el);
    });

    const sources = ['canvas.js', 'workflow.js', 'app.js']
        .map((name) => fs.readFileSync(path.join(jsDir, name), 'utf8'))
        .join('\n;\n');
    vm.runInContext(
        `${sources}\n;globalThis.__x = { canvas, dataNodes, dashboard, I18n,` +
            ' savePreviewImage, saveDashboardImage, saveChartPicture,' +
            ' openChartFullscreen, closeChartFullscreen, saveFullscreenImage,' +
            ' getFullscreenInstance: () => _chartFullscreenInstance,' +
            ' getPreviewNodeId: () => _chartPreviewNodeId };',
        sandbox
    );

    sandbox.fetch = (url, init) => {
        const u = String(url);
        const body = init && init.body ? JSON.parse(init.body) : null;
        requests.push({ url: u, body });
        const payload = u.indexOf('/api/studio/save-image') >= 0 ? answers.save : answers.render;
        return Promise.resolve({ json: () => Promise.resolve(payload), status: 200 });
    };

    const toast = () => {
        const el = sandbox.document.getElementById('toast');
        return { text: el.textContent, shown: el.classList.contains('show') };
    };

    return { sandbox, x: sandbox.__x, requests, created, toast, answers };
}

/* canvas.js keeps its object in a top-level `const`, which a sandbox property cannot
   see, so the fixture builds nodes through the object the loaded script exported. */
function addChart(w, id, title, params) {
    const c = w.x.canvas;
    c.nodes[id] = {
        id,
        type: 'visualize',
        title,
        params: params || { chart_type: 'bar', x_field: '城市', engine: 'echarts' },
    };
    c.nodes['src-1'] = { id: 'src-1', type: 'analysis', title: '上游', params: {} };
    c.connections = (c.connections || []).filter((conn) => conn.to !== id);
    c.connections.push({ from: 'src-1', to: id });
}

function saves(w) {
    return w.requests.filter((r) => r.url.indexOf('/api/studio/save-image') >= 0);
}

/* ── preview panel ─────────────────────────────────────────────────────────── */
async function previewCase(engine) {
    const w = world(engine === 'matplotlib' ? RENDER_IMAGE : RENDER_ECHARTS);
    addChart(w, 'v-1', '图23 发酵期 每日热度与情感强度');
    await w.x.dataNodes.previewVisualize('v-1');
    await ticks();
    const drawn = w.created.length;
    const filename = await w.x.savePreviewImage();
    await ticks();
    const post = saves(w).pop();
    return {
        drawn,
        asked: saves(w).length,
        url: post ? post.url : null,
        name: post && post.body ? post.body.name : null,
        image: post && post.body ? String(post.body.image) : null,
        spec: w.created[0] ? w.created[0].lastSpec : null,
        filename,
        toast: w.toast(),
    };
}

async function previewNothingCase() {
    const w = world();
    const filename = await w.x.savePreviewImage();
    await ticks();
    return { asked: saves(w).length, filename, toast: w.toast() };
}

async function previewRefusedCase() {
    const w = world();
    addChart(w, 'v-1', '图24 爆发期');
    await w.x.dataNodes.previewVisualize('v-1');
    await ticks();
    w.answers.save = SAVE_REFUSED;
    const filename = await w.x.savePreviewImage();
    await ticks();
    return { filename, toast: w.toast(), asked: saves(w).length };
}

/* The name follows the LAST preview, not the first one: two charts, one button. */
async function previewRetargetCase() {
    const w = world();
    addChart(w, 'v-1', '图23 发酵期');
    await w.x.dataNodes.previewVisualize('v-1');
    await ticks();
    addChart(w, 'v-2', '图24 爆发期');
    await w.x.dataNodes.previewVisualize('v-2');
    await ticks();
    await w.x.savePreviewImage();
    await ticks();
    const post = saves(w).pop();
    return { name: post && post.body ? post.body.name : null, asked: saves(w).length };
}

/* ── dashboard cells ───────────────────────────────────────────────────────── */
function renders(w) {
    return w.requests.filter((r) => r.url.indexOf('/api/visualize/render') >= 0);
}

async function dashboardCase(engine, rebuild) {
    const w = world(engine === 'matplotlib' ? RENDER_IMAGE : RENDER_ECHARTS);
    addChart(w, 'v-1', '图15 主题流向', {
        chart_type: 'dual_line',
        x_field: 'period',
        y_field: 'total',
        y2_field: 'intensity',
        agg: 'sum',
        agg2: 'mean',
        annotations: '2022-01-24=本阶段峰3439条',
        engine: 'echarts',
    });
    w.x.dashboard.open();
    await ticks(6);
    const asked = (renders(w)[0] || {}).body || {};
    if (rebuild) {
        /* Rebuilding the board twice: what has to stay true is that the cell's picture
           is the LIVE one and that the bookkeeping does not accumulate an instance per
           refresh (a leaked instance is resized on every window resize forever, and a
           stale `_images` entry would be exported as the current chart). */
        w.x.dashboard.open();
        await ticks(6);
        const mid = Object.keys(w.x.dashboard._instances).length;
        w.x.dashboard.open();
        await ticks(6);
        const before = saves(w).length;
        const filename = await w.x.saveDashboardImage('v-1');
        await ticks();
        const post = saves(w).pop();
        return {
            after_first_rebuild: mid,
            after_second_rebuild: Object.keys(w.x.dashboard._instances).length,
            images: Object.keys(w.x.dashboard._images).length,
            asked: saves(w).length - before,
            name: post && post.body ? post.body.name : null,
            image: post && post.body ? String(post.body.image) : null,
            filename,
        };
    }
    const filename = await w.x.saveDashboardImage('v-1');
    await ticks();
    const post = saves(w).pop();
    return {
        instances: Object.keys(w.x.dashboard._instances).length,
        images: Object.keys(w.x.dashboard._images).length,
        render: asked,
        name: post && post.body ? post.body.name : null,
        image: post && post.body ? String(post.body.image) : null,
        filename,
        toast: w.toast(),
    };
}

const out = {};
out.preview_echarts = await previewCase('echarts');
out.preview_matplotlib = await previewCase('matplotlib');
out.preview_nothing_drawn = await previewNothingCase();
out.preview_server_refused = await previewRefusedCase();
out.preview_retargeted_name = await previewRetargetCase();
out.dashboard_echarts = await dashboardCase('echarts', false);
out.dashboard_matplotlib = await dashboardCase('matplotlib', false);
out.dashboard_after_rebuild = await dashboardCase('echarts', true);

/* ── full-screen window ─────────────────────────────────────────────────────── */
function el(w, id) {
    return w.sandbox.document.getElementById(id);
}

/* The board already holds the option, so opening full-screen must reuse it, not re-ask the
   server (a re-ask of a 主题概括 cell would re-hit the endpoint on every click). */
async function fullscreenFromBoardOptionCase() {
    const w = world();
    addChart(w, 'v-1', '图25 全库主题距离图', {
        chart_type: 'topic_map', engine: 'echarts', x_field: 'pc1', y_field: 'pc2',
        value_field: 'prevalence_pct', label_field: '主题概括',
    });
    w.x.dashboard.open();
    await ticks(6);
    const before = renders(w).length;
    await w.x.openChartFullscreen('v-1');
    await ticks();
    return {
        rendersExtra: renders(w).length - before,
        boardInstances: Object.keys(w.x.dashboard._options).length,
        fsAlive: !!w.x.getFullscreenInstance(),
        panelOpen: el(w, 'chart-fullscreen-panel').classList.contains('open'),
        title: el(w, 'chart-fullscreen-title').textContent,
    };
}

async function fullscreenFromBoardImageCase() {
    const w = world(RENDER_IMAGE);
    addChart(w, 'v-1', '图26', { chart_type: 'bar', engine: 'echarts', x_field: '城市' });
    w.x.dashboard.open();
    await ticks(6);
    const before = renders(w).length;
    await w.x.openChartFullscreen('v-1');
    await ticks();
    return {
        rendersExtra: renders(w).length - before,
        fsInstance: !!w.x.getFullscreenInstance(),
        // The stub stores an inline style="…" as a string, so a real `.style.display` write is
        // a no-op here (a browser applies it). The src landing is the proof the image branch ran.
        imgSrc: String(el(w, 'chart-fullscreen-image').src || ''),
    };
}

/* A node the board never drew: the window re-renders from the server, and the request must
   carry label_field or the 概括 column the chart was set to read is silently dropped. */
async function fullscreenRefetchCase() {
    const w = world();
    addChart(w, 'v-1', '图27', {
        chart_type: 'topic_map', engine: 'echarts', x_field: 'pc1', y_field: 'pc2',
        value_field: 'prevalence_pct', label_field: '主题概括',
    });
    await w.x.openChartFullscreen('v-1');
    await ticks();
    const last = renders(w).slice(-1)[0] || {};
    return { renders: renders(w).length, payload: last.body || {}, fsAlive: !!w.x.getFullscreenInstance() };
}

async function fullscreenFromPreviewCase() {
    const w = world();
    addChart(w, 'v-1', '图28', { chart_type: 'bar', engine: 'echarts', x_field: '城市' });
    await w.x.dataNodes.previewVisualize('v-1');
    await ticks();
    const before = renders(w).length;
    await w.x.openChartFullscreen('v-1');
    await ticks();
    return { rendersExtra: renders(w).length - before, fsAlive: !!w.x.getFullscreenInstance(), nodeId: w.x.getPreviewNodeId() };
}

async function fullscreenCloseCase() {
    const w = world();
    addChart(w, 'v-1', '图29', { chart_type: 'bar', engine: 'echarts', x_field: '城市' });
    w.x.dashboard.open();
    await ticks(6);
    await w.x.openChartFullscreen('v-1');
    await ticks();
    const inst = w.x.getFullscreenInstance();
    w.x.closeChartFullscreen();
    await ticks();
    return { disposed: inst ? inst.disposed : -1, cleared: w.x.getFullscreenInstance() === null };
}

async function fullscreenSaveCase() {
    const w = world();
    addChart(w, 'v-1', '图30 二次爆发期距离图', {
        chart_type: 'topic_map', engine: 'echarts', x_field: 'pc1', y_field: 'pc2',
        value_field: 'prevalence_pct', label_field: '主题概括',
    });
    w.x.dashboard.open();
    await ticks(6);
    await w.x.openChartFullscreen('v-1');
    await ticks();
    const filename = await w.x.saveFullscreenImage();
    await ticks();
    const post = saves(w).pop();
    return { filename, name: post && post.body ? post.body.name : null, image: post && post.body ? String(post.body.image) : null };
}

/* The chart render probe must carry the workflow identity. Right after a run the rows are
   in the server's memory, but after a page refresh AND a server restart the upstream table
   lives only in the run store, which refuses a bare node id (node-2 repeats on every canvas) —
   so a chart can only be brought back when the request names its workflow, exactly like a
   table preview does. */
async function previewIdentityCase() {
    const w = world();
    w.x.canvas.nodes['nm-1'] = { id: 'nm-1', type: 'name', params: { workflow_name: '情感演化分析' } };
    addChart(w, 'v-1', '图31 发酵期情感', { chart_type: 'bar', engine: 'echarts', x_field: '城市' });
    await w.x.dataNodes.previewVisualize('v-1');
    await ticks();
    const last = renders(w).slice(-1)[0] || {};
    return {
        node_id: (last.body || {}).node_id || null,
        workflow_name: (last.body || {}).workflow_name || null,
    };
}

out.fullscreen_from_board_option = await fullscreenFromBoardOptionCase();
out.fullscreen_from_board_image = await fullscreenFromBoardImageCase();
out.fullscreen_refetch = await fullscreenRefetchCase();
out.fullscreen_from_preview = await fullscreenFromPreviewCase();
out.fullscreen_close_disposes = await fullscreenCloseCase();
out.fullscreen_save_named_after_title = await fullscreenSaveCase();
out.preview_identity = await previewIdentityCase();

/* Wording is asked of the loaded catalog in the sandbox's own language, so a renamed
   key fails here instead of silently changing what the assertions compare. */
const probe = world();
out.catalog = {
    saveNothing: probe.x.I18n.t('chart.saveNothing'),
    saved: probe.x.I18n.t('studio.saved'),
    saveFailed: probe.x.I18n.t('studio.saveFailed'),
    fullscreen: probe.x.I18n.t('chart.fullscreen'),
    lang: probe.x.I18n.lang,
};

out.panel_markup = {
    save_button: panelMarkup.indexOf('savePreviewImage()') >= 0,
    fullscreen_panel: panelMarkup.indexOf('id="chart-fullscreen-panel"') >= 0,
    fullscreen_open_from_preview: panelMarkup.indexOf('openChartFullscreen(_chartPreviewNodeId)') >= 0,
    fullscreen_close: panelMarkup.indexOf('closeChartFullscreen()') >= 0,
    fullscreen_save: panelMarkup.indexOf('saveFullscreenImage()') >= 0,
    fullscreen_title_id: panelMarkup.indexOf('id="chart-fullscreen-title"') >= 0,
    keys: Array.from(panelMarkup.matchAll(/data-i18n="([^"]+)"/g), (m) => m[1]),
    onclicks: Array.from(panelMarkup.matchAll(/onclick="([^"]+)"/g), (m) => m[1]),
};

process.stdout.write(JSON.stringify(out));
