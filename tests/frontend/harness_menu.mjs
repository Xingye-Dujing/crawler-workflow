/* Runs the REAL top menu (menu.js) under node — the file no harness loaded.
 *
 * menu.js is the only place the bar's stateful controls are kept truthful: which
 * toggle is on, what the Run button says, whether Stop is pressable, which language
 * and background swatch is marked active, and what the radius slider shows. Every
 * one of those is a claim about state held elsewhere, so the whole family of
 * "the UI said X while the app knew Y" bugs lives here.
 *
 * Submenu behaviour is the other half: opening one closes the others, an outside
 * click / Escape / window resize dismiss them, and the corner-radius control writes
 * the single --radius token the whole stylesheet reads *and* the draft that has to
 * survive a reload.
 *
 * Usage: node harness_menu.mjs <canvas.js> <workflow.js> <stats.js> <app.js> <menu.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, dispatchDocument, dispatchWindow, fixWindow, resetWorld } from './harness_dom.mjs';

const paths = process.argv.slice(2);
const src = paths.map((p) => fs.readFileSync(p, 'utf8')).join('\n;\n');

const requests = [];
const sandbox = {
    ...baseSandbox(),
    fetch: (url, opts) => {
        requests.push({ url: String(url), opts });
        if (String(url).indexOf('/api/config') === 0) {
            return Promise.resolve({ json: () => Promise.resolve({ ollama_model: 'qwen:7b' }) });
        }
        return Promise.resolve({ json: () => Promise.resolve({ ok: true, settings: {}, models: [] }) });
    },
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
/* RunState/Settings/TopMenu are top-level declarations inside their own files, so
   only an explicit window.X assignment crosses over. The scenario therefore drives
   the very bindings menu.js reads, exported from inside the script itself. */
vm.runInContext(
    `${src}
     ;globalThis.__menu = { TopMenu, toggleStyleMenu, closeStyleMenu, toggleAiMenu, closeAiMenu,
                            toggleSettingsMenu, closeSettingsMenu, setRadius };
     globalThis.__state = { RunState, Settings, LLMSettings, AppSettings, canvas, workflow };`,
    sandbox,
);
const toasts = [];
sandbox.showToast = (m) => toasts.push(String(m));

const menu = sandbox.__menu;
const state = sandbox.__state;
const { TopMenu, setRadius } = menu;
const doc = sandbox.document;
const out = {};

function id(name) {
    return doc.getElementById(name);
}

/** The bar's language / background swatches exist only in index.html; register the
 *  shapes sync() walks so its "which one is active" loop has something to answer. */
function buildBar() {
    ['en', 'zh'].forEach((lang) => {
        const btn = doc.createElement('button');
        btn.className = 'lang-btn';
        btn.dataset.lang = lang;
        doc.body.appendChild(btn);
    });
    ['bg-grid', 'bg-dots', 'bg-void'].forEach((bg) => {
        const dot = doc.createElement('span');
        dot.className = 'bar-bg-dot';
        dot.dataset.bg = bg;
        doc.body.appendChild(dot);
    });
}

function active(selector) {
    return doc.querySelectorAll(selector).filter((el) => el.classList.contains('active')).map((el) => el.dataset.lang || el.dataset.bg);
}

function fresh() {
    resetWorld(sandbox);
    sandbox.localStorage.removeItem('crawler_settings');
    sandbox.localStorage.removeItem('crawler_llm');
    doc.documentElement.style.removeProperty('--radius');
    doc.body.className = '';
    doc.body.dataset.lang = 'zh';
    doc.body.classList.add('bg-grid');
    requests.length = 0;
    toasts.length = 0;
    buildBar();
    state.RunState.parallel = true;
    state.RunState.headless = true;
    state.RunState.running = false;
}

/** init() is what installs the outside-click / Escape / resize dismissal listeners;
 *  a scenario that tests them without it is dispatching into an empty table. */
function started() {
    fresh();
    TopMenu.init();
}

