/* Drives the REAL settings page (panels/settings-panel.js) against a schema answer.
 *
 * The panel is the only place a user can change the crawl-wide values, so what it
 * renders and what it posts are product behaviour, not decoration:
 *   · every group and field comes from /api/settings/schema, not a second list;
 *   · a changed field is posted under ITS key, and a default restores the declared value;
 *   · the 慢速采集 card applies/restores through the preset route;
 *   · export asks for the machine-path opt-in the user actually ticked.
 *
 * Usage: node harness_settings_panel.mjs
 * Prints one JSON object to stdout.
 */
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const sandbox = { ...baseSandbox() };
sandbox.console = { log() {}, warn() {}, error() {} };
vm.createContext(sandbox);
fixWindow(vm, sandbox);

const ids = [
    'settings-panel',
    'settings-panel-nav',
    'settings-panel-form',
    'settings-panel-warnings',
    'settings-panel-status',
    'settings-panel-save',
    'settings-export-btn',
    'settings-import-btn',
    'settings-include-machine',
    'settings-import-file',
    'settings-panel-search',
    'settings-preset-card',
];
for (const id of ids) {
    const el = sandbox.document.createElement('input');
    el.id = id;
    el.type = 'checkbox';
    el.value = '';
    el.checked = false;
}

const posted = [];
const toasts = [];
let answer = {};
sandbox.fetch = (url, opts) => {
    posted.push({ url: String(url), body: opts && opts.body ? JSON.parse(opts.body) : null, method: (opts && opts.method) || 'GET' });
    return Promise.resolve({ json: () => Promise.resolve(answer) });
};
sandbox.showToast = (text) => toasts.push(String(text));
sandbox.showDialog = () => Promise.resolve('go');
sandbox.escapeHtml = (value) => String(value === undefined || value === null ? '' : value);
sandbox.closeDockedPanels = () => {};
sandbox.I18n = { t: (key) => key };
/* The page's own prefix builder (index.html). A navigation must go through it: a bare
   /api/... asks the site root and 404s under a reverse-proxied subpath. */
sandbox.__cu = (url) => '/crawler' + url;
sandbox.AppSettings = {
    _values: {},
    preset: null,
    readOnly: false,
    refreshes: 0,
    applyToPanel() {},
    refreshAfterSave() {
        this.refreshes += 1;
    },
    applyPresetState(preset) {
        this.preset = preset && preset.active ? preset : null;
    },
    async pull() {},
};

const schema = {
    groups: [
        { id: 'pace', label: 'set.groupPace' },
        { id: 'safety', label: 'set.groupSafety' },
    ],
    settings: [
        {
            key: 'crawl_pace_scale',
            kind: 'float',
            default: 1.0,
            group: 'pace',
            label: 'set.crawlPaceScale',
            hint: 'set.crawlPaceScaleHint',
            minimum: 0.25,
            maximum: 10,
            choices: [],
            restart: false,
            portable: true,
        },
        {
            key: 'same_platform_queue',
            kind: 'bool',
            default: false,
            group: 'safety',
            label: 'set.sameQueue',
            hint: '',
            minimum: null,
            maximum: null,
            choices: [],
            restart: false,
            portable: true,
        },
    ],
    presets: { slow: { label: 'set.presetSlow', hint: 'set.presetSlowHint', keys: ['crawl_pace_scale'] } },
};

function settingsAnswer(overrides) {
    return {
        ok: true,
        schema,
        read_only: false,
        ...overrides,
    };
}

const source = fs.readFileSync(path.join(process.cwd(), 'backend', 'static', 'js', 'panels', 'settings-panel.js'), 'utf8');
vm.runInContext(source, sandbox);
const Panel = sandbox.SettingsPanel;

const out = {};

/* ── render from the schema ────────────────────────────────────────────── */
answer = settingsAnswer();
sandbox.AppSettings._values = { crawl_pace_scale: 1.0, same_platform_queue: false };
await Panel.refresh();
const form = sandbox.__byId('settings-panel-form');
const nav = sandbox.__byId('settings-panel-nav');
out.rendered = {
    groups: (nav.innerHTML.match(/settings-panel-nav|set\.group/g) || []).length,
    paceField: !!sandbox.__byId('sp-crawl_pace_scale'),
    queueField: !!(sandbox.__byId('settings-panel-form').innerHTML.indexOf('sp-same_platform_queue') >= 0),
    formHasDefault: form.innerHTML.indexOf('value="1"') >= 0,
};

/* ── a field edit is posted under its own key ──────────────────────────── */
const pace = sandbox.__byId('sp-crawl_pace_scale');
pace.value = '2.5';
Panel.fieldChanged(pace);
answer = { ok: true, settings: { crawl_pace_scale: 2.5, same_platform_queue: false }, warnings: [], preset: null };
await Panel.save();
const saveCall = posted.filter((c) => c.url === '/api/settings' && c.method === 'POST').pop();
out.save = { body: saveCall && saveCall.body, toast: toasts[toasts.length - 1] };
/* A save must re-ask the two boot-time catalogues the new values feed (new-node
   defaults, the CatBus engine list), or the canvas keeps describing the old config. */
out.save.refreshes = sandbox.AppSettings.refreshes;

/* ── reset a field to the declared default ─────────────────────────────── */
Panel.resetField('crawl_pace_scale');
out.reset = { value: sandbox.__byId('sp-crawl_pace_scale').value, draft: Panel.draft.crawl_pace_scale };

/* ── preset apply / restore hit the preset route ───────────────────────── */
posted.length = 0;
answer = { ok: true, settings: { crawl_pace_scale: 4.0 }, warnings: [], preset: { active: 'slow', customized: false } };
await Panel.applyPreset();
out.presetRefreshes = sandbox.AppSettings.refreshes;
await Panel.restorePreset();
out.preset = posted.filter((c) => c.url === '/api/settings/preset').map((c) => c.body.action);
out.presetRefreshesAfterRestore = sandbox.AppSettings.refreshes;

/* ── export carries the user's machine-path choice ─────────────────────── */
sandbox.__byId('settings-include-machine').checked = true;
sandbox.location = { href: '' };
Panel.exportSettings();
out.export = sandbox.location.href;

process.stdout.write(JSON.stringify(out));
