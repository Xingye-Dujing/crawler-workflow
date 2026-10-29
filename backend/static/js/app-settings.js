/* app-settings.js — machine-local settings and the browser-profile status row
 *
 * Split out of `app.js` on 2026-10-29 as its own banner sections, so every name here is still a
 * page global and inline `onclick="…"` handlers keep calling it by name. index.html loads it right
 * after `app.js`; `tests/frontend/splits.json` declares it a companion of that file, so a harness
 * naming one receives both.
 */
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
