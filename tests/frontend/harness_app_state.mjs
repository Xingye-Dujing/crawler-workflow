/* Runs the REAL application state layer (app.js) under node.
 *
 * These objects decide what the server is told. `LLMSettings.payload()` in
 * particular builds the body of every run request, and until now it was *stubbed*
 * in every harness that needed a run — so the function that chooses which
 * provider's model travels, and whether the API key travels at all, had never been
 * executed. Likewise:
 *
 *   · the two transports keep separate blocks because sharing one `model` field let
 *     a local Ollama run inherit an OpenRouter catalog id;
 *   · `payload()` must never leak the OpenRouter key when Ollama is active, and
 *     must never send an Ollama tag while OpenRouter is chosen;
 *   · `load()` normalises an unknown provider to the local one, and migrates the
 *     pre-split flat `model`/`api_key` pair;
 *   · `save()` drops the flat keys so a cleared OpenRouter id cannot resurface;
 *   · `RunState.set/toggle/setRunning` persist and re-sync the top menu;
 *   · `Settings.apply()` restores language, background, run switches, menu pin and
 *     corner radius from the draft;
 *   · `AppSettings` writes the server-side settings file, including the booleans
 *     that gate a run (cookie confirmation, live export).
 *
 * Usage: node harness_app_state.mjs <canvas.js> <workflow.js> <app.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow, resetWorld } from './harness_dom.mjs';

const [canvasPath, wfPath, appPath] = process.argv.slice(2);
const src = [canvasPath, wfPath, appPath].map((p) => fs.readFileSync(p, 'utf8')).join('\n;\n');

/* app.js owns I18n (a top-level `const`), so nothing is seeded for it here: the
   assertions below read the effect of the REAL dictionary and the REAL apply(),
   which is the only version that can drift from the shipped app. */
const requests = [];
const sandbox = { ...baseSandbox() };
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(
    `${src}
     ;globalThis.__app = { RunState, Settings, LLMSettings, AppSettings, convertToFloating, onSettingInput, I18n };
     globalThis.__canvas = canvas;`,
    sandbox,
);
/* Installed after the load: app.js declares fetch-using functions itself, and the
   recording stub has to be what those bodies see when they run. */
let settingsAnswer = { ok: true, settings: {}, warnings: [] };
sandbox.fetch = (url, opts) => {
    requests.push({ url: String(url), opts });
    if (String(url).indexOf('/api/config') === 0) {
        return Promise.resolve({ json: () => Promise.resolve({ ollama_model: 'qwen-pulled:7b' }) });
    }
    if (String(url).indexOf('/api/settings') === 0) {
        return Promise.resolve({ json: () => Promise.resolve(settingsAnswer) });
    }
    return Promise.resolve({ json: () => Promise.resolve({ ok: true, models: ['a:free', 'b:free'] }) });
};
/* The radius token is read back through computed style when the draft is written,
   so a fixed answer is what makes `Settings.save()` assertable. */
sandbox.getComputedStyle = (el) => ({ getPropertyValue: (p) => (p === '--radius' ? '6px' : ''), right: 'auto', transform: 'none' });

const app = sandbox.__app;
const { RunState, Settings, LLMSettings, AppSettings, convertToFloating, onSettingInput } = app;
const canvas = sandbox.__canvas;
const doc = sandbox.document;
const out = {};

const LLM_KEY = 'crawler_llm';
const SETTINGS_KEY = 'crawler_settings';

function setLlm(value) {
    sandbox.localStorage.setItem(LLM_KEY, typeof value === 'string' ? value : JSON.stringify(value));
}
function readLlm() {
    return JSON.parse(sandbox.localStorage.getItem(LLM_KEY) || 'null');
}
function clearStored() {
    resetWorld(sandbox);
    sandbox.localStorage.removeItem(LLM_KEY);
    sandbox.localStorage.removeItem(SETTINGS_KEY);
    sandbox.localStorage.removeItem('crawler_app_settings');
    requests.length = 0;
}

/* ── LLMSettings.payload: the body every run is sent with ───────────── */
clearStored();
out.payload_defaults = LLMSettings.payload();

clearStored();
LLMSettings.save({ provider: 'openrouter', ollama: { model: 'local-tag' }, openrouter: { model: 'catalog:free', api_key: 'sk-secret' } });
out.payload_openrouter = LLMSettings.payload();

