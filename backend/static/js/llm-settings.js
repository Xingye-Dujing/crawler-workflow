/* llm-settings.js — the LLM transport settings: provider, model, key, batching, and the connection test
 *
 * Split out of `app.js` on 2026-10-29 as its own banner sections, so every name here is still a
 * page global and inline `onclick="…"` handlers keep calling it by name. index.html loads it right
 * after `app.js`; `tests/frontend/splits.json` declares it a companion of that file, so a harness
 * naming one receives both.
 */
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
            if (typeof CloudMode !== 'undefined') CloudMode.set(cfg && cfg.cloud_mode, cfg && cfg.auth_required);
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
