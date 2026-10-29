/* Main Application Entry */

/* Console i18n: every request carries the UI language as X-Lang, so the log
   lines the server streams into the console (crawl progress, LLM batches,
   errors) come back in the language being read. Patching fetch once covers
   every call site, including the ones added later. */
(function () {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
        let lang = 'zh';
        try {
            lang = (typeof I18n !== 'undefined' && I18n.lang) || document.body.dataset.lang || 'zh';
        } catch (e) { /* keep the default */ }
        try {
            const opts = Object.assign({}, init || {});
            opts.headers = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined) || undefined);
            if (!opts.headers.has('X-Lang')) opts.headers.set('X-Lang', lang);
            return nativeFetch(input, opts);
        } catch (e) {
            return nativeFetch(input, init);
        }
    };
})();

/* The words themselves are data: ``js/i18n/<domain>.js`` pushes {name, en, zh} onto one
 * registry ahead of this file, and the merge below is the only place that decides who wins.
 * A key claimed by two domains is refused at load rather than silently kept from whichever
 * file loaded last — the same accident as typing a key twice inside one object, just spread
 * over two files where no side-by-side diff would show it. */
function _mergeCatalogues(local) {
    const out = { en: { ...(local && local.en) }, zh: { ...(local && local.zh) } };
    const owner = new Map();
    for (const lang of ['en', 'zh']) {
        for (const key of Object.keys(out[lang])) owner.set(`${lang}\u0000${key}`, 'app.js');
    }
    for (const table of (globalThis.I18N_CATALOGUES || [])) {
        for (const lang of ['en', 'zh']) {
            for (const [key, value] of Object.entries(table[lang] || {})) {
                const who = `${lang}\u0000${key}`;
                if (owner.has(who)) {
                    throw new Error(
                        `i18n: ${key} is defined by both ${owner.get(who)} and ${table.name}`
                    );
                }
                owner.set(who, table.name);
                out[lang][key] = value;
            }
        }
    }
    return out;
}

/* I18n - Internationalization */
const I18n = {
    lang: 'en',
    dict: _mergeCatalogues(),
    /* Keys no dictionary defines, in the order they were first asked for. A
       silent fallback is exactly how a raw "nodeType.upload" reached the screen
       once: warn on the first miss (and keep the list available as
       I18n.missing()) so a gap can never hide again. */
    _missing: new Set(),

    t(key, vars) {
        const d = this.dict[this.lang] || this.dict.en;
        let text = d[key];
        if (text === undefined) {
            /* Show the other language before showing the raw key — a missing
               translation should still read as a sentence ("Upload File"), not as
               an identifier ("palette.upload"). */
            const other = this.dict[this.lang === 'zh' ? 'en' : 'zh'] || {};
            if (!this._missing.has(key)) {
                this._missing.add(key);
                console.warn('[i18n] missing ' + this.lang + ' string: ' + key);
            }
            text = other[key] !== undefined ? other[key] : key;
        }
        return vars ? I18n.fill(text, vars) : text;
    },

    /* Fill EVERY occurrence of each slot. `String.prototype.replace` with a string needle
       replaces the FIRST occurrence only, and the cookie-delete template names the platform
       twice — so `.replace('{platform}', …)` left a literal `{platform}` inside a Chinese
       sentence the user read (measured 2026-09-28). A call site that formats through here
       cannot half-fill a sentence again. */
    fill(text, vars) {
        let out = String(text);
        Object.keys(vars || {}).forEach(function (name) {
            out = out.split('{' + name + '}').join(String(vars[name]));
        });
        return out;
    },

    missing() {
        return Array.from(this._missing).sort();
    },
    apply() {
        this.lang = document.body.dataset.lang || 'en';
        /* The page is declared lang="zh-CN"; an English choice has to reach assistive
           technology too, or the reader keeps a Chinese voice for English words. */
        document.documentElement.lang = this.lang === 'en' ? 'en' : 'zh-CN';
        document.querySelectorAll('[data-i18n]').forEach(el => {
            el.textContent = this.t(el.dataset.i18n);
        });
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            el.title = this.t(el.dataset.i18nTitle);
        });
        /* A placeholder is the only place some inputs explain themselves (the
           Profile directory field is empty by design, and what empty means is the
           information), so it has to switch language with the rest of the panel. */
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            el.placeholder = this.t(el.dataset.i18nPlaceholder);
        });
        /* Menu labels and the open dropdown are rendered by TopMenu, not by
           data-i18n attributes, so they need an explicit refresh. */
        if (window.TopMenu) TopMenu.refresh();
        /* The studio bar re-hosts the embedded studio's nav, so its mirrored
           chips carry i18n labels too. */
        if (window.chartStudio) chartStudio.refreshMenus();
        /* Option text inside custom selects comes from the <option> nodes, so
           their trigger labels need re-reading once the locale changes. */
        if (window.CustomSelect) CustomSelect.refreshAll();
        /* The outline rows are built by JS (not data-i18n), so their type chips and
           labels must be re-rendered when the language flips. Guarded on typeof: this
           is `const Outline` in another file, which is NOT a window property. */
        if (typeof Outline !== 'undefined') Outline.render();
    },
};

/* Run-time switches that used to live as `.toggle-on` classes on the old flat
   menu bar. They are real state now, because the buttons only exist while a
   dropdown is open — reading them back from the DOM is no longer possible. */
const RunState = {
    parallel: true,
    headless: true,
    running: false,

    set(key, value) {
        this[key] = !!value;
        Settings.save();           /* persist */
        if (window.TopMenu) TopMenu.refresh();  /* keep the open panel truthful */
    },

    /* Flip a boolean switch and re-sync the flat bar. */
    toggle(key) {
        this[key] = !this[key];
        Settings.save();
        if (window.TopMenu) TopMenu.refresh();
    },

    /* Execute / Stop reflect a run in progress. */
    setRunning(on) {
        this.running = !!on;
        if (window.TopMenu) TopMenu.refresh();
    },
};