clearStored();
LLMSettings.save({ provider: 'ollama', ollama: { model: 'local-tag' }, openrouter: { model: 'catalog:free', api_key: 'sk-secret' } });
out.payload_ollama = LLMSettings.payload();

/* A hand-edited provider must not desync the panel from the backend, which treats
   every non-OpenRouter value as the local daemon. */
clearStored();
setLlm({ provider: 'openai', model: 'x', ollama: { model: 'local-tag' } });
out.payload_unknown_provider = LLMSettings.payload();

/* The pre-split shape: one flat pair, no nested blocks. */
clearStored();
setLlm({ provider: 'openrouter', model: 'legacy:free', api_key: 'sk-legacy' });
out.migrated_legacy_shape = { loaded: LLMSettings.load(), payload: LLMSettings.payload() };

/* save() writes the nested shape only, so a cleared catalog id cannot come back. */
clearStored();
setLlm({ provider: 'openrouter', model: 'legacy:free', api_key: 'sk-legacy', openrouter: { model: '', api_key: '' } });
const afterSave = LLMSettings.save({});
out.save_drops_flat_keys = { hasFlatModel: 'model' in afterSave, hasFlatKey: 'api_key' in afterSave, stored: readLlm() };

/* Corrupt storage is a settings panel that still opens. */
clearStored();
setLlm('{not json');
out.corrupt_storage = { payload: LLMSettings.payload(), threw: false };

/* One provider's block changes without disturbing the other's. */
clearStored();
LLMSettings.save({ provider: 'openrouter', ollama: { model: 'keep-me' }, openrouter: { model: 'old:free', api_key: 'k' } });
out.save_provider_patch = {
    after: LLMSettings.saveProvider('openrouter', { model: 'new:free' }),
    payload: LLMSettings.payload(),
};

/* A number the panel cannot parse must not become NaN in a run body. */
clearStored();
LLMSettings.save({ batch_size: 10 });
out.numeric_bounds_loaded = LLMSettings.load();

/* ── LLMSettings panel mirroring ───────────────────────────────────── */
clearStored();
LLMSettings.save({ provider: 'openrouter', ollama: { model: 'local-tag' }, openrouter: { model: 'cat:free', api_key: 'sk' }, batch_size: 7, max_chars: 900 });
LLMSettings.applyToPanel();
out.apply_to_panel = {
    provider: doc.getElementById('ai-provider').value,
    ollamaModel: doc.getElementById('ai-ollama-model').value,
    routerModel: doc.getElementById('ai-model').value,
    key: doc.getElementById('ai-key').value,
    batch: doc.getElementById('ai-batch').value,
    maxChars: doc.getElementById('ai-maxchars').value,
};
clearStored();
LLMSettings.save({ provider: 'ollama', openrouter: { model: 'cat:free', api_key: 'sk' } });
/* The provider rows exist only while the AI panel is open, and the panel builds
   them from markup; register two so the toggle has something to hide. */
const ollamaRow = doc.createElement('div');
ollamaRow.className = 'ai-only-ollama';
const routerRow = doc.createElement('div');
routerRow.className = 'ai-only-openrouter';
doc.body.appendChild(ollamaRow);
doc.body.appendChild(routerRow);
LLMSettings.applyToPanel();
out.provider_rows = {
    ollamaShown: ollamaRow.style.display,
    routerHidden: routerRow.style.display,
};
LLMSettings.save({ provider: 'openrouter' });
LLMSettings.applyToPanel();
out.provider_rows_after_switch = {
    ollamaShown: ollamaRow.style.display,
    routerHidden: routerRow.style.display,
};

/* The placeholder is the server's configured default, not a copy of it. */
clearStored();
async function defaultsAndHost() {
    await LLMSettings.loadDefaults();
    const placeholder = doc.getElementById('ai-ollama-model').placeholder;
    const secondCall = LLMSettings._defaultsPulled;
    /* The address shown is the one the SERVER has, so it comes from
       AppSettings._values — not from a window alias. */
    const hostEl = doc.getElementById('ai-ollama-host');
    hostEl.textContent = '';
    const realValues = AppSettings._values;
    AppSettings._values = { ollama_host: 'http://10.0.0.9:11434' };
    LLMSettings.renderOllamaHost();
    const withValue = hostEl.textContent;
    AppSettings._values = {};
    LLMSettings.renderOllamaHost();
    const fallback = hostEl.textContent;
    AppSettings._values = realValues;
    return {
        placeholder,
        pulledOnce: secondCall === true,
        requested: requests.map((r) => r.url),
        withValue,
        fallsBack: fallback,
    };
}