/* ── sync(): the bar restates state it does not own ────────────────── */
fresh();
id('btn-parallel').className = 'menu-btn stale';
id('btn-headless').className = 'menu-btn stale';
TopMenu.sync();
out.sync = {
    parallelClass: id('btn-parallel').className,
    headlessClass: id('btn-headless').className,
};

fresh();
state.RunState.parallel = false;
state.RunState.headless = false;
TopMenu.sync();
out.sync_off = {
    parallelClass: id('btn-parallel').className,
    headlessClass: id('btn-headless').className,
};

/* The Execute button is never disabled: it relabels to "queue this run". */
fresh();
state.RunState.running = false;
TopMenu.sync();
out.execute_idle = { disabled: id('btn-execute').disabled, label: id('btn-execute').textContent, stop: id('btn-stop').disabled };
state.RunState.running = true;
TopMenu.sync();
out.execute_running = { disabled: id('btn-execute').disabled, label: id('btn-execute').textContent, stop: id('btn-stop').disabled };

/* language + background markers */
fresh();
doc.body.dataset.lang = 'en';
TopMenu.sync();
out.language_marker = active('.lang-btn');
doc.body.dataset.lang = 'zh';
TopMenu.sync();
out.language_marker_zh = active('.lang-btn');

fresh();
doc.body.className = '';
doc.body.classList.add('bg-dots');
TopMenu.sync();
out.background_marker = active('.bar-bg-dot');
doc.body.classList.remove('bg-dots');
doc.body.classList.add('bg-void');
TopMenu.sync();
out.background_marker_other = active('.bar-bg-dot');

/* radius read-back */
fresh();
doc.documentElement.style.setProperty('--radius', '7px');
TopMenu.sync();
out.radius_shown = { slider: id('radius-slider').value, label: id('radius-val').textContent };
fresh();
TopMenu.sync();
out.radius_unset = { slider: id('radius-slider').value, label: id('radius-val').textContent };

/* ── submenus are mutually exclusive ───────────────────────────────── */
function menuState() {
    return {
        style: id('style-menu').classList.contains('open'),
        ai: id('ai-menu').classList.contains('open'),
        settings: id('settings-menu').classList.contains('open'),
        styleBtn: id('btn-style').classList.contains('active'),
        aiBtn: id('btn-ai').classList.contains('active'),
        settingsBtn: id('btn-settings').classList.contains('active'),
        bodyFlag: doc.body.classList.contains('style-menu-open'),
    };
}

fresh();
menu.toggleStyleMenu({ stopPropagation() {} });
out.style_open = { ...menuState(), left: id('style-menu').style.left, top: id('style-menu').style.top };
menu.toggleStyleMenu({ stopPropagation() {} });
out.style_toggled_closed = menuState();

fresh();
menu.toggleStyleMenu({ stopPropagation() {} });
menu.toggleAiMenu({ stopPropagation() {} });
out.ai_closes_style = menuState();
menu.toggleSettingsMenu({ stopPropagation() {} });
out.settings_closes_ai = menuState();

/* outside click closes each one, a click inside does not */
started();
menu.toggleStyleMenu({ stopPropagation() {} });
dispatchDocument(sandbox.__handlers, 'click', { target: { closest: (sel) => (sel === '#style-menu' ? id('style-menu') : null) } });
out.style_survives_inside_click = menuState().style;
dispatchDocument(sandbox.__handlers, 'click', { target: { closest: () => null } });
out.style_closed_by_outside_click = menuState().style === false;

started();
menu.toggleAiMenu({ stopPropagation() {} });
dispatchDocument(sandbox.__handlers, 'click', { target: { closest: (sel) => (sel === '#btn-ai' ? id('btn-ai') : null) } });
out.ai_survives_its_own_button = menuState().ai;
dispatchDocument(sandbox.__handlers, 'click', { target: { closest: () => null } });
out.ai_closed_by_outside_click = menuState().ai === false;

started();
menu.toggleSettingsMenu({ stopPropagation() {} });
dispatchDocument(sandbox.__handlers, 'click', { target: { closest: () => null } });
out.settings_closed_by_outside_click = menuState().settings === false;