const Settings = {
    _key: 'crawler_settings',
    defaults: {
        bg: 'bg-grid',
        theme: 'auto',
        parallel: true,
        headless: true,
        menuPinned: true,
        zoom: 1,
        lang: 'zh',
        radius: 2,
        reusableAutoLayout: true,
    },
    save() {
        const data = {
            bg: Array.from(document.body.classList).find(c => c.startsWith('bg-')) || 'bg-grid',
            theme: document.documentElement.dataset.themeChoice || 'auto',
            parallel: RunState.parallel,
            headless: RunState.headless,
            menuPinned: document.getElementById('top-menu').classList.contains('pinned'),
            zoom: canvas.zoom,
            lang: document.body.dataset.lang || 'zh',
            radius: parseInt(getComputedStyle(document.documentElement).getPropertyValue('--radius'), 10) || 2,
            reusableAutoLayout: (function () {
                var box = document.getElementById('reusable-auto-layout');
                return box ? box.checked !== false : true;
            })(),
        };
        localStorage.setItem(this._key, JSON.stringify(data));
    },
    load() {
        /* The draft is user-editable and survives every upgrade, so a broken one is
           expected input rather than a crash: apply() runs from DOMContentLoaded, and
           an exception here stopped the rest of start-up — canvas.init() never ran,
           so the page stayed blank with nothing in the console the user could read.
           Same fallback LLMSettings.load() already gives its own draft. */
        const raw = localStorage.getItem(this._key);
        if (!raw) return Object.assign({}, this.defaults);
        try {
            const stored = JSON.parse(raw);
            if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return Object.assign({}, this.defaults);
            return Object.assign({}, this.defaults, stored);
        } catch (e) {
            return Object.assign({}, this.defaults);
        }
    },
    apply() {
        const s = this.load();
        /* Language — set first so I18n.t() uses the correct locale */
        document.body.dataset.lang = s.lang || 'zh';
        I18n.apply();
        /* Theme — the choice (auto/light/dark) is stored; auto follows the OS. The design
           system is no longer light-only: html[data-theme] drives the token override. */
        document.documentElement.dataset.themeChoice = s.theme || 'auto';
        applyTheme();
        /* Background */
        document.body.className = document.body.className.replace(/bg-\S+/g, '').trim();
        document.body.classList.add(s.bg);
        document.querySelectorAll('[data-bg]').forEach(el => {
            el.classList.toggle('active', el.dataset.bg === s.bg);
        });
        /* Run switches */
        RunState.parallel = s.parallel !== false;
        RunState.headless = s.headless !== false;
        /* Menu pin */
        document.getElementById('top-menu').classList.toggle('pinned', s.menuPinned);
        document.getElementById('pin-btn').classList.toggle('pinned', s.menuPinned);
        document.getElementById('pin-btn').setAttribute('aria-pressed', s.menuPinned ? 'true' : 'false');
        /* Corner radius — drive the single --radius token from saved value */
        const radius = (typeof s.radius === 'number') ? s.radius : 2;
        document.documentElement.style.setProperty('--radius', radius + 'px');
        const slider = document.getElementById('radius-slider');
        if (slider) slider.value = radius;
        const lbl = document.getElementById('radius-val');
        if (lbl) lbl.textContent = radius + 'px';
        /* Presentation preference, not product state: the Style menu says whether
           opening a reusable node also reflows the canvas once. */
        const reusableAuto = document.getElementById('reusable-auto-layout');
        if (reusableAuto) reusableAuto.checked = s.reusableAutoLayout !== false;
    },
};

/* ── Theme (auto / light / dark) ──────────────────────────────────────────
   The choice lives in Settings (localStorage) and on <html data-theme-choice>;
   `data-theme` is the RESOLVED value (auto collapses to the OS scheme) and is what the
   CSS token override keys on. Resolved on <html> (not body) so a single rule flips every
   surface that reads a var(); nothing sets body.theme-light any more, so the legacy
   light override can no longer win over a dark canvas. */
function resolveTheme(choice) {
    if (choice === 'dark') return 'dark';
    if (choice === 'light') return 'light';
    try {
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } catch (e) {
        return 'light';
    }
}

function applyTheme() {
    var html = document.documentElement;
    var choice = html.dataset.themeChoice || 'auto';
    html.dataset.themeChoice = choice;
    var resolved = resolveTheme(choice);
    html.dataset.theme = resolved;
    /* Native widgets (scrollbars, form controls) follow the same choice as the tokens. */
    html.style.colorScheme = resolved;
    document.querySelectorAll('.theme-opt').forEach(function (el) {
        el.classList.toggle('active', el.dataset.themeChoice === choice);
    });
}

function setTheme(choice) {
    if (choice !== 'auto' && choice !== 'light' && choice !== 'dark') return;
    document.documentElement.dataset.themeChoice = choice;
    applyTheme();
    Settings.save();
}

/* Filter the node library (left palette) by a query typed into #palette-search. Matching the
   data-type and the tag abbreviation as well as the label means a Chinese panel still answers
   an English fragment ("src"); a category header is hidden once every item under it is, so a
   search reads as a flat result list rather than a column of empty headings. Top-level (not
   inside the boot handler) so the popup/keyboard harnesses can drive it directly. */
function filterPalette(query) {
    var q = String(query == null ? '' : query).trim().toLowerCase();
    document.querySelectorAll('.palette-item').forEach(function (item) {
        var tagEl = item.querySelector('.palette-tag');
        var labelEl = item.querySelector('[data-i18n]');
        var hay = ((item.dataset && item.dataset.type) || '') + ' '
            + ((tagEl && tagEl.textContent) || '') + ' '
            + ((labelEl && labelEl.textContent) || '');
        item.style.display = (!q || hay.toLowerCase().indexOf(q) >= 0) ? '' : 'none';
    });
    var scope = document.getElementById('node-palette');
    if (!scope) return;
    /* A category owns the items until the next category; hide it when none remain visible. */
    var activeCat = null;
    var catAny = false;
    var flush = function () { if (activeCat) activeCat.style.display = catAny ? '' : 'none'; };
    scope.querySelectorAll('.palette-cat, .palette-item').forEach(function (node) {
        if (node.classList.contains('palette-cat')) {
            flush();
            activeCat = node;
            catAny = false;
        } else if (node.style.display !== 'none') {
            catAny = true;
        }
    });
    flush();
}

/* ── What this server can serve ─────────────────────────────────────────────
   The cloud flag is the SERVER's fact (`python app.py cloud`), read once from
   /api/config, and it decides which controls exist: a cloud host has no display to
   open a window on and no Ollama daemon on its own machine.

   Hiding is only the visible half. Every route behind one of these controls still
   answers a request — a saved workflow, an old tab, a hand-written POST — and each of
   those refuses by name server-side. A button that disappeared is not a permission. */
const CloudMode = {
    on: false,
    applied: false,

    /* Fed by the one /api/config read the page already makes at boot
       (``LLMSettings.loadDefaults``) — this module does not fetch, because a second
       request for the same payload would be a second answer to keep in sync. */
    set(flag) {
        this.on = !!flag;
        this.apply();
        /* The panel is filled from localStorage, which may name a transport this
           host cannot serve. Re-apply it from the truth instead of leaving a selected
           「本地 Ollama」 on a server that has none. */
        if (typeof LLMSettings !== 'undefined' && LLMSettings.applyToPanel) LLMSettings.applyToPanel();
        /* And say, once, what this kind of host keeps on its own disk. The flag landing
           is the moment the page knows it is standing in front of a stranger. */
        if (this.on && typeof PrivacyNotice !== 'undefined') PrivacyNotice.maybeShow();
    },

    apply() {
        document.documentElement.dataset.cloud = this.on ? '1' : '0';
        if (this.on) {
            /* The transport is taken OUT of the select, not merely styled away: a hidden
               <option> is still a value the element can be asked for (keyboard, a stale
               restore, an autofill), and this host cannot serve it. */
            var sel = document.getElementById('ai-provider');
            var local = sel && sel.querySelector('option[value="ollama"]');
            if (local && sel.removeChild) sel.removeChild(local);
        }
        this.applied = true;
    },
};

/* ── The first-entry notice on a cloud host ────────────────────────────────
   On a desktop the person IN FRONT of the page is the machine's owner. On a server they
   may be a stranger, and the two things they are about to hand over — a paste of cookies
   and an uploaded table — land in the SAME `data/` the operator's own runs use. So the
   page says, once, what is stored where.

   It rides `showDialog` rather than getting its own markup: that dialog already handles
   the backdrop click, Esc, and the button values this needs, and a second modal would be
   a second implementation of "how does this box close" to get wrong.

   The ack lives in localStorage — it is this BROWSER declining to be told again, not a
   server-side preference about a person the server cannot identify. */