/* ── RunState ──────────────────────────────────────────────────────── */
clearStored();
const refreshes = [];
sandbox.window.TopMenu = { refresh: () => refreshes.push(true) };
RunState.parallel = true;
RunState.headless = true;
RunState.set('parallel', false);
out.run_state = {
    afterSet: { parallel: RunState.parallel, headless: RunState.headless },
    persisted: JSON.parse(sandbox.localStorage.getItem(SETTINGS_KEY)),
    refreshed: refreshes.length,
};
RunState.toggle('headless');
out.run_state.toggled = { headless: RunState.headless, refreshed: refreshes.length };
RunState.setRunning(true);
out.run_state.running = { running: RunState.running, menuRefreshed: refreshes.length };
RunState.set('parallel', 'yes-a-string');
out.run_state.coerces_to_boolean = typeof RunState.parallel === 'boolean' && RunState.parallel === true;
RunState.setRunning(0);
out.run_state.running_off = RunState.running;
/* A missing TopMenu (the panel never loaded) must not break the switch. */
delete sandbox.window.TopMenu;
RunState.toggle('parallel');
out.run_state.works_without_menu = typeof RunState.parallel === 'boolean';

/* ── Settings.save / apply ────────────────────────────────────────── */
clearStored();
canvas.zoom = 2.5;
doc.body.classList.add('bg-dots');
doc.getElementById('top-menu').classList.add('pinned');
doc.body.dataset.lang = 'en';
RunState.parallel = false;
RunState.headless = false;
Settings.save();
out.settings_saved = JSON.parse(sandbox.localStorage.getItem(SETTINGS_KEY));

clearStored();
sandbox.localStorage.setItem(SETTINGS_KEY, JSON.stringify({ bg: 'bg-grid', parallel: false, headless: false, menuPinned: false, lang: 'zh', radius: 9 }));
/* app.js declares I18n itself, so the seeded one is gone: the assertion is on what
   the real apply() leaves behind — every [data-i18n] element stamped in the new
   language. That is the observable effect, and it cannot drift from the real dict. */
const labelled = doc.createElement('span');
labelled.dataset.i18n = 'btn.lang';
labelled.textContent = 'stale';
const titled = doc.createElement('button');
titled.dataset.i18nTitle = 'pin.title';
doc.body.appendChild(labelled);
doc.body.appendChild(titled);
Settings.apply();
out.settings_applied = {
    languageTag: doc.body.dataset.lang,
    stampedLabel: labelled.textContent,
    stampedTitle: titled.title,
    background: Array.from(doc.body._classes).filter((c) => c.startsWith('bg-')),
    parallel: RunState.parallel,
    headless: RunState.headless,
    menuPinned: doc.getElementById('top-menu').classList.contains('pinned'),
    pinPressed: doc.getElementById('pin-btn').getAttribute('aria-pressed'),
    radiusToken: doc.documentElement.style.getPropertyValue('--radius'),
    slider: doc.getElementById('radius-slider').value,
    label: doc.getElementById('radius-val').textContent,
};
/* Switching to English re-stamps the same element from the same attribute. */
doc.body.dataset.lang = 'en';
app.I18n.apply();
out.settings_applied.englishLabel = labelled.textContent;

clearStored();
out.settings_first_run = { load: Settings.load(), appliedWithoutDraft: true };
Settings.apply();
out.settings_first_run.parallelDefault = RunState.parallel;

clearStored();
sandbox.localStorage.setItem(SETTINGS_KEY, '{broken');
let applyThrew = false;
try {
    Settings.apply();
} catch (e) {
    applyThrew = true;
}
out.settings_corrupt_draft = { threw: applyThrew };