/* a press that lands on a *different* top-menu button must not be treated as
   "outside" for the menu it belongs to */
started();
menu.toggleStyleMenu({ stopPropagation() {} });
dispatchDocument(sandbox.__handlers, 'click', { target: { closest: (sel) => (sel === '#btn-style' ? id('btn-style') : null) } });
out.style_survives_its_own_button = menuState().style;

/* Escape closes all three; so does a window resize */
started();
menu.toggleStyleMenu({ stopPropagation() {} });
menu.toggleAiMenu({ stopPropagation() {} });
menu.toggleSettingsMenu({ stopPropagation() {} });
dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Escape' });
out.escape_closed_everything = menuState();
started();
menu.toggleStyleMenu({ stopPropagation() {} });
menu.toggleAiMenu({ stopPropagation() {} });
dispatchWindow(sandbox.__handlers, 'resize');
out.resize_closed = menuState();
/* An unrelated key must not dismiss anything. */
started();
menu.toggleAiMenu({ stopPropagation() {} });
dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Enter' });
out.other_key_keeps_menu = menuState().ai;

/* an opening called with no event at all (a keyboard activation) must not throw */
fresh();
let threw = false;
try {
    menu.toggleStyleMenu();
    menu.toggleAiMenu();
    menu.toggleSettingsMenu();
} catch (e) {
    threw = true;
}
out.no_event_is_tolerated = threw === false;

/* ── the corner radius control ─────────────────────────────────────── */
function radiusToken() {
    return sandbox.getComputedStyle(doc.documentElement).getPropertyValue('--radius');
}
fresh();
setRadius('6');
out.radius_applied = { token: radiusToken(), label: id('radius-val').textContent, draft: JSON.parse(sandbox.localStorage.getItem('crawler_settings')).radius };
fresh();
setRadius('99');
out.radius_clamped_high = radiusToken();
fresh();
setRadius('-4');
out.radius_clamped_low = radiusToken();
fresh();
setRadius('abc');
out.radius_unparseable_is_zero = radiusToken();
fresh();
setRadius('');
out.radius_blank_is_zero = radiusToken();
/* A corrupt draft must not stop the corner from changing. */
fresh();
sandbox.localStorage.setItem('crawler_settings', '{broken');
let radiusThrew = false;
try {
    setRadius('5');
} catch (e) {
    radiusThrew = true;
}
out.radius_with_corrupt_draft = { threw: radiusThrew, token: radiusToken() };

/* ── init(): what the bar does at start-up ─────────────────────────── */
async function startUp() {
    fresh();
    TopMenu.init();
    const synced = id('btn-parallel').className.indexOf('toggle-') >= 0;
    const listeners = {
        click: (sandbox.__handlers.document.click || []).length,
        keydown: (sandbox.__handlers.document.keydown || []).length,
        resize: (sandbox.__handlers.window.resize || []).length,
    };
    /* init() fires the AI placeholder and server-settings reads without awaiting
       them, so the requests have to be given a turn before they are visible.
       `_defaultsPulled` is a one-shot latch a previous init() already spent, so it
       is cleared here to observe what a genuine first load asks for. */
    state.LLMSettings._defaultsPulled = false;
    requests.length = 0;
    TopMenu.init();
    await new Promise((resolve) => setImmediate(resolve));
    const asked = requests.map((r) => r.url);
    const stillLatched = state.LLMSettings._defaultsPulled;
    TopMenu.init();
    const doubled = (sandbox.__handlers.document.click || []).length;
    return { synced, listeners, asked, stillLatched, secondInitClickListeners: doubled };
}

/* TopMenu.refresh is the hook RunState and setLang call. */
fresh();
state.RunState.parallel = false;
TopMenu.refresh();
out.refresh_routes_to_sync = id('btn-parallel').className.indexOf('toggle-off') >= 0;
fresh();
TopMenu.close();
out.close_dismisses_style = menuState().style === false;

startUp().then((started) => {
    out.init = started;
    process.stdout.write(JSON.stringify(out));
}).catch((err) => {
    process.stdout.write(JSON.stringify({ error: String(err && err.stack) }));
});