const PrivacyNotice = {
    KEY: 'crawler_privacy_ack',
    shown: false,

    maybeShow() {
        if (this.shown || this.acked()) return;
        this.shown = true;
        showDialog({
            message: I18n.t('privacy.body'),
            buttons: [
                { label: I18n.t('privacy.never'), value: 'never' },
                { label: I18n.t('privacy.gotIt'), value: null, primary: true },
            ],
        }).then((answer) => {
            if (answer === 'never') {
                try {
                    localStorage.setItem(this.KEY, '1');
                } catch (e) {
                    /* A browser that refuses localStorage (private mode with storage
                       blocked) is asked again next visit. Saying so in a toast would be
                       noise; the notice reappearing is the honest answer. */
                }
            }
        });
    },

    acked() {
        try {
            return localStorage.getItem(this.KEY) === '1';
        } catch (e) {
            return false;
        }
    },

    /* Test seam and a genuine product need: 「我在本机重新看看这条说明」 is how a user
       unsends an ack they clicked in passing. */
    reset() {
        try {
            localStorage.removeItem(this.KEY);
        } catch (e) {
            /* Nothing to undo — an unreadable storage never held an ack. */
        }
        this.shown = false;
    },
};

/* ── AI (LLM) settings — transport, model, key, batching ────────────────────
   The two transports keep *separate* settings blocks. They used to share one
   `model` field, so a local Ollama run inherited whatever OpenRouter id was
   left in the box (e.g. `nex-agi/nex-n2.5-pro:free`) and the daemon answered
   "unexpected keyword argument" long before it ever got to complain about the
   model. Ollama needs a tag the daemon has pulled; OpenRouter needs a catalog
   id plus a key. Nothing is shared, so switching provider no longer carries a
   stale value across.

   Everything lives in localStorage; the key never leaves the browser except
   inside the execute / test request bodies. workflow.execute() sends
   LLMSettings.payload() alongside the workflow. */
const LLMSettings = {
    _key: 'crawler_llm',
    defaults: {
        provider: 'ollama',   // 'ollama' | 'openrouter'
        ollama: {
            model: '',        // a tag pulled locally (see 刷新 / list_ollama_models)
        },
        openrouter: {
            model: '',        // required, a :free model id
            api_key: '',      // localStorage only, never written server-side
        },
        batch_size: 10,       // rows between checkpoint saves
        max_chars: 600,       // per-row truncation — long texts burn tokens
        workers: 3,           // openrouter only
    },

    load() {
        let raw = {};
        try {
            raw = JSON.parse(localStorage.getItem(this._key) || '{}');
        } catch (e) {
            raw = {};
        }
        const s = Object.assign({}, this.defaults, raw);
        /* Object.assign above replaces the nested blocks wholesale, so a stored
           block from an older build would drop its newer defaults. Merge both. */
        s.ollama = Object.assign({}, this.defaults.ollama, raw.ollama || {});
        s.openrouter = Object.assign({}, this.defaults.openrouter, raw.openrouter || {});
        /* Migration from the pre-split shape: the single flat `model`/`api_key`
           pair only ever appeared while OpenRouter was selected, so that is
           where it belongs. save() drops the flat keys, making this one-shot. */
        if (!s.openrouter.model && raw.model) s.openrouter.model = raw.model;
        if (!s.openrouter.api_key && raw.api_key) s.openrouter.api_key = raw.api_key;
        /* Anything but a known transport normalises to the local one, so a
           hand-edited localStorage entry cannot desync the panel and the
           backend (which treats every non-OpenRouter provider as Ollama).

           On a cloud host the same normalization runs the other way, and for the same
           reason: there is no local daemon here, so a stored 「ollama」 — one that came
           from a desktop profile, or from before the flag was set — must not stay the
           active transport. The server refuses that transport by name anyway; this is
           what makes the panel ask for the key it actually needs. */
        if (typeof CloudMode !== 'undefined' && CloudMode.on) s.provider = 'openrouter';
        else if (s.provider !== 'openrouter') s.provider = 'ollama';
        return s;
    },

    save(patch) {
        const data = Object.assign(this.load(), patch || {});
        /* Written in the nested shape only: leaving the flat fields behind
           would let a stale OpenRouter id resurface after the user clears it. */
        delete data.model;
        delete data.api_key;
        localStorage.setItem(this._key, JSON.stringify(data));
        return data;
    },

    /* Patch one provider's block without touching the other's. */
    saveProvider(provider, patch) {
        const s = this.load();
        s[provider] = Object.assign({}, s[provider], patch);
        return this.save({ [provider]: s[provider] });
    },

    /* What the backend needs for a run: the *active* provider's model, never
       the other one's. The key is included — it travels with the request and
       is kept in memory server-side, never persisted. */
    payload() {
        const s = this.load();
        const active = s[s.provider] || {};
        return {
            provider: s.provider,
            model: active.model || '',
            api_key: s.provider === 'openrouter' ? active.api_key || '' : '',
            batch_size: s.batch_size,
            max_chars: s.max_chars,
            workers: s.workers,
        };
    },

    /* Mirror saved values into the panel inputs. */
    applyToPanel() {
        const s = this.load();
        const put = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.value = value;
        };
        put('ai-provider', s.provider);
        put('ai-ollama-model', s.ollama.model || '');
        put('ai-model', s.openrouter.model || '');
        put('ai-key', s.openrouter.api_key || '');
        put('ai-batch', s.batch_size);
        put('ai-maxchars', s.max_chars);
        this.toggleProviderRows(s.provider);
        this.renderOllamaHost();
    },

    toggleProviderRows(provider) {
        document.querySelectorAll('.ai-only-ollama').forEach(el => {
            el.style.display = provider === 'ollama' ? '' : 'none';
        });
        document.querySelectorAll('.ai-only-openrouter').forEach(el => {
            el.style.display = provider === 'openrouter' ? '' : 'none';
        });
    },

    /* The placeholder should show the model the server considers the local
       default (Config.OLLAMA_MODEL) rather than a hardcoded copy of it that
       silently drifts when the environment variable changes. */
    async loadDefaults() {
        if (this._defaultsPulled) return;
        this._defaultsPulled = true;
        try {
            const cfg = await (await fetch('/api/config')).json();
            /* The server states its own shape before anything else reads it: the AI panel
               is applied from localStorage right after this, and on a cloud host that
               stored value is allowed to name a transport with no daemon behind it. */
            if (typeof CloudMode !== 'undefined') CloudMode.set(cfg && cfg.cloud_mode);
            const input = document.getElementById('ai-ollama-model');
            if (input && cfg && cfg.ollama_model) input.placeholder = cfg.ollama_model;
        } catch (e) {
            /* Unreachable server: the built-in placeholder stands, and the flag stays
               "not cloud" — stripping controls on no answer is not this page's job. */
        }
    },

    /* The daemon address is server-side (设置 → Ollama 服务地址). Show what is
       actually configured: "connection refused" is unreadable otherwise. */
    renderOllamaHost() {
        const el = document.getElementById('ai-ollama-host');
        if (!el) return;
        const values = (window.AppSettings && AppSettings._values) || {};
        el.textContent = values.ollama_host || 'http://localhost:11434';
    },
};

