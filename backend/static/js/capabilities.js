/* The crawl capability matrix, the machine verdict, and the registered model list.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-28) byte for byte. Nothing here renders: these are
 * the three fetches and the questions the rest of the page asks them (which platforms exist, which
 * engines a platform offers, which mode fields a mode needs, what this machine cannot run, which
 * fine-tuned models are registered). The panel that draws them stays in ``workflow.js``.
 *
 * Loaded after ``workflow.js`` and before ``app.js``: every reference is a call-time one.
 */

/* ─── Crawl capabilities: the backend's matrix, rendered rather than re-listed ───
   Which platforms exist, which of them take links instead of a keyword, and what
   each mode asks for belongs to the executor. The panel used to keep its own
   answer to those questions — a platform could be added in Python and stay
   missing here, or appear here while the server still refused it. One fetch now
   feeds one renderer, so the form is the matrix. Labels travel as catalogue keys
   because the payload carries no language: the canvas translates it. */
/* The words for each machine requirement a mode can ask for, keyed by the server's token.
   ``tests/unit/test_frontend_contract.py`` pins this object's keys against
   ``crawl_capabilities.REQUIREMENTS``: a token the server may send with no entry here would print as
   the empty string in a greyed-out option, which is the "silently looks available" failure in UI form. */
const CAPABILITY_REQUIREMENT_WORDS = {
    windows_desktop: 'cap.requiresWindowsDesktop',
};

