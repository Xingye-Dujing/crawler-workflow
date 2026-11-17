/* Browser-local AI preferences. The API key never leaves this object except inside a request body;
 * the server holds it for one call and never writes it to SQLite or a log. */
const AISettings = {
    /* Server-side keys the workspace respects; the browser never sends them as settings, but
       naming them here keeps the schema's browser-consumer audit honest. */
    SERVER_SETTINGS: ['ai_context_scope', 'ai_web_search_default', 'ai_safety_level'],
    _key: 'crawler_ai_workspace',
    defaults: {
        provider: 'deepseek',
        models: {},
        keys: {},
        thinking: true,
        /* A local qwen3.5 model THINKS by default, and a thought trace can double the time a
           batch call takes. Local turns therefore default to no thinking; the toolbar switch
           turns it on per browser. */
        thinkingLocal: false,
        search: true,
        skill: 'auto',
        scope: 'summary',
        width: 520,
        open: false,
        full: false,
        sessionsOpen: false,
        /* Pinned = "stay open": a press outside the dock must not close it. Off is the old
           behaviour (a click elsewhere gives the page back). */
        pinned: false,
        /* Local-only: every send must go to the local daemon; a paid provider is refused
           before a request leaves the page. */
        localOnly: false,
        /* The conversation the panel had open. Without it a reload opened a NEW empty chat and the
           previous turn looked deleted; only the session list still knew it existed. */
        conversation: '',
    },

    load() {
        let raw = {};
        try {
            raw = JSON.parse(localStorage.getItem(this._key) || '{}');
        } catch (e) {
            raw = {};
        }
        const settings = Object.assign({}, this.defaults, raw);
        settings.models = Object.assign({}, this.defaults.models, raw.models || {});
        settings.keys = Object.assign({}, this.defaults.keys, raw.keys || {});
        /* The pre-workspace panel stored one OpenRouter key/model under crawler_llm. Keep that
           credential useful after the upgrade without copying it into a second server store. */
        try {
            const legacy = JSON.parse(localStorage.getItem('crawler_llm') || '{}');
            if (legacy.openrouter && !settings.keys.openrouter && legacy.openrouter.api_key) {
                settings.keys.openrouter = legacy.openrouter.api_key;
            }
            if (legacy.openrouter && !settings.models.openrouter && legacy.openrouter.model) {
                settings.models.openrouter = legacy.openrouter.model;
            }
        } catch (e) {
            /* a broken legacy value is not a reason to lose the new settings */
        }
        /* No provider whitelist here: the server's catalog answers which providers exist
           (`_loadBootstrap` reconciles against `data.providers`). A raw value that is not a
           non-empty string is the only thing this can judge. */
        if (typeof settings.provider !== 'string' || !settings.provider.trim()) {
            settings.provider = this.defaults.provider;
        }
        return settings;
    },

    save(patch) {
        const data = Object.assign(this.load(), patch || {});
        try {
            localStorage.setItem(this._key, JSON.stringify(data));
        } catch (e) {
            /* storage denied: this session still works from the in-memory copy */
        }
        return data;
    },

    providerId(catalog) {
        const settings = this.load();
        if (catalog && catalog.length && !catalog.some((item) => item.id === settings.provider)) {
            return catalog[0].id;
        }
        return settings.provider;
    },

    modelFor(provider, catalog) {
        const settings = this.load();
        const chosen = settings.models[provider] || '';
        if (chosen) return chosen;
        const row = (catalog || []).find((item) => item.id === provider);
        return row && row.models && row.models.length ? row.models[0].id : '';
    },

    keyFor(provider) {
        return this.load().keys[provider] || '';
    },

    setProvider(provider) {
        return this.save({ provider });
    },

    setModel(provider, model) {
        const settings = this.load();
        settings.models[provider] = model;
        return this.save({ models: settings.models });
    },

    setKey(provider, key) {
        const settings = this.load();
        settings.keys[provider] = key;
        return this.save({ keys: settings.keys });
    },

    payload() {
        const settings = this.load();
        return {
            provider: settings.provider,
            model: settings.models[settings.provider] || '',
            api_key: settings.keys[settings.provider] || '',
            thinking: !!settings.thinking,
            web_search: !!settings.search,
            skill: settings.skill || 'auto',
            scope: settings.scope || 'summary',
        };
    },
};
window.AISettings = AISettings;