/* menu.js loads before this file and guards with `window.LLMSettings` — a
   top-level const never lands on window, so without this export the panel
   opens showing every row instead of just the active provider's. */
window.LLMSettings = LLMSettings;

function onAIProviderChange(value) {
    const provider = value === 'openrouter' ? 'openrouter' : 'ollama';
    const s = LLMSettings.save({ provider });
    LLMSettings.toggleProviderRows(provider);
    if (provider === 'openrouter') {
        refreshAIModels();
    } else if (!s.ollama.model) {
        /* The tag must be one the daemon actually has, and listing it is cheap
           — so offer the list instead of making the user guess. */
        refreshOllamaModels();
    }
}

/* Ollama model — its own field, kept apart from the OpenRouter one. */
function onAIOllamaModelInput(value) {
    LLMSettings.saveProvider('ollama', { model: value.trim() });
}

function onAIModelInput(value) {
    LLMSettings.saveProvider('openrouter', { model: value.trim() });
}

function onAIKeyInput(value) {
    LLMSettings.saveProvider('openrouter', { api_key: value.trim() });
}

function onAINumberInput(field, value) {
    const limits = { batch_size: [1, 100], max_chars: [0, 20000] };
    const [lo, hi] = limits[field] || [0, 999999];
    let n = parseInt(value, 10);
    if (isNaN(n)) n = LLMSettings.load()[field];
    n = Math.max(lo, Math.min(hi, n));
    LLMSettings.save({ [field]: n });
}

/* Fill a model <select> from a list of ids. The ids come from a remote
   catalog / local daemon and go straight into innerHTML, so they are escaped
   rather than trusted. */
function fillModelSelect(sel, ids, current, placeholderKey) {
    sel.innerHTML = '<option value="">' + I18n.t(placeholderKey) + '</option>' +
        ids.map(id =>
            '<option value="' + escapeHtml(id) + '"' + (id === current ? ' selected' : '') + '>' +
            escapeHtml(id) + '</option>'
        ).join('');
}

async function refreshAIModels() {
    const sel = document.getElementById('ai-models');
    const btn = document.getElementById('ai-refresh-btn');
    if (!sel) return;
    if (btn) btn.disabled = true;
    try {
        const resp = await fetch('/api/llm/models');
        const result = await resp.json();
        if (result.ok && result.models.length) {
            fillModelSelect(sel, result.models, LLMSettings.load().openrouter.model, 'ai.pickModel');
            showToast(I18n.t('toast.aiModelsLoaded').replace('{n}', result.models.length));
        } else {
            showToast(I18n.t('toast.aiModelsFail') + ': ' + (result.error || ''));
        }
    } catch (e) {
        showToast(I18n.t('toast.aiModelsFail') + ': ' + e.message);
    } finally {
        if (btn) btn.disabled = false;
    }
}

/* Local daemon tags — a different endpoint from the OpenRouter catalog because
   the two providers no longer share a model setting. */
async function refreshOllamaModels() {
    const sel = document.getElementById('ai-ollama-models');
    const btn = document.getElementById('ai-ollama-refresh-btn');
    if (!sel) return;
    if (btn) btn.disabled = true;
    try {
        const resp = await fetch('/api/llm/ollama/models');
        const result = await resp.json();
        if (result.ok && result.models.length) {
            fillModelSelect(sel, result.models, LLMSettings.load().ollama.model, 'ai.pickModel');
            /* Remembered so merely reopening the panel does not re-hit the
               daemon; 刷新 always re-reads. */
            sel.dataset.loaded = '1';
            showToast(I18n.t('toast.aiModelsLoaded').replace('{n}', result.models.length));
        } else if (result.ok) {
            /* Daemon answered but has nothing pulled — say that, don't fail. */
            showToast(I18n.t('toast.ollamaNoModels'));
        } else {
            showToast(I18n.t('toast.aiModelsFail') + ': ' + (result.error || ''));
        }
    } catch (e) {
        showToast(I18n.t('toast.aiModelsFail') + ': ' + e.message);
    } finally {
        if (btn) btn.disabled = false;
    }
}

function onAIModelPick(id) {
    if (!id) return;
    LLMSettings.saveProvider('openrouter', { model: id });
    const input = document.getElementById('ai-model');
    if (input) input.value = id;
}

function onAIOllamaModelPick(id) {
    if (!id) return;
    LLMSettings.saveProvider('ollama', { model: id });
    const input = document.getElementById('ai-ollama-model');
    if (input) input.value = id;
}

/* ── Machine-local settings (driver path, window, timeouts, Ollama host) ────
   These used to be hardcoded in config.py / crawlers/base.py. They live in
   data/settings.json on the server, edited through the 设置 panel; the draft
   only reaches the server on 保存设置, and warnings (e.g. driver file not
   found) come back in the response. */
const AppSettings = {
    _inputMap: {
        driver_path: 'set-driver',
        browser_binary: 'set-binary',
        latex_binary: 'set-latex',
        catbus_cli: 'set-catbus-cli',
        catbus_node: 'set-catbus-node',
        window_size: 'set-window',
        page_load_timeout: 'set-pageload',
        element_timeout: 'set-elementwait',
        ollama_host: 'set-ollamahost',
        cookie_preflight_before_run: 'set-cookie-preflight',
        ask_overseas_network: 'set-ask-overseas-network',
        same_platform_queue: 'set-same-platform-queue',
        same_platform_stagger: 'set-same-platform-stagger',
        use_browser_profile: 'set-use-profile',
        browser_profile_dir: 'set-profile-dir',
        max_visible_browsers: 'set-max-visible-browsers',
        max_headless_browsers: 'set-max-headless-browsers',
        clear_console_before_run: 'set-clear-console',
        gentle_crawl: 'set-gentle-crawl',
        hongguo_player_path: 'set-hg-player',
        mitmdump_path: 'set-mitmdump',
        harvest_proxy_port: 'set-harvest-port',
        harvest_auto_install_ca: 'set-harvest-ca',
    },
    _values: null,
    _draft: {},
    _pulled: false,

    async pull(force) {
        if (this._pulled && !force) return;
        try {
            const resp = await fetch('/api/settings');
            const result = await resp.json();
            if (result.ok) {
                this._values = result.settings || {};
                this._draft = {};
                this._pulled = true;
                this.applyToPanel();
            }
        } catch (e) {
            /* Panel just keeps whatever it has; save() reports failures. */
        }
    },

    applyToPanel() {
        const v = this._values || {};
        Object.keys(this._inputMap).forEach((key) => {
            const el = document.getElementById(this._inputMap[key]);
            if (!el) return;
            // A checkbox answers to .checked; writing .value would silently
            // do nothing and the panel would show a stale box.
            if (el.type === 'checkbox') el.checked = !!v[key];
            else el.value = v[key] !== undefined && v[key] !== null ? v[key] : '';
        });
        /* The AI panel shows the Ollama address read-only, and it is fetched
           asynchronously — mirror it now that the values have arrived. */
        if (window.LLMSettings) LLMSettings.renderOllamaHost();
    },

    async save() {
        if (!Object.keys(this._draft).length) {
            showToast(I18n.t('toast.setNoChange'));
            return;
        }
        const btn = document.getElementById('set-save-btn');
        if (btn) btn.disabled = true;
        try {
            const resp = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: this._draft }),
            });
            const result = await resp.json();
            if (result.ok) {
                this._values = result.settings || {};
                this._draft = {};
                this.applyToPanel();
                const warns = result.warnings || [];
                if (warns.length) {
                    showToast(I18n.t('toast.setSavedWarn') + ' ' + warns.join('；'));
                } else {
                    showToast(I18n.t('toast.setSaved'));
                }
            } else {
                showToast(I18n.t('toast.setSaveFail') + ': ' + (result.error || ''));
            }
        } catch (e) {
            showToast(I18n.t('toast.setSaveFail') + ': ' + e.message);
        } finally {
            if (btn) btn.disabled = false;
        }
    },
};

