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
const LABELS = {
    'settingsPanel.effective': '≈ {seconds} s (baseline {base} s × {scale})',
    'settingsPanel.search': 'Search settings…',
    'settingsPanel.presetsTitle': 'Speed presets',
    'settingsPanel.presetWillChange': 'Will change {n} values: {list}',
    'settingsPanel.presetMore': ' …and {n} more',
    'settingsPanel.presetNoChange': 'Already matches the page',
    'settingsPanel.importDiff': 'Changes (now → after import):',
    'settingsPanel.importSummary': 'Import preview: {changed} change(s), {skipped} skipped.',
    'settingsPanel.presetRestoreHint': 'Restore puts back exactly the values the preset replaced.',
    'settingsPanel.resetGroup': 'Defaults',
    'settingsPanel.resetGroupHint': 'stage',
    'settingsPanel.resetAll': 'Restore all defaults',
    'settingsPanel.advanced': 'Advanced settings',
    'settingsPanel.outOfRange': 'allowed range: {min} – {max}',
    'settingsPanel.hasInvalid': '{n} fields need a valid value',
    'toast.setInvalid': 'These values need fixing before saving:',
    'set.crawlPaceScale': 'Pacing multiplier',
    'set.sameQueue': 'Same-platform queue',
    'set.presetSlow': 'Slow crawl preset',
    'set.presetSlowHint': 'slow',
};
sandbox.I18n = { t: (key) => (Object.prototype.hasOwnProperty.call(LABELS, key) ? LABELS[key] : key) };/* The page's own prefix builder (index.html). A navigation must go through it: a bare
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
            baseline: 1.2,
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
        {
            key: 'wall_proofs',
            kind: 'int',
            default: 5,
            group: 'safety',
            label: 'set.wallProofs',
            hint: '',
            minimum: 1,
            maximum: 20,
            choices: [],
            restart: false,
            portable: true,
            advanced: true,
        },
    ],
    presets: {
        slow: {
            label: 'set.presetSlow',
            hint: 'set.presetSlowHint',
            keys: ['crawl_pace_scale', 'same_platform_queue'],
            values: { crawl_pace_scale: 4.0, same_platform_queue: true },
        },
    },
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
    /* First confirmation the page turns a multiplier into seconds: ×1 at 1.2 s. */
    effective: (form.innerHTML.match(/settings-field-effective">([^<]*)</) || [])[1] || '',
    advancedHidden: form.innerHTML.indexOf('sp-wall_proofs') < 0,
};

/* ── advanced knobs stay out of the first look ─────────────────────────── */
Panel.showGroup('safety');
out.advancedHiddenInSafety = sandbox.__byId('settings-panel-form').innerHTML.indexOf('sp-wall_proofs') < 0;
Panel.setAdvanced(true);
out.advancedShown = sandbox.__byId('settings-panel-form').innerHTML.indexOf('sp-wall_proofs') >= 0;
Panel.setAdvanced(false);
Panel.showGroup('pace');

/* ── a field edit is posted under its own key ──────────────────────────── */
const pace = sandbox.__byId('sp-crawl_pace_scale');
pace.value = '2.5';
Panel.fieldChanged(pace);
/* The effective line follows the number, not only the first render. */
const effectiveNode = sandbox.document.querySelector
    ? sandbox.document.querySelector('.settings-field-effective')
    : null;
out.effectiveAfterEdit = effectiveNode ? effectiveNode.textContent : '';
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

/* ── an out-of-range number is refused by name, before the POST ─────────── */
const invalid = sandbox.__byId('sp-crawl_pace_scale');
invalid.value = '99';
Panel.fieldChanged(invalid);
posted.length = 0;
const toastsBefore = toasts.length;
await Panel.save();
out.invalid = {
    posted: posted.length,
    toast: toasts[toasts.length - 1],
    marked: !!invalid.closest('.settings-field').classList.contains('settings-field-invalid'),
    raised: toasts.length > toastsBefore,
};
Panel.resetField('crawl_pace_scale');

/* ── reset a whole group stages defaults; Save applies them ─────────────── */
Panel.resetGroup('safety');
out.groupReset = {
    queue: Panel.draft.same_platform_queue,
    proofs: Panel.draft.wall_proofs,
    dirty: Object.keys(Panel.draft).length,
};
Panel.draft = {};

/* ── the preset card shows what applying it would change ───────────────── */
Panel.values = { crawl_pace_scale: 1.0, same_platform_queue: false };
await Panel.renderPresetState();
out.presetCard = sandbox.__byId('settings-preset-card').innerHTML;

/* ── preset apply / restore hit the preset route ───────────────────────── */
posted.length = 0;
answer = { ok: true, settings: { crawl_pace_scale: 4.0 }, warnings: [], preset: { active: 'slow', customized: false } };
await Panel.applyPreset();
out.presetRefreshes = sandbox.AppSettings.refreshes;
await Panel.restorePreset();
out.preset = posted.filter((c) => c.url === '/api/settings/preset').map((c) => c.body.action);
out.presetRefreshesAfterRestore = sandbox.AppSettings.refreshes;

/* ── the import preview is old → new, not a list of keys ───────────────── */
Panel.values = { crawl_pace_scale: 1.0, same_platform_queue: false };
out.importDiff = Panel._importPreviewText({
    ok: true,
    changed: ['crawl_pace_scale'],
    values: { crawl_pace_scale: 4.0 },
    skipped: [],
    warnings: [],
});

/* ── closing with staged edits asks first, and a discard clears them ─────── */
const panelEl = sandbox.__byId('settings-panel');
panelEl.classList.add('open');
const dialogs = [];
sandbox.showDialog = (opts) => {
    dialogs.push(opts && opts.message);
    return Promise.resolve('discard');
};
Panel.draft = { crawl_pace_scale: 2.5 };
Panel.close();
await new Promise((r) => setImmediate(r));
out.guard = {
    asked: dialogs.length,
    open: panelEl.classList.contains('open'),
    draft: Object.keys(Panel.draft).length,
};
sandbox.showDialog = () => Promise.resolve('go');

/* ── export carries the user's machine-path choice ─────────────────────── */
sandbox.__byId('settings-include-machine').checked = true;
sandbox.location = { href: '' };
Panel.exportSettings();
out.export = sandbox.location.href;

process.stdout.write(JSON.stringify(out));
