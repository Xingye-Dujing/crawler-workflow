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
/* A node that files its LaTeX writes a real .txt into the export folder and registers it; an
   inline-only preview has nothing registered, so there is nothing the server may compile. */
const RENDER_LATEX = {
    ok: true,
    engine: 'echarts',
    option: { series: [{ type: 'bar' }] },
    latex: 'FIGURE SOURCE',
    latex_table: 'TABLE SOURCE',
    latex_file: 'tu30-a1b2.txt',
    latex_table_file: 'tu30-a1b2-table.txt',
};
const RENDER_LATEX_INLINE = {
    ok: true,
    engine: 'echarts',
    option: { series: [{ type: 'bar' }] },
    latex: 'FIGURE SOURCE',
    latex_table: 'TABLE SOURCE',
};
const RENDER_IMAGE = { ok: true, engine: 'matplotlib', image: 'data:image/png;base64,MATPLOTLIBPICTURE' };

/* A knowledge-map option in the shape `biblio_charts._node_data` ships: every node carries its
   own ``yearSeries`` so the browser can replay the network without a second request. */
const GRAPH_OPTION = () => ({
    series: [
        {
            type: 'graph',
            layout: 'none',
            categories: [{ name: '全部' }],
            data: [
                { name: '甲', x: 0, y: 0, symbolSize: 30, label: { show: true }, yearSeries: [[2020, 1], [2021, 2]] },
                { name: '乙', x: 10, y: 0, symbolSize: 20, label: { show: true }, yearSeries: [[2020, 2]] },
                { name: '丙', x: 20, y: 0, symbolSize: 10, label: { show: true }, yearSeries: [[2021, 1]] },
            ],
            links: [
                { source: '甲', target: '乙', value: 2 },
                { source: '甲', target: '丙', value: 1 },
            ],
        },
    ],
});
const RENDER_GRAPH = { ok: true, engine: 'echarts', option: GRAPH_OPTION() };
/* One year of activity is a picture, not a timeline: the bar would offer a single frame. */
const RENDER_ONE_YEAR = {
    ok: true,
    engine: 'echarts',
    option: {
        series: [
            {
                type: 'graph',
                data: [
                    { name: '甲', symbolSize: 30, yearSeries: [[2020, 3]] },
                    { name: '乙', symbolSize: 20, yearSeries: [[2020, 2]] },
                ],
                links: [],
            },
        ],
    },
};
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
                    applied: [],
                    setOption(opt) { inst.applied.push(opt); },
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
            ' savePreviewVector, saveChartVector, chartSvgMarkup,' +
            ' saveChartPdf, getLatexFile: () => _lastLatexFile,' +
            ' openChartFullscreen, closeChartFullscreen, saveFullscreenImage,' +
            ' getFullscreenInstance: () => _chartFullscreenInstance,' +
            ' getFullscreenOption: () => _chartFullscreenOption,' +
            ' getPreviewNodeId: () => _chartPreviewNodeId,' +
            ' replay: {' +
            '   years: (o) => _replayYears(o), frame: (o, y) => _replayFrame(o, y),' +
            '   show: (k, i) => _replayShow(k, i), all: (k) => _replayAll(k),' +
            '   detach: (k) => _replayDetach(k), current: (k) => _replayCurrentOption(k),' +
            '   surface: (k, stored) => _surfaceOption(k, stored),' +
            '   state: (k) => _replaySurfaces[k] || null,' +
            '   storedOption: (k) => (k === "preview" ? _chartPreviewOption : _chartFullscreenOption),' +
            ' } };',
        sandbox
    );

    sandbox.fetch = (url, init) => {
        const u = String(url);
        const body = init && init.body ? JSON.parse(init.body) : null;
        requests.push({ url: u, body });
        const payload =
            u.indexOf('/api/studio/save-image') >= 0 ||
            u.indexOf('/api/studio/save-vector') >= 0 ||
            u.indexOf('/api/studio/save-pdf') >= 0
                ? answers.save
                : answers.render;
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
    /* Read the toast WITHOUT awaiting a tick: the DOM stub remaps setTimeout to 0 ms, so
       showToast's hide is a pending macrotask. An ``await ticks()`` here drains macrotasks
       and the hide fires first (``setImmediate`` vs ``setTimeout(0)`` order is not
       guaranteed), making ``shown`` flip under full-suite load. The ``!dataUrl`` branch
       toasts synchronously, so the continuation after this single ``await`` is still a
       microtask and the ``.show`` class is provably present. */
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

/* An unexecuted node: the preview panel must read the note, never toast a failure,
   and the internal reference string must not reach the page. */
async function previewNoDataCase() {
    const w = world({ ok: false, code: 'no_run_data', error: 'No tabular result available for node: src-1' });
    addChart(w, 'v-1', '图25 未运行');
    await w.x.dataNodes.previewVisualize('v-1');
    await ticks();
    const html = String(el(w, 'chart-preview-echarts').innerHTML || '');
    return {
        note: html.indexOf(w.x.I18n.t('chart.noRunData')) >= 0,
        rawLeaked: html.indexOf('No tabular result') >= 0,
        toastShown: w.toast().shown,
    };
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
out.preview_no_run_data = await previewNoDataCase();
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
    saveVectorFailed: probe.x.I18n.t('chart.saveVectorFailed'),
    fullscreen: probe.x.I18n.t('chart.fullscreen'),
    lang: probe.x.I18n.lang,
};

out.panel_markup = {
    save_button: panelMarkup.indexOf('savePreviewImage()') >= 0,
    fullscreen_panel: panelMarkup.indexOf('id="chart-fullscreen-panel"') >= 0,
    fullscreen_open_from_preview: panelMarkup.indexOf('openChartFullscreen(_chartPreviewNodeId)') >= 0,
    fullscreen_close: panelMarkup.indexOf('closeChartFullscreen()') >= 0,
    fullscreen_save: panelMarkup.indexOf('saveFullscreenImage()') >= 0,
    preview_save_vector: panelMarkup.indexOf('savePreviewVector()') >= 0,
    fullscreen_save_vector: panelMarkup.indexOf('saveFullscreenVector()') >= 0,
    fullscreen_title_id: panelMarkup.indexOf('id="chart-fullscreen-title"') >= 0,
    keys: Array.from(panelMarkup.matchAll(/data-i18n="([^"]+)"/g), (m) => m[1]),
    onclicks: Array.from(panelMarkup.matchAll(/onclick="([^"]+)"/g), (m) => m[1]),
};

/* ── Vector export ────────────────────────────────────────────────────────────
 * The success path needs a real SVG renderer, so it is measured in the browser tier
 * (`test_ui_layout.py` paints an option and reads the markup back). What is provable HERE is
 * that both ways the vector path fails are NAMED and send no request: a button that silently
 * does nothing reads as a broken app, and posting an empty body would blame the server. */
async function vectorNothingCase() {
    const w = world();
    const name = await w.x.savePreviewVector();
    return { name, toast: w.toast(), asked: w.requests.map((r) => r.url) };
}

async function vectorNoMarkupCase() {
    const w = world();
    const name = await w.x.saveChartVector({ series: [{ type: 'bar' }] }, '图23', 'chart-preview-echarts');
    return {
        name,
        toast: w.toast(),
        asked: w.requests.map((r) => r.url),
        markup: w.x.chartSvgMarkup({ series: [{ type: 'bar' }] }, 800, 600),
    };
}

/* ── The LaTeX bar's one-click PDF ─────────────────────────────────────────── */
async function latexBarCase(render) {
    const w = world(render);
    addChart(w, 'v-1', '图30 结构变异');
    await w.x.dataNodes.previewVisualize('v-1');
    await ticks();
    const bar = w.sandbox.document.getElementById('latex-action-bar');
    const html = String((bar && bar.innerHTML) || '');
    const askedBefore = w.requests.length;
    const filename = await w.x.saveChartPdf();
    await ticks();
    const post = w.requests.slice(askedBefore).pop();
    return {
        html,
        hasPdfButton: html.indexOf('saveChartPdf()') >= 0,
        registered: w.x.getLatexFile(),
        filename,
        url: post ? post.url : null,
        sentName: post && post.body ? post.body.name : null,
        sentSource: post && post.body ? Object.keys(post.body) : null,
        asked: w.requests.length - askedBefore,
        toast: w.toast(),
    };
}

out.latex_bar_registered = await latexBarCase(RENDER_LATEX);
out.latex_bar_inline_only = await latexBarCase(RENDER_LATEX_INLINE);

out.vector_nothing_drawn = await vectorNothingCase();
out.vector_no_markup = await vectorNoMarkupCase();

/* ── Replay the network year by year ───────────────────────────────────────
   The bar is an inspection affordance, so what matters is that it never lies about the
   figure: the last frame has to BE the whole network, the stored option has to survive
   every seek, an export has to carry what is on screen, and a window with nothing to
   replay (a bar chart, or one year of data) has to offer no button at all.
   Wording is read back through `I18n.t`, never pasted. */
async function replayCase() {
    const w = world(RENDER_GRAPH);
    addChart(w, 'v-9', '关键词知识图谱');
    await w.x.dataNodes.previewVisualize('v-9');
    await ticks();
    const doc = w.sandbox.document;
    const panel = doc.getElementById('chart-preview-panel');
    const bar = panel.querySelector('.chart-replay-bar');
    const readout = () => panel.querySelector('.chart-replay-year').textContent;
    const slider = panel.querySelector('.chart-replay-range');
    const instance = () => w.created[0];
    const applied = () => instance().applied[instance().applied.length - 1];
    const before = JSON.stringify(w.x.replay.storedOption('preview'));

    const first = {
        bar: !!bar,
        sliderMax: slider ? slider.max : null,
        sliderValue: slider ? slider.value : null,
        readout: readout(),
        readoutWord: w.x.I18n.t('chart.replayAllYears'),
        playLabel: panel.querySelector('.chart-replay-play').textContent,
        playWord: w.x.I18n.t('chart.replayPlay'),
        hint: panel.querySelector('.chart-replay-hint').textContent,
        hintWord: w.x.I18n.t('chart.replayHint'),
        years: w.x.replay.years(w.x.replay.storedOption('preview')),
    };

    w.x.replay.show('preview', 0);
    const frameData = {};
    applied().series[0].data.forEach((node) => { frameData[node.name] = node; });
    const frameLinks = applied().series[0].links;
    const afterFirst = {
        readout: readout(),
        readoutExpected: w.x.I18n.t('chart.replayYear', { year: 2020 }),
        sliderValue: slider.value,
        futureNodeHidden: frameData['丙'].itemStyle.opacity === 0 && frameData['丙'].label.show === false,
        pastNodeSize: frameData['甲'].symbolSize,
        untouchedNodeSize: frameData['乙'].symbolSize,
        linkAcrossTheGapHidden: frameLinks[1].lineStyle ? frameLinks[1].lineStyle.opacity === 0 : false,
        linkInsideTheFrameShown: !frameLinks[0].lineStyle || frameLinks[0].lineStyle.opacity !== 0,
        optionUntouched: JSON.stringify(w.x.replay.storedOption('preview')) === before,
        exportIsTheFrame: w.x.replay.surface('preview', w.x.replay.storedOption('preview')) === w.x.replay.current('preview'),
    };

    w.x.replay.show('preview', first.years.length - 1);
    const lastData = {};
    applied().series[0].data.forEach((node) => { lastData[node.name] = node; });
    const lastFrame = {
        sizesAreTheFigures: Object.keys(lastData).every((name) => lastData[name].symbolSize === GRAPH_OPTION().series[0].data.find((n) => n.name === name).symbolSize),
        nothingHidden: Object.keys(lastData).every((name) => !lastData[name].itemStyle || lastData[name].itemStyle.opacity === undefined),
        linksUntouched: applied().series[0].links.every((l) => !l.lineStyle || l.lineStyle.opacity === undefined),
    };

    w.x.replay.all('preview');
    const reset = {
        readout: readout(),
        current: w.x.replay.current('preview'),
        exportIsTheStoredOption: w.x.replay.surface('preview', w.x.replay.storedOption('preview')) === w.x.replay.storedOption('preview'),
        repaintedWholeOption: applied() === w.x.replay.storedOption('preview'),
    };

    w.x.replay.detach('preview');
    const detached = { bar: !!panel.querySelector('.chart-replay-bar'), state: w.x.replay.state('preview') };

    return { first, afterFirst, lastFrame, reset, detached };
}

async function noReplayCase(render) {
    const w = world(render);
    addChart(w, 'v-8', '没有可回放的图');
    await w.x.dataNodes.previewVisualize('v-8');
    await ticks();
    const panel = w.sandbox.document.getElementById('chart-preview-panel');
    return { bar: !!panel.querySelector('.chart-replay-bar'), state: w.x.replay.state('preview') };
}

async function fullscreenOptionCase() {
    const w = world(RENDER_GRAPH);
    addChart(w, 'v-7', '关键词知识图谱');
    await w.x.dataNodes.previewVisualize('v-7');
    await ticks();
    await w.x.openChartFullscreen('v-7');
    await ticks();
    const fsPanel = w.sandbox.document.getElementById('chart-fullscreen-panel');
    const opened = {
        hasOption: !!w.x.getFullscreenOption(),
        bar: !!fsPanel.querySelector('.chart-replay-bar'),
        state: !!w.x.replay.state('fullscreen'),
        years: w.x.replay.years(w.x.getFullscreenOption()),
    };
    w.x.closeChartFullscreen();
    return { opened, closed: { hasOption: !!w.x.getFullscreenOption(), bar: !!fsPanel.querySelector('.chart-replay-bar') } };
}

out.replay = await replayCase();
out.replay_absent_for_a_plain_bar = await noReplayCase(RENDER_ECHARTS);
out.replay_absent_for_one_year = await noReplayCase(RENDER_ONE_YEAR);
out.fullscreen_keeps_its_own_option = await fullscreenOptionCase();

process.stdout.write(JSON.stringify(out));