function onSettingInput(field, value) {
    AppSettings._draft[field] = value;
}

/* Per-platform browser-profile state, so "启用" is not a blind switch: the panel
   shows which platforms the crawl matrix flags as needing one and whether that
   platform's directory has already been used (``imported``). A platform reading
   需要登录 is the case the user has to act on — turning the setting on does nothing
   by itself until they have logged into *that* profile once through the Cookie panel.

   Built with textContent rather than innerHTML: the row carries a platform name and
   a state sentence, and a list assembled by string concatenation is one future
   server-side string away from being markup. */
const BrowserProfiles = {
    data: null,
    _generation: 0,

    _row(entry) {
        /* Structured, and text-only on purpose: the block sits in a narrow menu
           where a single unbroken line scrolls it sideways, so the name, the
           建议 chip and the state are separate cells that wrap between them. */
        const line = document.createElement('div');
        line.className = 'profile-item';
        line.dataset.kind = entry.recommended ? 'suggested' : 'plain';
        const name = document.createElement('span');
        name.className = 'profile-name';
        name.textContent = I18n.t('platform.' + entry.platform);
        line.appendChild(name);
        if (entry.recommended) {
            const chip = document.createElement('span');
            chip.className = 'profile-chip';
            chip.textContent = I18n.t('set.profileSuggested');
            line.appendChild(chip);
        }
        const state = document.createElement('span');
        state.className = 'profile-state';
        state.textContent = this._stateOf(entry);
        line.appendChild(state);
        return line;
    },

    _noteRow(text, kind) {
        const line = document.createElement('div');
        line.className = 'profile-item';
        line.dataset.kind = kind;
        const state = document.createElement('span');
        state.className = 'profile-state';
        state.textContent = text;
        line.appendChild(state);
        return line;
    },

    _stateOf(entry) {
        if (!entry.enabled) return I18n.t('set.profileOff');
        if (entry.imported) return I18n.t('set.profileReady');
        if (entry.has_saved_cookie) return I18n.t('set.profileWillImport');
        return I18n.t('set.profileNeedsLogin');
    },

    _templateState(template) {
        if (!template.exists) return I18n.t('set.templateMissing');
        if (!template.pristine) return I18n.t('set.templateDirty');
        return I18n.t('set.templateReady');
    },

    async refresh() {
        const box = document.getElementById('profile-status');
        if (!box) return;
        /* Opening the panel while a read is still in flight used to append both
           answers to the same box (the harness caught it: 16 rows for 8 platforms).
           A generation stamp makes an older answer leave the table alone. */
        const generation = ++this._generation;
        try {
            const resp = await fetch('/api/browser/profiles');
            const result = await resp.json();
            this.data = result && Array.isArray(result.profiles) ? result : null;
        } catch (e) {
            this.data = null;
        }
        if (generation !== this._generation) return;
        /* Assigning textContent is the documented way to empty a node here: it
           replaces every descendant in a browser and in the DOM stub both, while a
           `while (box.firstChild)` loop stops dead in the stub (no firstChild) and
           would leave a re-render appending to the old rows. */
        box.textContent = '';
        /* An empty list is not "nothing to report": the endpoint answers one row per
           matrix platform, so no rows means the table broke, and a blank box would
           read as a clean bill of health. */
        if (!this.data || !this.data.profiles.length) {
            box.appendChild(this._noteRow(I18n.t('set.profileUnavailable'), 'unavailable'));
            return;
        }
        this.data.profiles.forEach(function (entry) {
            box.appendChild(BrowserProfiles._row(entry));
        });
        /* One line for the template, because it is the state this panel cannot be given
           any other way: the directory every NEW account is cloned from is made by the
           program, on the server, and nobody clicked anything to create it. A payload
           without the field says nothing — an older server that never answered the
           question is not evidence that the answer is 「缺失」. */
        if (this.data.enabled && this.data.template && typeof this.data.template.exists === 'boolean') {
            box.appendChild(BrowserProfiles._noteRow(BrowserProfiles._templateState(this.data.template), 'template'));
        }
    },
};

function renderBrowserProfiles() {
    return BrowserProfiles.refresh();
}

window.BrowserProfiles = BrowserProfiles;
window.renderBrowserProfiles = renderBrowserProfiles;

async function saveAppSettings() {
    await AppSettings.save();
}

/* Same window export as LLMSettings — menu.js's 设置 panel guard needs it. */
window.AppSettings = AppSettings;