/* ── AppSettings (the server-side file) ───────────────────────────── */
clearStored();
async function appSettings() {
    const results = {};
    const toasts = [];
    sandbox.showToast = (m) => toasts.push(String(m));
    /* A stub element has no `type`, so the panel's checkbox/text branch would always
       take the text path; declare the two shapes the real panel contains. */
    doc.getElementById('set-cookie-confirm').type = 'checkbox';
    doc.getElementById('set-driver').type = 'text';
    settingsAnswer = { ok: true, settings: { driver_path: 'D:\\chromedriver.exe', page_load_timeout: 40, cookie_confirm_before_run: true }, warnings: [] };
    await AppSettings.pull();
    results.pulled = {
        values: AppSettings._values,
        driver: doc.getElementById('set-driver').value,
        pageload: doc.getElementById('set-pageload').value,
        /* A checkbox answers to .checked: writing .value instead leaves the panel
           showing a box that is not what the server has. */
        confirmChecked: doc.getElementById('set-cookie-confirm').checked,
        missingKeyLeftAlone: doc.getElementById('set-window').value,
    };
    /* A second pull is a no-op unless forced — the panel must not lose unsaved
       edits every time the settings menu opens. */
    requests.length = 0;
    await AppSettings.pull();
    results.second_pull_requested = requests.length;
    await AppSettings.pull(true);
    results.forced_requested = requests.length;
    /* Nothing staged: saving says so and sends no request. */
    requests.length = 0;
    toasts.length = 0;
    await AppSettings.save();
    results.no_change = { requested: requests.length, toasts: toasts.slice() };
    requests.length = 0;
    toasts.length = 0;
    onSettingInput('driver_path', 'C:\\drivers\\cd.exe');
    onSettingInput('ollama_host', 'http://127.0.0.1:11435');
    const saveBtn = doc.getElementById('set-save-btn');
    const promise = AppSettings.save();
    results.button_disabled_while_writing = saveBtn.disabled === true;
    await promise;
    results.save = {
        method: requests[0] && requests[0].opts.method,
        body: requests[0] && JSON.parse(requests[0].opts.body),
        button_released: saveBtn.disabled === false,
        draft_cleared: Object.keys(AppSettings._draft).length,
        toasts: toasts.slice(),
    };
    /* A refusal is reported, not swallowed. */
    requests.length = 0;
    toasts.length = 0;
    settingsAnswer = { ok: false, error: 'disk full' };
    onSettingInput('window_size', '1280,720');
    await AppSettings.save();
    results.rejected = { toasts: toasts.slice(), values_unchanged: AppSettings._values.driver_path };
    /* A warning alongside a successful save must reach the user too. */
    toasts.length = 0;
    settingsAnswer = { ok: true, settings: { driver_path: 'D:\\cd.exe' }, warnings: ['驱动版本偏旧'] };
    onSettingInput('page_load_timeout', '20');
    await AppSettings.save();
    results.warned = toasts.slice();
    return results;
}

/* ── the floating conversion a docked panel leans on ──────────────── */
clearStored();
const anchored = doc.createElement('div');
/* `right`/`transform` come from CSS classes here, so the conversion has to read
   computed style — reading .style would do nothing to a class-anchored panel. */
sandbox.getComputedStyle = () => ({ getPropertyValue: () => '', right: '12px', transform: 'none' });
anchored.style.right = '12px';
convertToFloating(anchored);
out.convert = {
    pinnedLeft: anchored.style.getPropertyValue ? anchored.style.left : anchored.style.left,
    topPinned: anchored.style.top,
    rightReleased: anchored.style.right === 'auto',
};
sandbox.getComputedStyle = (el) => ({ getPropertyValue: (p) => (p === '--radius' ? '6px' : ''), right: 'auto', transform: 'none' });
const staticEl = doc.createElement('div');
convertToFloating(staticEl);
out.convert.untouched_when_not_anchored = staticEl.style.left === undefined;

/* menu.js's pin button and the style controls live behind these. */
clearStored();
out.pinned_default = Settings.load().menuPinned;

defaultsAndHost().then((dh) => {
    out.llm_async = dh;
    return appSettings();
}).then((as) => {
    out.app_settings = as;
    process.stdout.write(JSON.stringify(out));
}).catch((err) => {
    process.stdout.write(JSON.stringify({ error: String(err && err.stack) }));
});