const Capabilities = {
    data: null,
    error: '',
    loading: false,

    load() {
        /* One in-flight request, handed to whoever asks while it is running: a
           second caller that got `null` back would render the failure note for a
           list that was about to arrive, and a retry clicked twice would fire two
           fetches whose answers race. */
        if (this._pending) return this._pending;
        this.loading = true;
        var self = this;
        this._pending = fetch('/api/capabilities')
            .then(function (resp) {
                return resp.json();
            })
            .then(function (payload) {
                self.data = payload && Array.isArray(payload.platforms) && payload.platforms.length ? payload : null;
                self.error = self.data ? '' : 'malformed';
                if (self.data) Machine.apply(self.data);
                /* The data-source card is written from this payload, and the nodes a
                   draft restored on a cold page were drawn before it arrived. Redraw
                   them here rather than at each caller, so no entry point (startup,
                   the retry button, a later refresh) can forget it. `canvas` is a
                   top-level const in canvas.js — `window.canvas` would never exist. */
                if (self.data && typeof canvas !== 'undefined' && canvas && canvas.refreshSourceSummaries) {
                    canvas.refreshSourceSummaries();
                }
                /* The cost estimate reads the matrix's own per-mode defaults, so it is
                   only meaningful once they have loaded. */
                if (self.data && typeof Diagnostics !== 'undefined' && Diagnostics.schedule) Diagnostics.schedule();
                return self.data;
            })
            .catch(function (e) {
                self.data = null;
                self.error = (e && e.message) || String(e);
                return null;
            })
            .then(function (result) {
                self.loading = false;
                self._pending = null;
                return result;
            });
        return this._pending;
    },

    ready() {
        return !!this.data;
    },

    platforms() {
        return this.data ? this.data.platforms : [];
    },

    platform(id) {
        var list = this.platforms();
        for (var i = 0; i < list.length; i++) {
            if (list[i].platform === id) return list[i];
        }
        return null;
    },

    /* Every engine this platform offers, in the panel's order. The payload decides: a platform with
       no browser crawl has no Selenium entry, and a CatBus-only platform still carries its engine so
       the panel can say why nothing runs when the adapter is missing. */
    engines(id) {
        var entry = this.platform(id);
        return (entry && entry.engines) || [];
    },

    engine(id, key) {
        var engines = this.engines(id);
        for (var i = 0; i < engines.length; i++) {
            if (engines[i].key === key) return engines[i];
        }
        return null;
    },

    /* Which engine a node with no stored choice starts on: the browser where it exists, CatBus only
       where it is the platform's one engine. Mirrors ``crawl_capabilities.engine_default``. */
    defaultBackend(id) {
        var engines = this.engines(id);
        for (var i = 0; i < engines.length; i++) {
            if (engines[i].key === 'selenium' && engines[i].available !== false) return 'selenium';
        }
        return engines.length ? engines[0].key : 'selenium';
    },

    /* The functions one engine offers. Without an engine this is the union (old callers); with one,
       only the modes whose ``engines`` list names it — the platform's Selenium-only modes do not
       appear under CatBus and vice versa. */
    modes(id, backend) {
        var entry = this.platform(id);
        if (!entry) return [];
        var list = entry.modes || [];
        /* An older payload has no engine dimension at all: filtering by one would hide every mode
           from a panel that is otherwise readable, so the whole list stands. */
        if (!backend || !(entry.engines || []).length) return list;
        return list.filter(function (m) {
            return (m.engines || ['selenium']).indexOf(backend) >= 0;
        });
    },

    /* An unknown or missing mode key resolves to the engine's first RUNNABLE mode — the same fallback
       the backend applies, so the panel can never show a form the run would not use, and an old canvas
       opens the mode it will execute. Falling to a browser-only mode for a CatBus node would show a
       form whose handler the CatBus adapter does not have. */
    mode(id, key, backend) {
        var modes = this.modes(id, backend);
        for (var i = 0; i < modes.length; i++) {
            if (modes[i].key === key) return modes[i];
        }
        if (backend && backend !== 'selenium') {
            for (var j = 0; j < modes.length; j++) {
                if (this.cellRunnable(modes[j], backend)) return modes[j];
            }
        }
        return modes.length ? modes[0] : null;
    },

    cell(mode, backend) {
        return (mode && mode.cells && mode.cells[backend]) || null;
    },

    /* Whether one function × engine pair can run on this machine, from the server's derived answer.
       A mode with no ``cells`` map came from an older payload that never judged the question; an
       unjudged answer is not evidence of failure, so it stays runnable (the run refuses by name if
       it really cannot start). */
    cellRunnable(mode, backend) {
        if (!mode) return false;
        if (!backend || backend === 'selenium') return true;
        if (!mode.cells) return true;
        var cell = this.cell(mode, backend);
        return !!(cell && cell.runnable);
    },

    /* The sentence for why a function × engine pair cannot run, in the canvas's language. The
       adapter's own prose wins when it gave one; a catalogue key is the fallback, never a sentence
       invented here. */
    modeRefusal(id, mode, backend) {
        if (!mode) return '';
        if (!this.runnable(mode)) return this.requirementWord(mode);
        if (backend && backend !== 'selenium' && mode.cells) {
            var engine = this.engine(id, backend);
            if (engine && engine.available === false) {
                return I18n.t(engine.reasonKey || 'settings.backendProbeFailed');
            }
            var cell = this.cell(mode, backend);
            if (!cell || !cell.runnable) {
                return (cell && cell.reason) || I18n.t((cell && cell.reasonKey) || 'settings.backendNoCell');
            }
        }
        return '';
    },

    fields(id, key, backend) {
        var mode = this.mode(id, key, backend);
        if (!mode) return [];
        return mode.fields.concat((this.data && this.data.fileFields) || []);
    },

    needsSession(id, key) {
        /* Whether this crawl is a session crawl. With no answer from the matrix it
           says yes: a probe that is not run cannot block a run, but a crawl that
           quietly turns out to need a login costs the user a wasted crawl — so the
           unknown direction is "keep asking", matching `fields()` never guessing a
           shape. */
        if (!this.ready()) return true;
        var mode = this.mode(id, key);
        if (!mode) return true;
        return mode.needsSession !== false;
    },

    /* Whether THIS machine can run a mode, from the server's own verdict (``payload.machine``).

       Three answers, deliberately different: a mode with no requirement is runnable anywhere; a
       requirement the payload never judged (an older server, a partial response) is runnable rather than
       silently hidden — hiding a working feature on a missing byte is worse than a run that refuses by
       name; and a requirement the server judged false is NOT runnable, which is the case this exists for.
       The harvest node itself still refuses at run time; this only keeps the panel from offering a mode
       the machine cannot honour and keeps 执行 from paying for a start that is already decided. */
    runnable(mode) {
        if (!mode || !mode.requires) return true;
        var machine = this.data && this.data.machine;
        if (!machine) return true;
        return machine[mode.requires] !== false;
    },

    requirementWord(mode) {
        /* The words for what the mode asks of the machine, as a literal catalogue key per requirement —
           never a computed one, which is how a greyed option would end up reading `cap.requires.windows`. */
        if (!mode || !mode.requires) return '';
        return I18n.t(CAPABILITY_REQUIREMENT_WORDS[mode.requires] || '');
    },

    backendState(id, modeKey, value) {
        /* Whether THIS machine can crawl one cell with the named backend, from the server's own map.

           Three answers, deliberately the same shape as ``runnable``: the browser backend is always
           runnable (it is this app); a payload that never judged the question — an older server, a
           partial response — is runnable rather than greyed, because an option this side cannot read
           is not evidence that the crawl will fail, and the run refuses by name if it does; and a
           cell the adapter does not offer, or a machine it cannot start on, is greyed with the
           server's own reason key.

           Greyed-and-named rather than removed: a canvas that STORES this value has to show what it
           holds, or the panel would display option #0 while the button starts the other crawl. */
        if (String(value || '') !== 'catbus') return { runnable: true, wordKey: '' };
        if (!this.ready()) return { runnable: true, wordKey: '' };
        var catbus = (this.data.backends || {}).catbus;
        if (!catbus) return { runnable: true, wordKey: '' };
        if (!catbus.available) return { runnable: false, wordKey: catbus.panelKey || 'settings.backendProbeFailed' };
        var cell = (catbus.cells || {})[String(id || '') + '.' + String(modeKey || '')] || {};
        /* ``runnable`` is the server's derived answer, not a token list re-read here: which manifest
           states may be crawled is the adapter's fact, and a copy in JS is how the two drift apart. */
        if (cell.runnable) return { runnable: true, wordKey: '' };
        return { runnable: false, wordKey: 'settings.backendNoCell' };
    },

    backendAuth(id, modeKey) {
        /* Whether a CatBus crawl of this cell wants a login, per the adapter's own declaration.

           The Selenium matrix answers the same question for the browser (weibo's 热搜 is anonymous,
           微信 has no session to want), and the two answers are genuinely different facts about two
           different tools — so the gate asks the one belonging to the backend this node will use,
           rather than letting the browser's answer stand in for a crawl that reads no cookie. */
        if (!this.ready()) return true;
        var catbus = (this.data.backends || {}).catbus || {};
        var cell = (catbus.cells || {})[String(id || '') + '.' + String(modeKey || '')] || {};
        return String(cell.auth || 'required') === 'required';
    },

    defaults(id) {
        var out = {};
        if (!this.data) return out;
        /* The union of both engines' forms: switching the engine must not re-seed the node, and a
           CatBus-only field has to be at its declared default when the user picks CatBus. */
        var modes = this.modes(id);
        for (var i = 0; i < modes.length; i++) {
            var fields = modes[i].fields.concat(this.data.fileFields || []);
            for (var j = 0; j < fields.length; j++) {
                if (!(fields[j].key in out)) out[fields[j].key] = fields[j].default;
            }
        }
        if (!('backend' in out)) out.backend = this.defaultBackend(id);
        return out;
    },
};
window.Capabilities = Capabilities;