async function testAIConnection() {
    const btn = document.getElementById('ai-test-btn');
    const s = LLMSettings.load();
    /* Per-provider prerequisites — the same rules the backend enforces before
       a run, so the panel never promises a run it would refuse. */
    if (s.provider === 'openrouter') {
        if (!s.openrouter.api_key) { showToast(I18n.t('toast.aiNeedKey')); return; }
        if (!s.openrouter.model) { showToast(I18n.t('toast.aiNeedModel')); return; }
    } else if (!s.ollama.model) {
        showToast(I18n.t('toast.aiNeedOllamaModel'));
        return;
    }
    if (btn) { btn.disabled = true; btn.textContent = I18n.t('ai.testing'); }
    try {
        const resp = await fetch('/api/llm/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(LLMSettings.payload()),
        });
        const result = await resp.json();
        if (result.ok) {
            showToast(I18n.t('toast.aiTestOk').replace('{ms}', result.latency_ms) + ' [' + result.provider + ']');
        } else {
            showToast(I18n.t('toast.aiTestFail') + ': ' + (result.error || ''));
        }
    } catch (e) {
        showToast(I18n.t('toast.aiTestFail') + ': ' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = I18n.t('ai.test'); }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    /* Each start-up step is allowed to fail on its own. This body used to run
       straight through, so ONE throwing module took every later step with it —
       a missing chart CDN blanked the Data Source panel's capability list, the
       dataset re-link, the autosave and the 断点续跑 banner at once, and nothing
       on screen said which part had failed. Settings.load already learned this
       lesson the hard way; now the whole boot does. */
    const _bootSteps = [];
    const boot = (name, fn) => {
        try {
            fn();
        } catch (e) {
            _bootSteps.push(`${name}: ${(e && e.message) || e}`);
            console.error(`startup step failed: ${name}`, e);
        }
    };
    boot('settings', () => Settings.apply());
    boot('menu', () => TopMenu.init());
    /* The catalogue is what the canvas validates restored nodes against and seeds new ones
       from; it answers asynchronously, so a boot failure here is named by node-types.js and the
       canvas falls back to its pinned table rather than refusing every draft. */
    boot('nodeTypes', () => NodeTypes.load());
    boot('canvas', () => canvas.init());
    // Restore which saved file this draft belongs to BEFORE anything reads runName()
    // (resume bar, dashboard rehydrate, exports) — a refresh/restart reopens the file,
    // and only 新建 starts a new one.
    boot('openFile', () => workflow.restoreOpenFile());
    // Then re-fetch that file's CONTENT from the server: the local draft is a snapshot and the file
    // may have been updated outside this browser, so entering must open the latest saved version,
    // not the stale view. A new (unnamed) canvas keeps its draft.
    boot('reloadOpenFile', () => workflow.reloadOpenFile());
    boot('stats', () => stats.init());
    /* Replace every OS-drawn candidate UI (select popups, datalist suggestions)
       with the themed equivalents. Runs last so it also catches anything the
       other modules rendered during init. */
    boot('customSelect', () => CustomSelect.init());

    /* The Data Source panel is generated from the backend's crawl matrix, so the
       browser has to have it before a source node can be configured. Fetched at
       start-up rather than on first open: the first settings panel should show a
       form, not a spinner, and a failure says so with a retry.
       Through boot(): these were the only two of ~16 start-up steps outside it, so a
       throw here (workflow.js failing to evaluate, say) skipped every step AFTER them
       — datasets, palette, outline, dirtyGuard, resumeBar, the console reconnect, the
       locks and the autosave — and the partial-boot message never printed either. */
    boot('capabilities', () => Capabilities.load());

    /* Registered fine-tuned models (the 网暴模型 etc.) are fetched the same way, so
       the bert-mode picker can name them instead of the user typing a path. */
    boot('bertModels', () => BertModels.load());

    /* Uploaded files are stored on the server, so the canvas restored from
       localStorage very likely still owns every file it referenced. Verify
       each one instead of clearing it — see dataNodes.reconcileDatasets. */
    boot('datasets', () => dataNodes.reconcileDatasets());
    /* Arm the edit-time diagnostics only now, on the real page boot: node/saveState
       changes then refresh badges, output columns and the cost line on a debounce. */
    boot('diagnostics', () => {
        if (typeof Diagnostics !== 'undefined') {
            Diagnostics._armed = true;
            Diagnostics.schedule();
        }
    });
    /* Sweep orphaned files (only ones no saved workflow points at go). */
    fetch('/api/data/clear', { method: 'POST' }).catch(() => { });

    /* Palette drag */
    boot('palette', () => {
        document.querySelectorAll('.palette-item').forEach(item => {
            item.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', item.dataset.type);
                e.dataTransfer.effectAllowed = 'copy';
            });
        });
        /* The panel boots expanded; label its toggle to say what the next click does. */
        var palToggle = document.querySelector('#node-palette .palette-toggle');
        if (palToggle) palToggle.title = I18n.t('palette.collapse');
        var palSearch = document.getElementById('palette-search');
        if (palSearch) {
            palSearch.placeholder = I18n.t('palette.searchPlaceholder');
            palSearch.addEventListener('input', function (e) {
                filterPalette(e && e.target ? e.target.value : palSearch.value);
            });
        }
    });

    /* Outline sidebar: a jump-to-node navigator. Its rows re-render from the model on
       every saveState, so init only has to restore the collapsed state and paint once. */
    boot('outline', () => Outline.init());

    /* Auto-save every 30 seconds */
    setInterval(() => {
        canvas.saveState();
    }, 30000);

    /* Warn on close/refresh while the canvas has unsaved work. The debounce autosave keeps
       an OPEN file fresh, but a never-named canvas or a save that could not reach the server
       still leaves `dirty` true. The handler logic is in workflow.js (harness-testable); this
       boot step only wires it — `workflow` is a top-level const, so it is named directly. */
    boot('dirtyGuard', () => workflow.installDirtyGuard());

    /* An interrupted run may be waiting from before this page opened. */
    boot('resumeBar', () => {
        if (typeof resumeBar !== 'undefined' && resumeBar) resumeBar.refresh();
    });
    /* A run may also be GOING, in which case this page's console is not a new console —
       it is the same run's log with a browser that reloaded in the middle of it. Nothing
       else starts the poll, so without this step the box stays empty for the rest of the
       crawl while the server keeps writing. `workflow` is a top-level const in
       workflow.js, so it is named directly: `window.workflow` could never be truthy. */
    boot('consoleReconnect', () => {
        if (typeof workflow !== 'undefined' && workflow) workflow.reconnectConsole();
    });
    boot('locks', () => {
        /* #182: fetch the lock set ONCE at startup, then repaint any docked panel that
           is already open so a locked row shows its lock immediately. Loading here (not
           in each panel refresh) keeps the per-refresh paths free of an extra request. */
        if (typeof Locks === 'undefined') return Promise.resolve();
        return Locks.load().then(function () {
            var open = function (mgr) {
                return mgr && mgr.panel && mgr.panel() && mgr.panel().classList.contains('open');
            };
            if (typeof exportsManager !== 'undefined' && open(exportsManager)) exportsManager.render();
            if (typeof runsManager !== 'undefined' && open(runsManager)) runsManager.render(runsManager._shown || []);
            if (typeof wfFiles !== 'undefined' && open(wfFiles) && wfFiles._last) wfFiles.render();
        });
    });
    if (_bootSteps.length) {
        showToast(I18n.t('boot.partial').replace('{steps}', _bootSteps.length));
    }
});

/* Background selection is handled by setBg() in workflow.js, which the menu
   delegates to — no separate listener needed here. */

/* ── Panel Drag & Resize Utilities ── */

const _DS = {}; // shared drag state

function makeDraggable(el, handleSelector) {
    const handle = typeof handleSelector === 'string'
        ? el.querySelector(handleSelector) : handleSelector;
    if (!handle) return;
    /* Pointer events, not mouse: one code path serves mouse, touch and pen. touch-action:none
       stops the browser claiming a finger drag as a page scroll before we see a pointermove. */
    handle.style.touchAction = 'none';

    handle.addEventListener('pointerdown', (e) => {
        if (e.target.closest('button, select, input, textarea')) return;
        e.preventDefault();

        /* Convert to floating FIRST (while transform is still readable)
           THEN add panel-dragging to freeze inline styles */
        convertToFloating(el);
        el.classList.add('panel-dragging');

        const rect = el.getBoundingClientRect();
        _DS.el = el;
        _DS.offX = e.clientX - rect.left;
        _DS.offY = e.clientY - rect.top;
        _DS.isDragging = true;
        _DS.handle = handle;
        handle.style.cursor = 'grabbing';
    });
}

document.addEventListener('pointermove', (e) => {
    if (!_DS.isDragging || !_DS.el) return;
    _DS.el.style.setProperty('left', (e.clientX - _DS.offX) + 'px', 'important');
    _DS.el.style.setProperty('top', (e.clientY - _DS.offY) + 'px', 'important');
});

