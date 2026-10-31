/* Main Application Entry — the words, the theme, the cloud flag, the first-run notice, and the
   start-up sequence that boots them all. The two settings panels and the panel-window behaviour were
   cut out on 2026-10-29 into `llm-settings.js`, `app-settings.js` and `floating-panels.js`; they are
   loaded right after this file, so the page still evaluates one order and this boot body still runs
   after every module it names exists. */

/* The signed-in account, as the SERVER described it in /api/config. The token is the session's
   CSRF token: every mutating fetch echoes it in ``X-CSRF-Token`` (the patch below does that once,
   for call sites added later too). A password or a hash never arrives here — the server never
   sends one — and this object never stores a password typed by the user. */
const Auth = {
    token: '',
    user: null,
    mustChange: false,
    /* Resolves once /api/config has told the page whether this host has accounts. Mutating
       boot calls (the orphan sweep's POST, the resumable probe) used to run before that answer,
       so they carried no X-CSRF-Token and the server refused them — real Chrome showed two
       lonely 403s on every boot while every test client passed. */
    ready: null,
    _readyResolve: null,

    markReady() {
        if (!this._readyResolve) return;
        const resolve = this._readyResolve;
        this._readyResolve = null;
        resolve();
    },

    set(auth) {
        const data = auth || {};
        this.token = String(data.csrf_token || '');
        this.user = data.user && data.user.username ? data.user : null;
        this.mustChange = !!data.must_change_password;
        this.apply();
        this.markReady();
        if (this.mustChange && typeof Accounts !== 'undefined' && Accounts.openPasswordDialog) {
            Accounts.openPasswordDialog(true);
        }
    },

    apply() {
        const chip = document.getElementById('btn-account');
        if (!chip) return;
        chip.hidden = !this.user;
        chip.textContent = this.user ? this.user.username : '';
        if (this.user && typeof I18n !== 'undefined') {
            chip.title = I18n.t('accounts.signedInAs', { user: this.user.username });
        }
    },
};

Auth.ready = new Promise((resolve) => { Auth._readyResolve = resolve; });
/* A server that never answers /api/config must not park every write forever: after this bound
   the page sends anyway and the server has the final word. */
if (typeof setTimeout === 'function') {
    const authTimer = setTimeout(() => Auth.markReady(), 3000);
    if (authTimer && typeof authTimer.unref === 'function') authTimer.unref();
}

/* Console i18n: every request carries the UI language as X-Lang, so the log
   lines the server streams into the console (crawl progress, LLM batches,
   errors) come back in the language being read. Patching fetch once covers
   every call site, including the ones added later. A mutating request also
   echoes the session's CSRF token once the page has it. */
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
            const method = String(opts.method || (input && input.method) || 'GET').toUpperCase();
            const safeMethod = method === 'GET' || method === 'HEAD' || method === 'OPTIONS';
            const send = () => {
                if (!safeMethod && Auth.token && !opts.headers.has('X-CSRF-Token')) {
                    opts.headers.set('X-CSRF-Token', Auth.token);
                }
                return nativeFetch(input, opts).then(redirectIfAuthRequired).then(handlePasswordChangeRequired);
            };
            /* Wait for the account answer before the first write: a token that has not arrived
               yet is not "no token needed". Reads are never delayed. */
            if (!safeMethod && !Auth.token && !opts.headers.has('X-CSRF-Token')) {
                return Auth.ready.then(send);
            }
            return send();
        } catch (e) {
            return nativeFetch(input, init);
        }
    };
})();

/* A 401 that carries X-Auth-Required is an EXPIRED / MISSING LOGIN, not a node refusing
   something: the server marks its own refusals, so the page can tell them apart and send the
   user to the login page with the address it was on. Any other 401 is left to the caller. */
function redirectIfAuthRequired(response) {
    if (!response || response.status !== 401) return response;
    const marker = response.headers && response.headers.get && response.headers.get('X-Auth-Required');
    if (!marker || typeof location === 'undefined' || typeof location.assign !== 'function') return response;
    location.assign('/login?next=' + encodeURIComponent(location.pathname + location.search));
    return response;
}

/* A 403 that carries X-Password-Change-Required means the account is still working off an
   administrator-issued password. The server refuses everything but the change dialog; the page
   says so once instead of leaving every panel mysteriously empty. */
function handlePasswordChangeRequired(response) {
    if (!response || response.status !== 403) return response;
    const marker = response.headers && response.headers.get && response.headers.get('X-Password-Change-Required');
    if (!marker) return response;
    Auth.mustChange = true;
    if (typeof Accounts !== 'undefined' && Accounts.openPasswordDialog) Accounts.openPasswordDialog(true);
    return response;
}

/* End this browser's login (the top bar's 退出登录 entry). A POST, because a cross-site link or
   image must not be able to end someone's session; the server answers with a redirect to the
   login page either way, so the navigation below is the one thing left to do. */
function logout() {
    fetch('/logout', { method: 'POST' })
        .catch(() => { })
        .then(() => {
            if (typeof location !== 'undefined' && typeof location.assign === 'function') location.assign('/login');
        });
}

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
    /* Whether this host asks for a login. It rides the same /api/config answer as the cloud
       flag — the page must not ask a second question whose answer could disagree. */
    authRequired: false,

    /* Fed by the one /api/config read the page already makes at boot
       (``LLMSettings.loadDefaults``) — this module does not fetch, because a second
       request for the same payload would be a second answer to keep in sync. */
    set(flag, authRequired, auth) {
        this.on = !!flag;
        this.authRequired = !!authRequired;
        if (auth) Auth.set(auth);
        this.apply();
        /* The panel is filled from localStorage, which may name a transport this
           host cannot serve. Re-apply it from the truth instead of leaving a selected
           「本地 Ollama」 on a server that has none. */
        if (typeof LLMSettings !== 'undefined' && LLMSettings.applyToPanel) LLMSettings.applyToPanel();
        /* And say, once, what this kind of host keeps on its own disk. The flag landing
           is the moment the page knows it is standing in front of a stranger. Suppressed
           while a password change is owed: both dialogs share the ONE dialog shell, and the
           privacy notice used to overwrite the forced change form — the user dismissed it and
           every later API call stayed 403. The notice shows on the next load, after the change. */
        if (this.on && !Auth.mustChange && typeof PrivacyNotice !== 'undefined') PrivacyNotice.maybeShow();
    },

    apply() {
        document.documentElement.dataset.cloud = this.on ? '1' : '0';
        /* The way out of a login exists only where there is one; a desktop page with no
           session to end must not offer to end it. */
        const out = document.getElementById('btn-logout');
        if (out) out.hidden = !this.authRequired;
        Auth.apply();
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