/* What this machine cannot do, written onto the document so CSS can take the desktop-only rows out of
   the settings panel instead of showing a Windows-only path setting on a Linux server.

   The verdict is the server's (``/api/capabilities`` → ``machine``) because only the process knows its
   operating system and whether it is a cloud host — the same rule 「the panel holds no second opinion」
   already applies to time, to cookie accounts and to a schedule's next fire. A missing verdict leaves
   the rows visible: hiding a setting on a byte that never arrived is how a panel loses a feature
   nobody asked it to drop. */
const Machine = {
    apply(payload) {
        var machine = payload && payload.machine;
        var windowsDesktop = !machine || machine.windows_desktop !== false;
        document.documentElement.dataset.winDesktop = windowsDesktop ? '1' : '0';
    },
};
window.Machine = Machine;

/* Registered fine-tuned models, fetched once at boot so the bert-mode picker can
   offer them by friendly NAME (「网暴模型」) instead of making the user type a path.
   Same shape as Capabilities: a cold page starts the fetch before any node is
   opened, so the first bert settings panel shows the list, not a spinner. The list
   is OPTIONAL — a node always accepts a raw path, and a missing or malformed
   registry (the backend returns an empty list, never an error) simply leaves the
   text input as the only way in. `load()` re-renders the open settings panel,
   because a node clicked in the sliver before the response arrives must not stay
   stuck without its picker. */
const BertModels = {
    data: null,
    load() {
        if (this._pending) return this._pending;
        var self = this;
        this._pending = fetch('/api/models')
            .then(function (resp) {
                return resp.json();
            })
            .then(function (payload) {
                self.data = payload && Array.isArray(payload.models) ? payload.models : [];
                /* `canvas` is a top-level const in canvas.js — window.canvas never
                   exists; `openSettings` is a top-level function in this file. */
                if (typeof canvas !== 'undefined' && canvas && canvas._settingsNodeId &&
                    typeof openSettings === 'function') {
                    openSettings(canvas._settingsNodeId);
                }
                return self.data;
            })
            .catch(function () {
                self.data = [];
                return self.data;
            })
            .then(function (result) {
                self._pending = null;
                return result;
            });
        return this._pending;
    },
    list() {
        return this.data || [];
    },
};
window.BertModels = BertModels;