document.addEventListener('pointerup', () => {
    if (_DS.isDragging && _DS.el) {
        _DS.el.classList.remove('panel-dragging');
        if (_DS.handle) _DS.handle.style.cursor = '';
    }
    _DS.isDragging = false;
    _DS.el = null;
    _DS.handle = null;
});

function convertToFloating(el) {
    /* Use getComputedStyle to detect positioning from CSS classes
       (el.style only sees inline styles, not class-based rules) */
    const cs = getComputedStyle(el);
    const hasRight = cs.right && cs.right !== 'auto' && parseFloat(cs.right) !== 0;
    const hasTransform = cs.transform && cs.transform !== 'none';

    if (hasRight || hasTransform) {
        const rect = el.getBoundingClientRect();
        el.style.setProperty('left', rect.left + 'px', 'important');
        el.style.setProperty('top', rect.top + 'px', 'important');
        el.style.right = 'auto';
        el.style.setProperty('transform', 'none', 'important');
    }
}

function makeResizable(el, opts) {
    opts = opts || {};
    const minW = opts.minW || 250;
    const minH = opts.minH || 120;
    const maxW = opts.maxW || window.innerWidth - 40;
    const maxH = opts.maxH || window.innerHeight - 40;
    const onResize = opts.onResize;

    let handle = el.querySelector('.resize-handle');
    if (!handle) {
        handle = document.createElement('div');
        handle.className = 'resize-handle';
        el.appendChild(handle);
    }

    /* A scrollable panel carries its absolutely-positioned handle away with the content:
       ``bottom: 0`` is the padding box's bottom, so scrolling up by N moves the grip up by N
       and past the frame it disappears. Cancelling the scroll keeps it in the visible corner
       (measured on #node-settings, whose form outgrows the panel). */
    const pinHandle = function () {
        handle.style.transform = 'translate(' + el.scrollLeft + 'px,' + el.scrollTop + 'px)';
    };
    if (!el.dataset._handlePinned) {
        el.dataset._handlePinned = '1';
        el.addEventListener('scroll', pinHandle, { passive: true });
        window.addEventListener('resize', pinHandle);
    }
    pinHandle();

    let rs = {};
    handle.style.touchAction = 'none'; /* a finger drag on the handle is ours, not the page's scroll */
    handle.addEventListener('pointerdown', (e) => {
        e.stopPropagation();
        e.preventDefault();
        convertToFloating(el);
        rs.el = el;
        rs.startX = e.clientX;
        rs.startY = e.clientY;
        rs.startW = el.offsetWidth;
        rs.startH = el.offsetHeight;
        rs.minW = minW; rs.minH = minH; rs.maxW = maxW; rs.maxH = maxH;
        window._rs = rs;
        rs.active = true;
    });

    /* One shared pointermove/pointerup for every resizable — mouse, touch and pen alike. */
    if (!window._resizeInit) {
        window._resizeInit = true;
        document.addEventListener('pointermove', (e) => {
            const r = window._rs;
            if (!r || !r.active) return;
            const newW = Math.max(r.minW, Math.min(r.maxW, r.startW + (e.clientX - r.startX)));
            const newH = Math.max(r.minH, Math.min(r.maxH, r.startH + (e.clientY - r.startY)));
            r.el.style.setProperty('width', newW + 'px', 'important');
            r.el.style.setProperty('height', newH + 'px', 'important');
            if (r.onResize) r.onResize(newW, newH);
        });
        document.addEventListener('pointerup', () => {
            const r = window._rs;
            if (r) r.active = false;
        });
    }
    rs.onResize = onResize;
    window._rs = rs;
}

/* ── Console pop-out / dock ── */

function toggleConsolePopout() {
    const panel = document.getElementById('console-panel');
    const btn = document.getElementById('btn-console-popout');
    const wasOpen = panel.classList.contains('open');

    if (panel.classList.contains('popout')) {
        /* Dock back */
        panel.classList.remove('popout');
        panel.classList.remove('panel-dragging');
        panel.style.left = '';
        panel.style.top = '';
        panel.style.width = '';
        panel.style.height = '';
        panel.style.transform = '';
        btn.textContent = I18n.t('console.popout');
        /* Restore open state */
        if (wasOpen) panel.classList.add('open');
    } else {
        /* Pop out: ensure open, then switch to floating */
        panel.classList.add('open');
        panel.classList.add('popout');
        /* Remove the docked bottom position, let CSS take over */
        btn.textContent = I18n.t('console.dock');
        /* Make draggable + resizable on first pop */
        if (!panel.dataset._popInit) {
            panel.dataset._popInit = '1';
            makeDraggable(panel, '.console-header');
            makeResizable(panel, { minW: 350, minH: 150, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
        }
        /* Add resize handle if not present */
        if (!panel.querySelector('.resize-handle')) {
            const rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }
    I18n.apply();
}

/* ── Console height resize (dock mode) ── */

(function initConsoleResize() {
    const handle = document.getElementById('console-resize-handle');
    if (!handle) return;
    let cs = {};

    handle.style.touchAction = 'none';
    handle.addEventListener('pointerdown', (e) => {
        const panel = document.getElementById('console-panel');
        if (panel.classList.contains('popout')) return;
        e.preventDefault();
        cs.panel = panel;
        cs.startY = e.clientY;
        cs.startH = panel.offsetHeight;
        cs.active = true;
        handle.classList.add('active');
    });

    document.addEventListener('pointermove', (e) => {
        if (!cs.active) return;
        const newH = Math.max(80, Math.min(window.innerHeight - 100, cs.startH + (cs.startY - e.clientY)));
        cs.panel.style.height = newH + 'px';
        cs.panel.classList.add('open'); /* keep open while resizing */
    });

    document.addEventListener('pointerup', () => {
        if (cs.active) {
            cs.active = false;
            handle.classList.remove('active');
        }
    });
})();

/* ─── Docked panel height resize ────────────────────────────────
   Four panels share this behaviour, so one function drives all of them.
   Measured from mousedown (not from a stored value) because each panel can be
   resized again after a drag, and the second drag has to start from where the
   first left off. */
function initDockResize(handleId, panelId) {
    const handle = document.getElementById(handleId);
    if (!handle) return;
    let cs = {};

    handle.style.touchAction = 'none';
    handle.addEventListener('pointerdown', (e) => {
        const panel = document.getElementById(panelId);
        if (!panel || !panel.classList.contains('open')) return;
        e.preventDefault();
        cs.panel = panel;
        cs.startY = e.clientY;
        cs.startH = panel.offsetHeight;
        cs.active = true;
        handle.classList.add('active');
    });

    document.addEventListener('pointermove', (e) => {
        if (!cs.active) return;
        const newH = Math.max(80, Math.min(window.innerHeight - 100, cs.startH + (cs.startY - e.clientY)));
        cs.panel.style.height = newH + 'px';
        cs.panel.classList.add('open'); /* keep open while resizing */
    });

    document.addEventListener('pointerup', () => {
        if (cs.active) {
            cs.active = false;
            handle.classList.remove('active');
        }
    });
}

initDockResize('runs-resize-handle', 'runs-panel');
initDockResize('exports-resize-handle', 'exports-panel');
initDockResize('dataset-resize-handle', 'dataset-panel');
initDockResize('workflows-resize-handle', 'workflows-panel');
/* The saved-logins dock is a dock like these: same bottom slot, same one-handle-to-resize,
   and ``closeDockedPanels`` already lists it, so opening it shuts the other five. */
initDockResize('cookies-resize-handle', 'cookies-panel');
/* The scheduled-task dock is a dock like these: same bottom slot, same one-handle-to-resize,
   and ``closeDockedPanels`` lists it, so opening it shuts the other six. */
initDockResize('schedules-resize-handle', 'schedules-panel');
/* The lexicon dock carries the same handle markup but was never given a handler, so the bar
   dragged with no effect — the eighth dock wired exactly like the other seven. */
initDockResize('lexicon-resize-handle', 'lexicon-panel');
/* The bibliometrics workspace is the ninth dock in the same slot, with the same handle. */
initDockResize('biblio-resize-handle', 'biblio-panel');

/* ── Cookie dialog: close on outside click ──
   The platform dropdown is a CustomSelect: its menu is rendered into <body>,
   OUTSIDE the dialog's DOM. Clicking a row there must count as an interaction
   with the dialog, not as an outside click — same two guards as the
   node-settings panel below. */

document.addEventListener('mousedown', (e) => {
    const dialog = document.getElementById('cookie-dialog');
    if (!dialog.classList.contains('open')) return;
    if (e.target.closest('#cookie-dialog')) return;
    if (e.target.closest('[data-i18n="btn.cookies"]')) return;
    /* A dropdown row belongs to the dialog's own control — never "outside". */
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    if (window.CustomSelect && CustomSelect.ownsPopup(e.target, dialog)) return;
    closeCookieDialog();
});

/* Close node-settings on outside click.
   Several things must not count as "outside" even though they live outside the
   panel's own DOM — otherwise the editor closes on the user mid-edit:
   · the node this panel edits (header, body, ports);
   · that node's right-click submenu, and the full-screen layers the panel can
     launch (chart studio, data preview);
   · a control's own popup (dropdown rows, suggestion candidates), which
     custom-select renders into <body> rather than into the panel. */
document.addEventListener('mousedown', (e) => {
    const panel = document.getElementById('node-settings');
    if (!panel.classList.contains('open')) return;
    if (e.target.closest('#node-settings')) return;
    if (e.target.closest('.node-action-btn, [data-action="ctxEdit"]')) return;
    /* A dropdown row is always an interaction with a control, never an "outside"
       click. The studio's picker renders its rows into <body>, so the overlay
       test below cannot see them — and without this the panel would close
       underneath while the user ticks sources in the studio. */
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    const nodeId = canvas._settingsNodeId;
    if (nodeId && e.target.closest('#' + nodeId)) return;
    if (nodeId && e.target.closest('#context-menu') && canvas._contextNode === nodeId) return;
    if (e.target.closest('#studio-overlay, #data-preview-panel')) return;
    if (window.CustomSelect && CustomSelect.ownsPopup(e.target, panel)) return;
    closeSettings();
});

/* Close the dashboard (看板) and Execution History (执行历史) popups on an
   outside click. They are floating windows, not modal overlays — while one
   is open the canvas stays usable, so the user expects it to be gone once
   they click back into the workspace. What must NOT count as "outside":
   · either panel itself (headers, drag/resize handles — and working with
     one popup may never discard the other; they are sized to sit side by side);
   · CustomSelect option menus — the panel's own <select>s render their menus
     into <body>, so a click there is an inside choice, not a click-away;
   · the modal dialogs (generic confirm, cookie capture) — the history panel's
     own button can raise one, and discarding the panel underneath while the
     answer is pending would strand the dialog over an empty canvas. */
document.addEventListener('mousedown', (e) => {
    if (!e.target || !e.target.closest) return;
    /* A click inside the board popup itself, the sibling history popup, or any overlay
       the user legitimately stacks on top of the board — the fullscreen chart, the data
       preview panel, the chart studio — must not dismiss the board. Those are top-level
       siblings, not children of #dashboard-panel, so without this list every click in one
       of them read as "outside" and the board vanished. (#node-settings stays OUTSIDE on
       purpose: opening a node's settings is meant to close the board.) */
    if (
        e.target.closest('#dashboard-panel, #history-panel, #chart-fullscreen-panel, #data-preview-panel, #studio-overlay')
    )
        return;
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    if (e.target.closest('#dialog-overlay, #cookie-dialog')) return;
    ['dashboard-panel', 'history-panel'].forEach((id) => {
        const panel = document.getElementById(id);
        if (!panel || !panel.classList.contains('open')) return;
        if (window.CustomSelect && CustomSelect.ownsPopup(e.target, panel)) return;
        panel.classList.remove('open');
    });
});

/* ── Init draggable panels on first open ── */

/* Patch openCookieDialog to init drag+resize on first open */
const _origOpenCookie = window.openCookieDialog;
window.openCookieDialog = function (...args) {
    /* EVERY argument is forwarded, as a list, on purpose. This wrapper exists to hang
       drag/resize off the first open, and it used to declare `function (platform)` and call
       `_origOpenCookie(platform)` — which silently dropped the SECOND argument the day the
       account landed there: the pre-run block and the saved-logins row both ask for
       「this platform, this account」, and in a browser the wrapper is the function they get.
       Measured in real Chrome (tests/integration/test_ui_layout.py): the panel opened on the
       right platform and the account box stayed on whatever the user had typed, so 「打开」
       looked half-dead. Restating the parameter list is exactly how this breaks again, so
       the list is passed through untouched. */
    _origOpenCookie(...args);
    const dialog = document.getElementById('cookie-dialog');
    if (dialog.classList.contains('open') && !dialog.dataset._uiInit) {
        dialog.dataset._uiInit = '1';
        makeDraggable(dialog, '.settings-header');
        /* Viewport-relative bounds, not fixed pixels: this dialog carries six
           platforms' worth of translated guidance plus two textareas, so a
           maxH of 500 clipped it to about a third of its content and the
           remainder could not be reached at any window size. */
        makeResizable(dialog, {
            minW: 320,
            minH: 260,
            maxW: Math.min(760, window.innerWidth - 40),
            maxH: window.innerHeight - 40,
        });
    }
};

/* Patch openSettings to init drag+resize on first open */
const _origOpenSettings = window.openSettings;
window.openSettings = function (nodeId) {
    var panel = document.getElementById('node-settings');
    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.settings-header');
        /* Same reasoning as the cookie dialog: the node panel grows with the node
           (a source node in comments mode, an analysis op with five fields), and a
           fixed 800px ceiling left fields unreachable on a tall window. */
        makeResizable(panel, {
            minW: 300,
            minH: 240,
            maxW: Math.min(680, window.innerWidth - 40),
            maxH: window.innerHeight - 40,
        });
    }
    _origOpenSettings(nodeId);
};

/* Init processes panel drag+resize */
(function initProcessesPanel() {
    const origToggle = window.toggleProcessesPanel;
    window.toggleProcessesPanel = function () {
        origToggle();
        var panel = document.getElementById('processes-panel');
        if (panel.classList.contains('open') && !panel.dataset._uiInit) {
            panel.dataset._uiInit = '1';
            makeDraggable(panel, '.console-header');
            makeResizable(panel, { minW: 300, minH: 150, maxW: 800, maxH: 500 });
        }
    };
})();
