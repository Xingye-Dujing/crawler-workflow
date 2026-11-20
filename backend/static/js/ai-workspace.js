/* AI workspace: the right-side agent window.
 *
 * The shell is one object; sessions, the stream decoder, the safe renderer, the page-context
 * collector, provider settings and the studio are split into companions (tests/frontend/splits.json).
 * A turn is a transcript plus an agent trace; the composer sends a canonical request and every
 * provider is reduced to the same event names by the server.
 */
/* The host label keys are also spelled here so the i18n reachability gate sees the literal keys;
 * the server's `runtime.label_key` remains the value shown, this table only maps kind → key. */
const AI_RUNTIME_KEYS = {
    desktop: 'ai.runtime.desktop',
    local_web: 'ai.runtime.local_web',
    cloud: 'ai.runtime.cloud',
};

/* How long a turn may send NOTHING before the live line says so. A local model on a long context is
 * genuinely silent for tens of seconds while it thinks, and a line that never changes reads as a
 * dead stream — the reader then assumes the answer was cut. 15 s is long enough not to cry wolf on
 * an ordinary pause and short enough to answer "is it still alive?" before doubt sets in. */
const STALL_AFTER_MS = 15000;

const AIWorkspace = {
    _init: false,
    _open: false,
    _full: false,
    _sessionsOpen: false,
    _sending: false,
    /* The live turn's clock: when it opened, when the last byte arrived, and whether an ENDING event
       (done / question / paused / error / stop) was seen. A stream that closes without one was cut,
       and a cut has to say so — otherwise a half answer is indistinguishable from a finished one. */
    _turnStartedAt: 0,
    _lastEventAt: 0,
    _turnEnded: false,
    _turnClock: null,
    /* The conversation the OPEN turn belongs to; `''` on a new chat until its first `meta`. */
    _streamConversation: '',
    _mode: 'chat',
    _conversationId: '',
    _bootstrap: null,
    _provider: 'deepseek',
    _model: '',
    _skill: 'auto',
    _scope: 'summary',
    _messages: [],
    _current: null,
    _plan: [],
    _usage: null,
    _contextMeta: null,
    _attachments: [],
    /* Things named with `@` in this draft: datasets, export files, workflow files and files
       uploaded in an earlier conversation. Sent as ids; the server resolves them. */
    _refs: [],
    /* The "what will be sent" text while it is open; one preview, toggled by its own button. */
    _contextPreview: '',
    _refResults: [],
    _refIndex: 0,
    _refOpen: false,
    _refQuery: '',
    _refTimer: null,
    _uploading: false,
    _studioTab: 'skills',
    _editingSkill: null,
    _pythonScript: null,
    _abort: null,
    _renderTimer: null,
    /* Which disclosures the READER opened, keyed by `data-ai-detail`. A streaming repaint rebuilds
       the block stream; without this, every delta closed the thinking block or tool result the user
       had just opened. */
    _openDetails: new Set(),
    _balance: null,
    _convoUsage: null,
    _conversationModel: '',
    _dom: {},

    init() {
        if (this._init) return;
        this._init = true;
        const ids = {
            root: 'ai-workspace',
            resizer: 'ai-resizer',
            sessions: 'ai-sessions',
            chat: 'ai-chat',
            side: 'ai-side',
            input: 'ai-input',
            send: 'ai-send-btn',
            stop: 'ai-stop-btn',
            provider: 'ai-ws-provider',
            model: 'ai-ws-model',
            skill: 'ai-skill',
            thinking: 'ai-thinking-btn',
            search: 'ai-search-btn',
            context: 'ai-context-bar',
            title: 'ai-title',
            modelChip: 'ai-model-chip',
            sessionsBtn: 'ai-history-btn',
            fullBtn: 'ai-full-btn',
            attachments: 'ai-attachments',
            refs: 'ai-refs',
            refMenu: 'ai-ref-menu',
            cmdMenu: 'ai-cmd-menu',
            attachBtn: 'ai-attach-btn',
            workspaceBtn: 'ai-workspace-btn',
            folderDialog: 'ai-folder-dialog',
            jump: 'ai-jump',
            agentPlan: 'ai-agent-plan',
            agentBuild: 'ai-agent-build',
            pinBtn: 'ai-pin-btn',
        };
        for (const [key, id] of Object.entries(ids)) this._dom[key] = document.getElementById(id);
        const root = this._dom.root;
        if (!root) return;
        this._sessionsOpen = !!AISettings.load().sessionsOpen;
        this._pinned = !!AISettings.load().pinned;
        /* The session panel's own filters: a search narrows on the server, and the archived view is
           a separate list rather than a hidden section of the same one. */
        this._sessionQuery = '';
        this._showArchived = false;
        this._sessionSearchTimer = null;
        root.classList.toggle('sessions-open', this._sessionsOpen);
        this._renderPin();
        AISettings.save({ open: this._open });
        this._provider = AISettings.providerId(null);
        if (AISettings.load().localOnly) this._provider = 'ollama';
        this._model = AISettings.modelFor(this._provider, null);
        this._skill = AISettings.load().skill || 'auto';
        this._agentMode = AISettings.load().agentMode === 'plan' ? 'plan' : 'build';
        this._scope = AISettings.load().scope || 'summary';
        if (this._dom.sessionsBtn) {
            this._dom.sessionsBtn.setAttribute('aria-expanded', this._sessionsOpen ? 'true' : 'false');
            this._dom.sessionsBtn.classList.toggle('active', this._sessionsOpen);
        }
        if (this._dom.input) {
            this._dom.input.addEventListener('input', () => {
                this._onRefInput();
                this._onCmdInput();
                this._autoGrow();
            });
            this._dom.input.addEventListener('keydown', (event) => {
                /* `nativeEvent` is a jQuery field; a DOM KeyboardEvent has none, so the old guard
                   threw on EVERY keypress in the composer (uncaught TypeError) and Enter never
                   sent. An IME's composing Enter is `isComposing` (or keyCode 229 on older
                   browsers) — that is the one this must not eat. */
                const composing = event.isComposing === true || event.keyCode === 229;
                if (this._cmdOpen && this._onCmdKey(event, composing)) return;
                if (this._refOpen && this._onRefKey(event, composing)) return;
                if (event.key === 'Escape' && this._sending) {
                    event.preventDefault();
                    this.stop();
                    return;
                }
                if (event.key === 'Enter' && !event.shiftKey && !composing) {
                    event.preventDefault();
                    this.send();
                }
            });
            /* A screenshot pasted into the composer becomes an attachment; pasted TEXT keeps its
               normal behavior, because only clipboard file items are intercepted. */
            this._dom.input.addEventListener('paste', (event) => {
                const items = event.clipboardData && event.clipboardData.items;
                if (!items) return;
                const files = [];
                /* DataTransferItemList is index-based, not iterable in older engines. */
                for (let index = 0; index < items.length; index += 1) {
                    const item = items[index];
                    if (!item || item.kind !== 'file') continue;
                    const file = item.getAsFile();
                    if (file) files.push(file);
                }
                if (!files.length) return;
                event.preventDefault();
                this._uploadFiles(files);
            });
        }
        if (this._dom.root) {
            /* Delegated from the dock, not from the transcript: sessions, the side panel and the
               context bar are siblings of #ai-chat, so a listener on the chat could never see them
               (switching conversations, refreshing context and stopping a monitor were inert). */
            this._dom.root.addEventListener('click', (event) => this._onClick(event));
            this._dom.root.addEventListener('change', (event) => this._onChange(event));
            this._bindAttachDrop(this._dom.root);
            /* `toggle` does not bubble, but the CAPTURE phase still passes through this element —
               so one listener records every disclosure the reader opens or closes. */
            this._dom.root.addEventListener(
                'toggle',
                (event) => {
                    const el = event && event.target;
                    const key = el && el.getAttribute ? String(el.getAttribute('data-ai-detail') || '') : '';
                    if (!key) return;
                    if (el.open) this._openDetails.add(key);
                    else this._openDetails.delete(key);
                },
                true
            );
            if (this._dom.chat) this._dom.chat.addEventListener('scroll', () => this._onChatScroll());
            /* An answer box takes `@` too: its textarea announces its own key/input events, and the
               menu must open for THAT box (see `_onRefInput`). */
            this._dom.root.addEventListener('input', (event) => {
                const target = event.target;
                if (target && target.hasAttribute && target.hasAttribute('data-ai-custom')) this._onRefInput(event);
                /* Typing in the session search asks the server, not the 80-row page in memory, but a
                   request per keystroke would reorder the list under the caret for nothing. */
                if (target && target.hasAttribute && target.hasAttribute('data-ai-session-search')) {
                    this._sessionQuery = String(target.value || '');
                    if (this._sessionSearchTimer) clearTimeout(this._sessionSearchTimer);
                    this._sessionSearchTimer = setTimeout(() => this._refreshConversations(), 250);
                }
            });
            this._dom.root.addEventListener('keydown', (event) => {
                const target = event.target;
                if (!target || !target.matches || !target.matches('textarea[data-ai-custom]')) return;
                const composing = event.isComposing === true || event.keyCode === 229;
                if (this._refOpen && this._onRefKey(event, composing)) return;
                if (event.key === 'Enter' && !event.shiftKey && !composing) {
                    event.preventDefault();
                    this._answerCustom(target.getAttribute('data-ai-custom'), target.value);
                }
            });
        }
        this._bindDock();
        this._bindColumns();
        this._renderWelcome();
        this._renderComposer();
        this._syncComposerHeight();
    },

    restore() {
        const settings = AISettings.load();
        if (settings.open) this.open({ silent: true });
        /* Monitors are page-level: a run can finish while the dock is closed, and the delivery must
           still reach the account that armed it. The poller never calls a provider without a key. */
        if (typeof AIWatch !== 'undefined') AIWatch.start();
    },

    _applyWidthClass(width) {
        if (!this._dom.root) return;
        this._dom.root.classList.toggle('narrow', !this._full && width < 480);
        this._dom.root.classList.toggle('tiny', !this._full && width < 390);
    },

    /* The two sidebars are draggable, each within a range that keeps its content readable. The
       width lives in a CSS variable so the grid follows the pointer without a repaint rule, and
       it is remembered per browser like the panel's own width. */
    _bindColumns() {
        const root = this._dom.root;
        if (!root) return;
        const saved = AISettings.load();
        let sessions = Math.max(150, Math.min(360, Number(saved.sessionsWidth) || 190));
        let side = Math.max(200, Math.min(440, Number(saved.sideWidth) || 260));
        const apply = () => {
            root.style.setProperty('--ai-sessions-w', sessions + 'px');
            root.style.setProperty('--ai-side-w', side + 'px');
        };
        apply();
        Array.from(root.querySelectorAll('[data-ai-resize]')).forEach((grip) => {
            grip.addEventListener('pointerdown', (event) => {
                event.preventDefault();
                const kind = String(grip.getAttribute('data-ai-resize') || '');
                const startX = event.clientX;
                const start = kind === 'sessions' ? sessions : side;
                const move = (moveEvent) => {
                    if (kind === 'sessions') {
                        sessions = Math.max(150, Math.min(360, start + (moveEvent.clientX - startX)));
                    } else {
                        side = Math.max(200, Math.min(440, start + (startX - moveEvent.clientX)));
                    }
                    apply();
                };
                const up = () => {
                    AISettings.save({ sessionsWidth: sessions, sideWidth: side });
                    document.removeEventListener('pointermove', move);
                    document.removeEventListener('pointerup', up);
                };
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', up);
            });
        });
    },

    _bindDock() {
        const root = this._dom.root;
        if (!root) return;
        const width = Math.max(360, Math.min(900, Number(AISettings.load().width) || 520));
        root.style.setProperty('--ai-width', width + 'px');
        this._applyWidthClass(width);
        if (this._dom.resizer) {
            let dragging = false;
            let startX = 0;
            let startWidth = width;
            const applyWidth = (next) => {
                root.style.setProperty('--ai-width', next + 'px');
                this._applyWidthClass(next);
                /* The separator is a focusable window-splitter: its value has to follow the width,
                   or a screen reader keeps announcing the width the page opened with. */
                this._dom.resizer.setAttribute('aria-valuenow', String(next));
            };
            applyWidth(width);
            const move = (event) => {
                if (!dragging) return;
                applyWidth(Math.max(360, Math.min(900, startWidth + (startX - event.clientX))));
            };
            const up = () => {
                if (!dragging) return;
                dragging = false;
                const value = parseInt(root.style.getPropertyValue('--ai-width'), 10) || width;
                AISettings.save({ width: value });
                this._applyWidthClass(value);
                document.removeEventListener('pointermove', move);
                document.removeEventListener('pointerup', up);
            };
            this._dom.resizer.addEventListener('pointerdown', (event) => {
                dragging = true;
                startX = event.clientX;
                startWidth = parseInt(root.style.getPropertyValue('--ai-width'), 10) || width;
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', up);
            });
            this._dom.resizer.addEventListener('keydown', (event) => {
                if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
                event.preventDefault();
                const current = parseInt(root.style.getPropertyValue('--ai-width'), 10) || width;
                const next = Math.max(360, Math.min(900, current + (event.key === 'ArrowLeft' ? 20 : -20)));
                applyWidth(next);
                AISettings.save({ width: next });
            });
        }
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && this._full) this.toggleFull();
        });
        /* The workspace is a side dock, so a press anywhere else gives the page back. Registered
           once, in the CAPTURE phase and on `pointerdown`: the click that opened the panel starts
           on its own button (excluded below), and a drag that begins inside and ends outside must
           not read as "outside" — a `click` listener would see exactly that. */
        document.addEventListener('pointerdown', (event) => this._onOutsidePress(event), true);
        /* A click needs mousedown and mouseup on the SAME element. While a turn streams, the block
           stream is rebuilt whenever it changes (~90 ms), so a press that straddled a repaint never
           became a click — "点击展开没有反应". Repainting waits for the button to come back up. */
        document.addEventListener(
            'pointerdown',
            () => {
                this._pointerDown = true;
            },
            true
        );
        document.addEventListener(
            'pointerup',
            () => {
                this._pointerDown = false;
                if (this._current && this._current._pendingPaint) {
                    this._current._pendingPaint = false;
                    this._paintAssistant();
                }
            },
            true
        );
    },

    /* True when a press lands outside every surface this panel owns. */
    _onOutsidePress(event) {
        if (!this._open || !this._dom.root) return;
        /* Pinned: the panel stays until its own × says otherwise. This is the switch that makes
           “click elsewhere” safe while a turn is running or a file is being chosen. */
        if (this._pinned) return;
        const target = event && event.target;
        if (!target || typeof target.closest !== 'function') return;
        if (this._dom.root.contains(target)) return;
        /* A CustomSelect/CustomCand popup is painted into <body>, so it is "outside" by DOM and
           "inside" to the user — the guard the floating panels already use. */
        if (typeof CustomSelect !== 'undefined' && CustomSelect.ownsPopup(target, this._dom.root)) return;
        /* Its own toggle closes it; doing both would close and immediately reopen. */
        if (target.closest('#btn-ai-workspace')) return;
        /* A dialog sits ON TOP of the page: answering one is not a request to close the panel. */
        if (target.closest('#dialog-overlay, #dialog-box')) return;
        this.close();
    },

    toggle() {
        if (this._open) this.close();
        else this.open();
    },

    /* The pin: ON = the dock ignores outside presses; OFF = the old behaviour. State lives in the
       browser's settings, so the choice survives a reload. */
    togglePin() {
        this._pinned = !this._pinned;
        AISettings.save({ pinned: this._pinned });
        this._renderPin();
        return this._pinned;
    },

    _renderPin() {
        const button = this._dom.pinBtn;
        if (!button) return;
        button.setAttribute('aria-pressed', this._pinned ? 'true' : 'false');
        button.classList.toggle('active', !!this._pinned);
        const label = I18n.t(this._pinned ? 'ai.pinOn' : 'ai.pinOff');
        button.setAttribute('title', label);
        button.setAttribute('aria-label', label);
        if (this._dom.root) this._dom.root.classList.toggle('pinned', !!this._pinned);
    },

    open(opts) {
        this.init();
        const root = this._dom.root;
        if (!root) return;
        this._open = true;
        root.hidden = false;
        root.classList.add('open');
        document.body.classList.add('ai-open');
        AISettings.save({ open: true });
        if (opts && opts.skill) this._skill = opts.skill;
        if (opts && opts.prompt) this._dom.input.value = opts.prompt;
        if (opts && opts.context) AIContext.setManual(opts.context);
        this._restoreConversation();
        this._loadBootstrap().then(() => {
            this._renderComposer();
            this._renderContextBar();
            /* A local daemon's real models are a live fact: the bootstrap row carries one static
               name, so the picker would offer a model the user may not even have. One silent read
               replaces it — no toast, and a daemon that is down keeps the static list. */
            this._refreshLocalModels();
            /* Closing the dock must not end the turn: the fetch is still streaming while the panel
               is hidden, and re-rendering the stored transcript would throw that live turn away and
               leave only the deltas that arrive afterwards. Keep the DOM the stream is painting. */
            if (this._conversationId && !this._sending) this.selectConversation(this._conversationId);
            else if (!this._conversationId) this._renderWelcome();
            this._loadSpend();
            if (opts && opts.prompt && this._dom.input) this._dom.input.focus();
        });
    },

    async _refreshLocalModels() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        if (!provider || !provider.local_only || provider.requires_key) return;
        try {
            const response = await fetch('/api/ai/providers/' + encodeURIComponent(this._provider) + '/models');
            const data = await response.json();
            const models = Array.isArray(data.models) ? data.models : [];
            if (!data.ok || !models.length) return;
            provider.models = models.map((item) => ({
                id: item.id,
                label: item.label || item.id,
                capabilities: provider.capabilities || [],
            }));
            /* A stored choice is KEPT while the daemon still has that model; an id the daemon no
               longer serves falls back to its first model, because a <select> whose value is not
               in its options shows blank and the next send would name a model that is gone. */
            const stored = AISettings.modelFor(this._provider, this._bootstrap.providers);
            const known = provider.models.some((row) => row.id === stored);
            this._model = known ? stored : provider.models[0].id;
            this._renderModelOptions();
            this._renderToggles();
        } catch (error) {
            /* The daemon may not be running: the static list stays, and sending says so. */
        }
    },

    close() {
        this._open = false;
        AISettings.save({ open: false });
        if (this._dom.root) {
            this._dom.root.classList.remove('open');
            this._dom.root.hidden = true;
        }
        document.body.classList.remove('ai-open');
        this._mode = 'chat';
    },

    toggleFull() {
        this._full = !this._full;
        this._dom.root.classList.toggle('full', this._full);
        document.body.classList.toggle('ai-focus', this._full);
        AISettings.save({ full: this._full });
        const width = parseInt(this._dom.root.style.getPropertyValue('--ai-width'), 10) || 520;
        this._applyWidthClass(width);
        if (this._dom.fullBtn) this._dom.fullBtn.setAttribute('aria-pressed', this._full ? 'true' : 'false');
    },

    toggleSessions() {
        this._sessionsOpen = !this._sessionsOpen;
        this._dom.root.classList.toggle('sessions-open', this._sessionsOpen);
        if (this._dom.sessionsBtn) {
            this._dom.sessionsBtn.classList.toggle('active', this._sessionsOpen);
            this._dom.sessionsBtn.setAttribute('aria-expanded', this._sessionsOpen ? 'true' : 'false');
        }
        AISettings.save({ sessionsOpen: this._sessionsOpen });
        this._renderSessions();
    },

    async _loadBootstrap() {
        const settings = AISettings.load();
        const provider = this._provider || settings.provider;
        const model = this._model || AISettings.modelFor(provider, null);
        /* Switching provider/model calls this again while the previous answer is still in flight.
           Without a sequence, the OLDER answer landed last and reset `_provider`/`_model` to what
           the user had just moved away from — the chip said one model while the request, and the
           key check, used another. Only the newest call may write the state. */
        this._bootstrapSeq = (this._bootstrapSeq || 0) + 1;
        const seq = this._bootstrapSeq;
        try {
            const response = await fetch('/api/ai/bootstrap?provider=' + encodeURIComponent(provider) + '&model=' + encodeURIComponent(model));
            const data = await response.json();
            if (seq !== this._bootstrapSeq) return;
            this._bootstrap = data;
            const ids = (data.providers || []).map((item) => item.id);
            this._provider = ids.includes(provider) ? provider : (ids[0] || 'deepseek');
            this._model = AISettings.modelFor(this._provider, data.providers);
            this._skill = settings.skill || 'auto';
            this._scope = data.settings?.context_scope || settings.scope || 'summary';
            /* 联网搜索默认跟随服务端设置：只有这个浏览器从没选过时才采纳，动手点过开关的浏览器
               保留自己的选择（一次点击不该被下一次刷新改回去）。 */
            if (data.settings && !AISettings.has('search')) {
                AISettings.save({ search: !!data.settings.web_search_default });
            }
            this._renderProviderOptions();
            this._renderSkillOptions();
            this._renderSessions();
            this._renderSide();
            this._renderWorkspace();
        } catch (error) {
            this._toast(I18n.t('ai.error') + ': ' + error.message);
        }
    },

    _renderProviderOptions() {
        const providers = this._bootstrap?.providers || [];
        if (this._dom.provider) {
            this._dom.provider.innerHTML = providers.map((item) => {
                const why = item.local_available === false ? (item.why_not_text || I18n.t('ai.noCapability')) : '';
                const title = why ? ' title="' + AIRender.escape(why) + '"' : '';
                return '<option value="' + AIRender.escape(item.id) + '"' + title + (item.id === this._provider ? ' selected' : '') + '' + (item.local_available === false ? ' disabled' : '') + '>' +
                    AIRender.escape(I18n.has(item.label_key) ? I18n.t(item.label_key) : item.id) + (item.local_available === false ? ' — ' + AIRender.escape(why) : '') + '</option>';
            }).join('');
        }
        this._renderModelOptions();
        this._renderToggles();
    },

    _renderModelOptions() {
        const provider = (this._bootstrap?.providers || []).find((item) => item.id === this._provider);
        const models = provider?.models || [];
        if (this._dom.model) {
            this._dom.model.innerHTML = models.map((item) =>
                '<option value="' + AIRender.escape(item.id) + '"' + (item.id === this._model ? ' selected' : '') + '>' +
                AIRender.escape(item.label || item.id) + '</option>'
            ).join('');
        }
        if (this._dom.modelChip) {
            /* Before the bootstrap answer there is no provider row at all; asking `t(undefined)`
               printed an i18n warning on every open. The id is the honest fallback. */
            const label = provider?.label_key && I18n.has(provider.label_key) ? I18n.t(provider.label_key) : this._provider;
            this._dom.modelChip.textContent = label + ' / ' + (this._model || '—');
        }
    },

    _renderSkillOptions() {
        const skills = this._bootstrap?.skills || [];
        if (this._dom.skill) {
            this._dom.skill.innerHTML = '<option value="auto">' + AIRender.escape(I18n.t('ai.skill') + ': ' + I18n.t('ai.skillAuto')) + '</option>' +
                skills.map((skill) => {
                    const why = skill.available === false
                        ? (skill.why_not_text || I18n.t('ai.skillUnavailable'))
                        : '';
                    const title = why ? ' title="' + AIRender.escape(why) + '"' : '';
                    return '<option value="' + AIRender.escape(skill.id) + '"' + title + (skill.id === this._skill ? ' selected' : '') + '' + (skill.available === false ? ' disabled' : '') + '>' +
                        AIRender.escape(skill.name || (I18n.has(skill.name_key) ? I18n.t(skill.name_key) : skill.id)) + (skill.available === false ? ' — ' + AIRender.escape(why) : '') + '</option>';
                }).join('');
        }
    },

    _runtimeTitle() {
        /* The chip names the host; its tooltip says which host powers are present here. The
           workspace itself is complete on every host, so only these optional powers are listed. */
        const runtime = this._bootstrap?.runtime;
        if (!runtime) return '';
        const pieces = [I18n.has(runtime.label_key) ? I18n.t(runtime.label_key) : (AI_RUNTIME_KEYS[runtime.kind] ? I18n.t(AI_RUNTIME_KEYS[runtime.kind]) : String(runtime.kind || ''))];
        if (runtime.ollama) pieces.push(I18n.t('ai.runtime.daemon'));
        if (runtime.user_files) pieces.push(I18n.t('ai.runtime.files'));
        if (runtime.local_source) pieces.push(I18n.t('ai.runtime.source'));
        if (runtime.code_plugins) pieces.push(I18n.t('ai.runtime.codePlugins'));
        return pieces.join(' · ');
    },

    _renderAgentMode() {
        const mode = this._agentMode === 'plan' ? 'plan' : 'build';
        for (const [button, value] of [[this._dom.agentPlan, 'plan'], [this._dom.agentBuild, 'build']]) {
            if (!button) continue;
            const on = value === mode;
            button.classList.toggle('selected', on);
            button.setAttribute('aria-pressed', on ? 'true' : 'false');
        }
    },

    setAgentMode(mode) {
        this._agentMode = String(mode) === 'plan' ? 'plan' : 'build';
        AISettings.save({ agentMode: this._agentMode });
        this._renderAgentMode();
        this._toast(I18n.t(this._agentMode === 'plan' ? 'ai.mode.planHint' : 'ai.mode.buildHint'));
    },

    _renderToggles() {
        this._renderAgentMode();
        const provider = (this._bootstrap?.providers || []).find((item) => item.id === this._provider);
        const capabilities = provider?.capabilities || [];
        const thinking = this._thinkingOn();
        const search = !!AISettings.load().search && capabilities.includes('web_search');
        if (this._dom.thinking) {
            this._dom.thinking.classList.toggle('selected', thinking);
            this._dom.thinking.disabled = !capabilities.includes('thinking');
            this._dom.thinking.setAttribute('aria-pressed', thinking ? 'true' : 'false');
            this._dom.thinking.title = capabilities.includes('thinking') ? I18n.t('ai.thinking') : I18n.t('ai.noCapability');
        }
        if (this._dom.search) {
            this._dom.search.classList.toggle('selected', search);
            this._dom.search.disabled = !capabilities.includes('web_search');
            this._dom.search.setAttribute('aria-pressed', search ? 'true' : 'false');
            this._dom.search.title = capabilities.includes('web_search') ? I18n.t('ai.search') : I18n.t('ai.noCapability');
        }
        if (this._dom.attachBtn) {
            const files = capabilities.includes('files');
            this._dom.attachBtn.disabled = !files || this._uploading || this._sending;
            this._dom.attachBtn.title = files ? I18n.t('ai.attach') : I18n.t('ai.noCapability');
        }
    },

    _renderComposer() {
        this._renderProviderOptions();
        this._renderSkillOptions();
        this._renderToggles();
        this._renderContextBar();
        this._renderAttachments();
    },

    _renderAttachments() {
        if (!this._dom.attachments) return;
        this._dom.attachments.innerHTML = this._attachments.map((row) =>
            '<span class="ai-attachment"><span>' + AIRender.escape(row.name || 'file') + '</span>' +
            '<button type="button" class="ai-attachment-x" data-ai-remove-attachment="' + AIRender.escape(row.id) + '" aria-label="Remove ' + AIRender.escape(row.name || 'file') + '">×</button></span>'
        ).join('');
    },

    /* ── @ references ─────────────────────────────────────────────────
       Typing `@` names something this account already has, so nothing is uploaded twice: the
       server resolves a dataset/export/workflow into bounded text, and a file uploaded in an
       earlier conversation into its existing file_id. */

    /* ─── Slash commands ───
       `/` at the start of the composer is a command palette, the way Codex/Claude Code expose
       actions without hunting through buttons. It is local: no provider call, no new protocol. */

    _commands() {
        return [
            { id: 'folder', label: 'ai.cmd.folder' },
            { id: 'retry', label: 'ai.cmd.retry' },
            { id: 'new', label: 'ai.cmd.new' },
            { id: 'skills', label: 'ai.cmd.skills' },
            { id: 'stop', label: 'ai.cmd.stop' },
        ];
    },

    _onCmdInput() {
        const input = this._dom.input;
        if (!input) return;
        const match = /^\/([a-z]*)$/i.exec(String(input.value || '').trim());
        if (!match) {
            this._closeCmds();
            return;
        }
        this._cmdQuery = match[1].toLowerCase();
        this._cmdRows = this._commands().filter((row) => !this._cmdQuery || row.id.startsWith(this._cmdQuery));
        this._cmdIndex = 0;
        this._cmdOpen = true;
        if (this._refOpen) this._closeRefs();
        this._renderCmdMenu();
    },

    _renderCmdMenu() {
        const menu = this._dom.cmdMenu;
        if (!menu) return;
        if (!this._cmdOpen) {
            menu.hidden = true;
            menu.innerHTML = '';
            return;
        }
        const rows = this._cmdRows || [];
        menu.innerHTML =
            '<div class="ai-ref-head">' + AIRender.escape(I18n.t('ai.cmd.title')) + '</div>' +
            (rows.length
                ? rows.map((row, index) =>
                    '<button type="button" class="ai-ref-row' + (index === this._cmdIndex ? ' active' : '') + '" data-ai-cmd="' + AIRender.escape(row.id) + '">' +
                    '<span class="ai-ref-kind">/' + AIRender.escape(row.id) + '</span>' +
                    '<span class="ai-ref-label">' + AIRender.escape(I18n.t(row.label)) + '</span></button>'
                ).join('')
                : '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.cmd.empty')) + '</div>');
        menu.hidden = false;
    },

    _closeCmds() {
        this._cmdOpen = false;
        this._cmdRows = [];
        if (this._dom.cmdMenu) {
            this._dom.cmdMenu.hidden = true;
            this._dom.cmdMenu.innerHTML = '';
        }
    },

    _onCmdKey(event, composing) {
        if (event.key === 'Escape') {
            event.preventDefault();
            this._closeCmds();
            return true;
        }
        if (!this._cmdRows || !this._cmdRows.length) {
            if (event.key === 'Enter' && !composing) {
                event.preventDefault();
                return true;
            }
            if (event.key === 'Backspace') this._closeCmds();
            return false;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const delta = event.key === 'ArrowDown' ? 1 : -1;
            this._cmdIndex = (this._cmdIndex + delta + this._cmdRows.length) % this._cmdRows.length;
            this._renderCmdMenu();
            return true;
        }
        if ((event.key === 'Enter' || event.key === 'Tab') && !composing) {
            event.preventDefault();
            this._runCommand(this._cmdRows[this._cmdIndex].id);
            return true;
        }
        return false;
    },

    _runCommand(id) {
        this._closeCmds();
        if (this._dom.input) this._dom.input.value = '';
        if (id === 'folder') this.toggleFolder();
        else if (id === 'retry') this.retry();
        else if (id === 'new') this.newChat();
        else if (id === 'skills') this.openStudio();
        else if (id === 'stop') this.stop();
        this._onRefInput();
    },

    _onRefInput(event) {
        /* Two places accept `@`: the composer and an answer box on a question card. The menu
           belongs to whichever one owns the caret, so a reference picked for an answer lands in
           the answer — never in the composer the user is not looking at. */
        const el = (event && event.target) || this._dom.input;
        if (!el) return;
        const isAnswer = !!(el.hasAttribute && el.hasAttribute('data-ai-custom'));
        if (el !== this._dom.input && !isAnswer) return;
        const match = /(?:^|[\s(])@([^\s@]{0,60})$/.exec(el.value || '');
        if (!match) {
            if (this._refTarget === el) this._closeRefs();
            return;
        }
        this._refTarget = el;
        this._refQuery = match[1];
        this._refOpen = true;
        if (this._dom.refMenu) this._dom.refMenu.hidden = false;
        if (this._refTimer) clearTimeout(this._refTimer);
        this._refTimer = setTimeout(() => this._loadRefs(), 120);
    },

    async _loadRefs() {
        this._refTimer = null;
        try {
            const response = await fetch('/api/ai/references?q=' + encodeURIComponent(this._refQuery || ''));
            const data = await response.json();
            this._refResults = data.ok ? (data.references || []) : [];
        } catch (error) {
            this._refResults = [];
        }
        this._refIndex = 0;
        this._renderRefMenu();
    },

    _refKindLabel(kind) {
        const key = 'ai.ref.' + String(kind || '');
        return I18n.has(key) ? I18n.t(key) : String(kind || '');
    },

    _renderRefMenu() {
        if (!this._dom.refMenu) return;
        if (!this._refOpen) {
            this._dom.refMenu.hidden = true;
            this._dom.refMenu.innerHTML = '';
            return;
        }
        const rows = this._refResults.map((row, index) =>
            '<button type="button" class="ai-ref-row' + (index === this._refIndex ? ' active' : '') + '"' +
            ' data-ai-ref="' + AIRender.escape(row.kind + '|' + row.id) + '">' +
            '<span class="ai-ref-kind">' + AIRender.escape(this._refKindLabel(row.kind)) + '</span>' +
            '<span class="ai-ref-label">' + AIRender.escape(row.label || row.id) + '</span>' +
            '<span class="ai-hint">' + AIRender.escape(row.detail || '') + '</span></button>'
        ).join('');
        this._dom.refMenu.innerHTML =
            '<div class="ai-ref-head">' + AIRender.escape(I18n.t('ai.refsTitle')) + '</div>' +
            (rows || '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.refsEmpty')) + '</div>');
        this._placeRefMenu();
        this._dom.refMenu.hidden = false;
    },

    /* The menu's CSS home is above the composer. An answer box can be anywhere in the transcript,
       so the menu is placed against THAT box's rectangle instead of opening far away at the bottom. */
    _placeRefMenu() {
        const menu = this._dom.refMenu;
        if (!menu || !menu.style) return;
        const target = this._refTarget;
        if (!target || target === this._dom.input || typeof target.getBoundingClientRect !== 'function') {
            menu.style.position = '';
            menu.style.left = '';
            menu.style.right = '';
            menu.style.bottom = '';
            menu.style.width = '';
            return;
        }
        const rect = target.getBoundingClientRect();
        menu.style.position = 'fixed';
        menu.style.left = Math.max(8, rect.left) + 'px';
        menu.style.right = 'auto';
        menu.style.width = Math.max(240, Math.min(rect.width || 320, 420)) + 'px';
        menu.style.bottom = Math.max(8, (window.innerHeight || 800) - rect.top + 6) + 'px';
    },

    /* The menu owns Enter/Arrows/Escape while it is open; true means "handled, do not send". */
    _onRefKey(event, composing) {
        if (event.key === 'Escape') {
            event.preventDefault();
            this._closeRefs();
            return true;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            const total = this._refResults.length;
            if (total) {
                const step = event.key === 'ArrowDown' ? 1 : -1;
                this._refIndex = (this._refIndex + step + total) % total;
                this._renderRefMenu();
            }
            event.preventDefault();
            return true;
        }
        if (event.key === 'Enter' && !event.shiftKey && !composing && this._refResults.length) {
            const row = this._refResults[this._refIndex];
            event.preventDefault();
            if (row) this._pickRef(row.kind, row.id, row.label);
            return true;
        }
        return false;
    },

    _pickRef(kind, id, label) {
        if (!kind || !id) return;
        const target = this._refTarget || this._dom.input;
        if (!target) return;
        const value = String(target.value || '').replace(/@[^\s@]{0,60}$/, '').replace(/\s+$/, '');
        target.value = value ? value + ' ' : '';
        const questionId = target.getAttribute ? target.getAttribute('data-ai-custom') : null;
        const isAnswer = questionId !== null;
        if (isAnswer) {
            const rows = this._answerRefs(questionId);
            if (!rows.some((row) => row.kind === kind && row.id === id)) {
                rows.push({ kind: kind, id: id, label: label || id });
            }
            this._renderAnswerRefs(questionId);
        } else if (!this._refs.some((row) => row.kind === kind && row.id === id)) {
            this._refs.push({kind: kind, id: id, label: label || id});
            this._renderRefs();
        }
        this._closeRefs();
        if (target.focus) target.focus();
    },

    /* The refs a question's answer box carries, keyed by the QUESTION (one card may hold several). */
    _answerRefs(questionId) {
        if (!this._current) return [];
        this._current.answerRefs = this._current.answerRefs || {};
        const key = String(questionId || '');
        this._current.answerRefs[key] = this._current.answerRefs[key] || [];
        return this._current.answerRefs[key];
    },

    _renderAnswerRefs(questionId) {
        const card = this._dom.chat && this._dom.chat.querySelector('[data-ai-question-card="' + String(questionId) + '"]');
        const host = card && card.querySelector('[data-ai-question-refs]');
        if (!host) return;
        const rows = this._answerRefs(questionId);
        host.innerHTML = rows.map((row) =>
            '<span class="ai-ref-chip"><span class="ai-ref-kind">' + AIRender.escape(this._refKindLabel(row.kind)) + '</span>' +
            '<span class="ai-ref-label">' + AIRender.escape(row.label || row.id) + '</span>' +
            '<button type="button" class="ai-ref-x" data-ai-remove-answer-ref="' + AIRender.escape(row.kind + '|' + row.id + '|' + questionId) + '" aria-label="remove">×</button></span>'
        ).join('');
    },

    _removeRef(kind, id) {
        this._refs = this._refs.filter((row) => !(row.kind === kind && row.id === id));
        this._renderRefs();
    },

    _closeRefs() {
        this._refOpen = false;
        this._refQuery = '';
        if (this._refTimer) {
            clearTimeout(this._refTimer);
            this._refTimer = null;
        }
        if (this._dom.refMenu) {
            this._dom.refMenu.hidden = true;
            this._dom.refMenu.innerHTML = '';
            /* Back to the stylesheet's own position, so the composer's menu is not stuck at an
               answer box's coordinates. */
            if (this._dom.refMenu.style) {
                this._dom.refMenu.style.position = '';
                this._dom.refMenu.style.left = '';
                this._dom.refMenu.style.right = '';
                this._dom.refMenu.style.bottom = '';
                this._dom.refMenu.style.width = '';
            }
        }
        this._refTarget = null;
    },

    _renderRefs() {
        if (!this._dom.refs) return;
        this._dom.refs.innerHTML = this._refs.map((row) =>
            '<span class="ai-ref-chip"><span class="ai-ref-kind">' + AIRender.escape(this._refKindLabel(row.kind)) + '</span>' +
            '<span>' + AIRender.escape(row.label || row.id) + '</span>' +
            '<button type="button" class="ai-attachment-x" data-ai-remove-ref="' + AIRender.escape(row.kind + '|' + row.id) + '" aria-label="Remove ' + AIRender.escape(row.label || row.id) + '">×</button></span>'
        ).join('');
    },

    _renderContextBar() {
        if (!this._dom.context) return;
        const context = AIContext.collect();
        const pieces = [];
        if (context.canvas) pieces.push(I18n.t('ai.nodesCount', { n: (context.canvas.nodes || []).length }));
        if (context.dataset_id) pieces.push(I18n.t('ai.datasetShort', { id: context.dataset_id }));
        if (context.run_id) pieces.push(I18n.t('ai.runShort', { id: context.run_id }));
        this._dom.context.innerHTML =
            '<span class="ai-chip">' + AIRender.escape(I18n.t('ai.context')) + '</span>' +
            (this._bootstrap?.runtime ? '<span class="ai-chip ai-runtime-chip" title="' + AIRender.escape(this._runtimeTitle()) + '">' + AIRender.escape(I18n.has(this._bootstrap.runtime.label_key) ? I18n.t(this._bootstrap.runtime.label_key) : (AI_RUNTIME_KEYS[this._bootstrap.runtime.kind] ? I18n.t(AI_RUNTIME_KEYS[this._bootstrap.runtime.kind]) : String(this._bootstrap.runtime.kind || ''))) + '</span>' : '') +
            '<span class="ai-hint">' + AIRender.escape(pieces.join(' · ') || I18n.t('ai.contextEmpty')) + '</span>' +
            '<button type="button" class="ai-ghost" data-ai-context-refresh="1">' + AIRender.escape(I18n.t('ai.contextRefresh')) + '</button>';
    },

    _renderWelcome() {
        if (this._mode !== 'chat' || !this._dom.chat) return;
        if (this._messages.length) return;
        const suggestions = [
            ['diagnose', 'ai.suggest.diagnose'],
            ['analysis', 'ai.suggest.analysis'],
            ['workflow', 'ai.suggest.workflow'],
            ['charts', 'ai.suggest.charts'],
            ['project', 'ai.suggest.project'],
        ].map(([skill, key]) =>
            '<button type="button" class="ai-suggestion" data-ai-suggest="' + skill + '">' + AIRender.escape(I18n.t(key)) + '</button>'
        ).join('');
        this._dom.chat.innerHTML =
            '<section class="ai-welcome">' +
            '<div class="ai-welcome-mark">◌</div>' +
            '<h2>' + AIRender.escape(I18n.t('ai.welcomeTitle')) + '</h2>' +
            '<p>' + AIRender.escape(I18n.t('ai.welcomeBody')) + '</p>' +
            '<div class="ai-suggestions">' + suggestions + '</div>' +
            '</section>';
        this._renderSide();
    },

    _renderSessions() {
        if (!this._dom.sessions) return;
        const rows = this._bootstrap?.conversations || [];
        const archived = !!this._showArchived;
        const query = this._sessionQuery || '';
        /* The search box lives inside this repainted container, so a refresh triggered by typing
           would otherwise drop the caret after the first character. Remember it and put it back. */
        const active = document.activeElement;
        const typing = !!(active && active.hasAttribute && active.hasAttribute('data-ai-session-search'));
        const caret = typing ? active.selectionStart : null;
        const items = rows.map((row) => {
            const id = AIRender.escape(row.id);
            const rename = AIRender.escape(I18n.t('ai.rename'));
            const remove = AIRender.escape(I18n.t('ai.delete'));
            const pinLabel = AIRender.escape(I18n.t(row.pinned ? 'ai.unpinConversation' : 'ai.pinConversation'));
            const exportLabel = AIRender.escape(I18n.t('ai.exportConversation'));
            const archiveLabel = AIRender.escape(I18n.t(archived ? 'ai.restoreConversation' : 'ai.archiveConversation'));
            const sessionModel = [row.provider, row.model].filter(Boolean).join(' / ');
            return (
                '<div class="ai-session-row' + (row.pinned ? ' pinned' : '') + '">' +
                '<button type="button" class="ai-session ' + (row.id === this._conversationId ? 'selected' : '') + '" data-ai-conversation="' + id + '"' +
                (sessionModel ? ' title="' + AIRender.escape(sessionModel) + '"' : '') + '>' +
                '<span class="ai-session-text">' +
                '<span class="ai-session-title">' + (row.pinned ? '<span class="ai-session-pin">★</span>' : '') + AIRender.escape(row.title || I18n.t('ai.noConversation')) + '</span>' +
                /* Which model answered this conversation, so an old chat is readable as itself rather
                   than as "whatever the picker shows today". */
                (sessionModel ? '<span class="ai-session-model">' + AIRender.escape(sessionModel) + '</span>' : '') +
                '</span>' +
                '<span class="ai-session-meta">' + AIRender.escape(String(row.message_count || 0)) + '</span>' +
                '</button>' +
                '<span class="ai-session-actions">' +
                '<button type="button" class="ai-icon-btn' + (row.pinned ? ' active' : '') + '" data-ai-pin-conversation="' + id + '" title="' + pinLabel + '" aria-label="' + pinLabel + '" aria-pressed="' + (row.pinned ? 'true' : 'false') + '">★</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-rename-conversation="' + id + '" title="' + rename + '" aria-label="' + rename + '">✎</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-export-conversation="' + id + '" title="' + exportLabel + '" aria-label="' + exportLabel + '">⤓</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-archive-conversation="' + id + '" data-ai-archived="' + (archived ? '1' : '0') + '" title="' + archiveLabel + '" aria-label="' + archiveLabel + '">' + (archived ? '↩' : '▤') + '</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-delete-conversation="' + id + '" title="' + remove + '" aria-label="' + remove + '">×</button>' +
                '</span></div>'
            );
        }).join('');
        const emptyKey = query ? 'ai.noSessionsMatch' : archived ? 'ai.archivedEmpty' : 'ai.noSessions';
        this._dom.sessions.innerHTML =
            '<div class="ai-sessions-head"><strong>' + AIRender.escape(I18n.t('ai.sessions')) + '</strong>' +
            '<button type="button" class="ai-ghost" data-ai-new-session="1">' + AIRender.escape(I18n.t('ai.newChat')) + '</button></div>' +
            '<label class="ai-session-search"><input class="ai-input" type="search" data-ai-session-search value="' + AIRender.escape(query) + '" placeholder="' + AIRender.escape(I18n.t('ai.searchSessions')) + '" /></label>' +
            '<div class="ai-session-filter"><button type="button" class="ai-ghost' + (archived ? ' selected' : '') + '" data-ai-toggle-archived="1" aria-pressed="' + (archived ? 'true' : 'false') + '">' + AIRender.escape(I18n.t('ai.archived')) + '</button></div>' +
            '<div class="ai-session-list">' + (items || '<p class="ai-hint">' + AIRender.escape(I18n.t(emptyKey)) + '</p>') + '</div>';
        if (typing) {
            const box = this._dom.sessions.querySelector('[data-ai-session-search]');
            if (box) {
                box.focus();
                if (caret !== null && caret !== undefined) box.setSelectionRange(caret, caret);
            }
        }
    },

    _renderSide() {
        if (!this._dom.side) return;
        const meta = this._contextMeta || {};
        const preview = this._contextPreview
            ? '<section class="ai-side-block ai-context-preview-block"><h3>' +
              AIRender.escape(I18n.t('ai.contextPreview')) + '</h3>' +
              '<button type="button" class="ai-ghost" data-ai-context-preview="1">' +
              AIRender.escape(I18n.t('ai.contextHide')) + '</button>' +
              '<pre class="ai-code ai-context-preview">' + AIRender.escape(this._contextPreview) + '</pre></section>'
            : '';
        const previewLabel = this._contextPreview ? 'ai.contextHide' : 'ai.contextPreview';
        const items = (meta.items || []).map((item) => '<li>' + AIRender.escape(item.title) + ' <span class="ai-hint">' + AIRender.escape(I18n.t('ai.chars', { n: item.chars || 0 })) + '</span></li>').join('');
        /* What was NOT sent is part of the answer: a context cut by the replay budget or by the
           overall budget changed what the model could have known, and silence reads as “it saw
           everything”. */
        const omitted = (meta.omitted || []).filter(Boolean);
        const history = meta.history || {};
        const memories = meta.memories || {};
        const contextNotes =
            (history.dropped
                ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextHistoryCut', { n: history.dropped, window: history.window || 0 })) + '</p>'
                : '') +
            (memories.omitted
                ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextMemoryCut', { n: memories.omitted, shown: memories.shown || 0 })) + '</p>'
                : '') +
            (meta.replay_truncated
                ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextReplayCut', { n: meta.replay_chars || 0 })) + '</p>'
                : '') +
            (omitted.length
                ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextOmitted', { items: omitted.join('、') })) + '</p>'
                : '');
        const plan = (this._plan || []).map((step) =>
            '<li class="ai-trace-step ' + (step.status || 'pending') + '"><span class="ai-trace-dot"></span>' + AIRender.escape(step.title) + '</li>'
        ).join('');
        const usage = this._usage ? AIRender.usage(this._usage) : '';
        const monitors = (this._bootstrap?.monitors || [])
            .filter((item) => item.status === 'armed' && (!item.conversation_id || item.conversation_id === this._conversationId));
        const monitorRows = monitors.map((item) => {
            const spec = item.spec || {};
            const title = spec.note || (spec.events || []).join(', ') || I18n.t('ai.monitor.notice');
            return '<li class="ai-monitor-row"><span class="ai-monitor-text">' + AIRender.escape(title) + '</span>' +
                (item.auto_analyze ? '<span class="ai-chip">' + AIRender.escape(I18n.t('ai.monitor.autoTag')) + '</span>' : '') +
                '<button type="button" class="ai-ghost" data-ai-disarm-monitor="' + AIRender.escape(item.id) + '">' + AIRender.escape(I18n.t('ai.monitor.disarm')) + '</button></li>';
        }).join('');
        this._dom.side.innerHTML =
            preview +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.context')) + '</h3>' +
            (meta.scope ? '<div class="ai-chip-row"><span class="ai-chip">' + AIRender.escape(meta.scope) + '</span><span class="ai-chip">' + AIRender.escape(I18n.t('ai.contextTokens', { tokens: meta.tokens || 0, chars: meta.chars || 0 })) + '</span></div>' : '') +
            '<ul class="ai-context-list">' + (items || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.contextEmpty')) + '</li>') + '</ul>' + contextNotes +
            '<div class="ai-context-actions"><button type="button" class="ai-ghost" data-ai-context-preview="1">' + AIRender.escape(I18n.t(previewLabel)) + '</button></div>' +
            '<div class="ai-context-fields"><label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.datasetId')) + '</span><input class="ai-input" data-ai-manual="dataset_id" value="' + AIRender.escape(AIContext.manual.dataset_id || '') + '" /></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.runId')) + '</span><input class="ai-input" data-ai-manual="run_id" value="' + AIRender.escape(AIContext.manual.run_id || '') + '" /></label>' +
            '<button type="button" class="ai-ghost" data-ai-context-apply="1">' + AIRender.escape(I18n.t('ai.applyContext')) + '</button></div>' +
            '</section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.monitor.heading')) + '</h3>' +
            '<ul class="ai-monitor-list">' + (monitorRows || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.monitor.empty')) + '</li>') + '</ul></section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.agentTrace')) + '</h3>' +
            '<ol class="ai-trace">' + (plan || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.planEmpty')) + '</li>') + '</ol></section>' +
            '<section class="ai-side-block ai-spend"><h3>' + AIRender.escape(I18n.t('ai.spend.heading')) +
            '<button type="button" class="ai-ghost" data-ai-spend-refresh="1">' + AIRender.escape(I18n.t('ai.spend.refresh')) + '</button></h3>' +
            this._spendHtml() + '</section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.usage')) + '</h3>' + (usage || '<p class="ai-hint">—</p>') + '</section>';
    },

    /* The conversation's own numbers: which models it used, the tokens, how much of the input came
       back from the provider's prefix cache, and (when the provider publishes prices) the money.
       Everything here is the server's answer — a token count is a fact, a price is the provider's. */
    _spendHtml() {
        const rows = [];
        const money = (amount, currency, digits) => {
            if (amount === null || amount === undefined) return '—';
            const code = String(currency || '').toUpperCase();
            const symbol = code === 'CNY' ? '¥' : (code === 'USD' ? '$' : '');
            const places = Number.isFinite(digits) ? digits : (Number(amount) < 0.01 ? 6 : 4);
            return symbol + Number(amount).toFixed(places);
        };
        const balance = this._balance;
        if (balance && balance.supported) {
            const lines = (balance.balances || []).map((row) => {
                const label = row.currency || balance.currency || '';
                return '<li><span>' + AIRender.escape(I18n.t('ai.spend.balance')) + ' · ' + AIRender.escape(label) + '</span><b>' +
                    AIRender.escape(money(row.total, row.currency || label, 2)) + '</b></li>';
            }).join('');
            rows.push(
                '<ul class="ai-spend-rows">' + (lines || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.noBalance')) + '</li>') +
                '</ul>' + (balance.available === false ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.unavailable')) + '</p>' : '')
            );
        } else if (balance && balance.supported === false) {
            rows.push('<p class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.unsupported')) + '</p>');
        }
        const usage = this._convoUsage;
        if (usage && (usage.total_tokens || usage.calls)) {
            const models = (usage.models || []).map((row) => (row.provider ? row.provider + ' / ' : '') + row.model).filter(Boolean);
            if (models.length) {
                rows.push('<ul class="ai-spend-rows"><li><span>' + AIRender.escape(I18n.t('ai.spend.models')) + '</span><b>' +
                    AIRender.escape(models.join('、')) + '</b></li></ul>');
            }
            rows.push(
                '<ul class="ai-spend-rows">' +
                '<li><span>' + AIRender.escape(I18n.t('ai.spend.input')) + '</span><b>' + usage.prompt_tokens + '</b></li>' +
                '<li><span>' + AIRender.escape(I18n.t('ai.spend.output')) + '</span><b>' + usage.completion_tokens + '</b></li>' +
                '<li><span>' + AIRender.escape(I18n.t('ai.spend.cacheRate')) + '</span><b>' + (Math.round((usage.cache_hit_rate || 0) * 1000) / 10) + '%</b></li>' +
                (usage.cost === null || usage.cost === undefined
                    ? ''
                    : '<li><span>' + AIRender.escape(I18n.t('ai.spend.cost')) + ' <span class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.estimated')) + '</span></span><b>' + AIRender.escape(money(usage.cost, usage.currency)) + '</b></li>') +
                '</ul>'
            );
        } else if (this._conversationId) {
            rows.push('<p class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.empty')) + '</p>');
        }
        return rows.join('') || '<p class="ai-hint">—</p>';
    },

    async _loadSpend() {
        const provider = this._provider || '';
        const key = AISettings.keyFor(provider);
        if (key) {
            try {
                const response = await fetch('/api/ai/providers/' + encodeURIComponent(provider) + '/balance', {
                    headers: { 'X-Provider-Key': key },
                });
                const data = await response.json();
                this._balance = data.ok ? data : null;
            } catch (error) {
                this._balance = null;
            }
        } else {
            this._balance = null;
        }
        if (this._conversationId) {
            try {
                const response = await fetch('/api/ai/conversations/' + encodeURIComponent(this._conversationId) + '/usage');
                const data = await response.json();
                this._convoUsage = data.ok ? data.usage : null;
            } catch (error) {
                this._convoUsage = null;
            }
        } else {
            this._convoUsage = null;
        }
        this._renderSide();
    },

    _ensureAssistant() {
        if (!this._current || !this._current.el) {
            const el = document.createElement('article');
            el.className = 'ai-message assistant';
            el.innerHTML =
                '<div class="ai-message-role">' + AIRender.escape(I18n.t('ai.assistant')) + '</div>' +
                '<div class="ai-message-body">' +
                '<div class="ai-flow"></div>' +
                AIRender.statusRow() +
                '<div class="ai-artifacts"></div>' +
                '<div class="ai-question-slot"></div>' +
                '<div class="ai-usage"></div>' +
                '<div class="ai-message-actions">' +
                '<button type="button" class="ai-ghost" data-ai-copy-answer="1">' + AIRender.escape(I18n.t('ai.copyAnswer')) + '</button>' +
                '<button type="button" class="ai-ghost" data-ai-retry="1">' + AIRender.escape(I18n.t('ai.retry')) + '</button>' +
                '</div>' +
                '</div>';
            this._dom.chat.appendChild(el);
            this._current = { el };
            this._current.flowEl = el.querySelector('.ai-flow');
            this._current.artifactsEl = el.querySelector('.ai-artifacts');
            this._current.questionEl = el.querySelector('.ai-question-slot');
            this._current.usageEl = el.querySelector('.ai-usage');
            this._current.blocks = [];
            this._current.questions = [];
            this._current.answers = {};
        }
        return this._current;
    },

    /* Repaint the turn from its ordered blocks. The ONE writer for `.ai-flow`, shared with the
       stored-message renderer, so a live turn and a reopened one cannot disagree. */
    _paintAssistant() {
        const current = this._current;
        if (!current || !current.flowEl) return;
        const chat = this._dom.chat;
        const atBottom = chat ? chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80 : true;
        const blocks = current.blocks || [];
        const html = AIRender.assistantFlow(blocks);
        /* Between steps the model says nothing and the stream is silent: after a tool card there is
           no sign of life until the app answers, and after a finished paragraph a reader cannot tell
           "the answer is complete" from "the model is still composing". The live line is drawn by
           `_renderStatus` — outside this memoised flow — in BOTH cases, so the transcript never
           looks finished while the turn is still open. */
        /* A repaint rebuilds this block stream. Two rules make that invisible:
           1. an unchanged picture is not re-written (a running tool card used to be replaced every
              90 ms, which dropped the focus and any open disclosure);
           2. the open/closed state of every disclosure is remembered and re-applied, so reading a
              thinking block or a tool result is not undone by the next streaming delta. */
        if (current._flowHtml === html) {
            this._renderStatus();
            return;
        }
        if (this._pointerDown) {
            /* The reader is pressing something in here: keep the nodes stable until the press ends
               (see the document pointerup listener), or the click lands on a node that just left. */
            current._pendingPaint = true;
            this._renderStatus();
            return;
        }
        current._flowHtml = html;
        this._collectOpenDetails(current.flowEl);
        current.flowEl.innerHTML = html;
        this._applyOpenDetails(current.flowEl);
        if (atBottom && chat) chat.scrollTop = chat.scrollHeight;
        this._renderStatus();
    },

    /* ─── The live line ("生成中 · 12s") ─── */

    /* What the line SAYS is the phase; the number is proof of life. A static "working" line on a
       stream that has been silent for a minute reads exactly like a dead one — which is why the
       reader used to conclude the answer had been cut — so the line carries the seconds this turn
       has been open, and says the model has gone quiet when it has. */
    _statusPhase() {
        const running = (this._current?.blocks || []).some(
            (row) => row.type === 'tool_use' && row.status === 'running'
        );
        /* A tool that runs for minutes legitimately sends nothing: say WHO we are waiting for. */
        if (running) return 'ai.waiting';
        const silent = Date.now() - (this._lastEventAt || Date.now());
        if (silent >= STALL_AFTER_MS) return 'ai.stillWaiting';
        return 'ai.working';
    },

    /* The one writer for that node. It is updated in place — never through `_paintAssistant` — so a
       tick does not rebuild (and un-focus, un-open, un-scroll) the block stream. */
    _renderStatus() {
        const host = this._current?.el ? this._current.el.querySelector('.ai-status') : null;
        if (!host) return;
        if (!this._sending) {
            host.hidden = true;
            return;
        }
        host.hidden = false;
        const text = host.querySelector('.ai-status-text');
        const phase = I18n.t(this._statusPhase());
        if (text && text.textContent !== phase) text.textContent = phase;
        const clock = host.querySelector('.ai-status-clock');
        if (!clock) return;
        const seconds = Math.max(0, Math.round((Date.now() - (this._turnStartedAt || Date.now())) / 1000));
        const shown = ' · ' + I18n.t('ai.elapsed', { seconds: seconds });
        if (clock.textContent !== shown) clock.textContent = shown;
    },

    /* One interval for the whole turn: it ticks the live line AND every running tool card's clock.
       (The tool clock was written for this and then never started, so a three-minute command showed
       the same static "运行中" the whole time.) */
    _startClock() {
        if (this._turnClock) return;
        this._turnClock = setInterval(() => {
            this._renderStatus();
            this._tickToolClocks();
            if (!this._sending && !this._dom.chat?.querySelector('.ai-tool-clock')) this._stopClock();
        }, 1000);
    },

    _stopClock() {
        if (this._turnClock) clearInterval(this._turnClock);
        this._turnClock = null;
    },

    _tickToolClocks() {
        const clocks = this._dom.chat ? this._dom.chat.querySelectorAll('.ai-tool-clock') : [];
        if (!clocks.length) return;
        const running = (this._current?.blocks || []).filter(
            (row) => row.type === 'tool_use' && row.status === 'running'
        );
        const started = Number((running[0] && running[0].startedAt) || Date.now());
        const seconds = Math.max(0, Math.round((Date.now() - started) / 1000));
        for (const el of clocks) el.textContent = ' · ' + seconds + 's';
    },

    /* Disclosure state belongs to the reader, not to the paint. Keyed by ``data-ai-detail`` (a
       thinking block's index, a tool call's id, an artifact's id), so the same card keeps its
       state across repaints AND across a stored-transcript repaint. */
    _collectOpenDetails(root) {
        if (!root || typeof root.querySelectorAll !== 'function') return;
        for (const el of root.querySelectorAll('details[data-ai-detail]')) {
            const key = String((el.getAttribute && el.getAttribute('data-ai-detail')) || '');
            if (!key) continue;
            const open = el.open === true || (el.hasAttribute && el.hasAttribute('open'));
            if (open) this._openDetails.add(key);
            else this._openDetails.delete(key);
        }
    },

    /* One writer for a disclosure's state, because a programmatic `.open` (the tool row click) does
       not always reach the capture listener in time for the next paint. */
    _setDetailOpen(detail, open) {
        if (!detail) return;
        detail.open = !!open;
        const key = String((detail.getAttribute && detail.getAttribute('data-ai-detail')) || '');
        if (key) {
            if (open) this._openDetails.add(key);
            else this._openDetails.delete(key);
        }
        const card = detail.parentElement;
        if (card && card.classList && card.classList.contains('ai-tool')) card.classList.toggle('is-open', !!open);
    },

    _applyOpenDetails(root) {
        if (!root || typeof root.querySelectorAll !== 'function' || !this._openDetails.size) return;
        for (const el of root.querySelectorAll('details[data-ai-detail]')) {
            const key = String((el.getAttribute && el.getAttribute('data-ai-detail')) || '');
            if (key && this._openDetails.has(key)) this._setDetailOpen(el, true);
        }
    },

    /* ``record`` is what separates a new turn from a repaint. ``_renderMessages`` replays stored
       rows and already has them; pushing there used to append into the array it was iterating,
       which never terminates. A repaint draws only. */
    _appendUser(text, context, attachments, extra, record = true) {
        const el = document.createElement('article');
        el.className = 'ai-message user';
        const files = (attachments || []).map((row) =>
            '<span class="ai-attachment">' + AIRender.escape(row.name || 'file') + '</span>'
        ).join('');
        const monitor = extra?.monitor_event
            ? '<span class="ai-monitor-tag">' + AIRender.escape(I18n.t('ai.monitor.notice')) + '</span>'
            : '';
        const feedback = extra?.feedback
            ? '<span class="ai-monitor-tag">' + AIRender.escape(I18n.t('ai.feedback.tag')) + '</span>'
            : '';
        el.innerHTML = '<div class="ai-message-role">' + AIRender.escape(I18n.t('ai.you')) + monitor + feedback + '</div><div class="ai-message-body">' +
            (files ? '<div class="ai-attachments ai-message-files">' + files + '</div>' : '') +
            '<div class="ai-user-text">' + AIRender.escape(text) + '</div></div>';
        this._dom.chat.appendChild(el);
        if (record) {
            this._messages.push({
                role: 'user',
                content: text,
                meta: { context: context || {}, attachments: attachments || [], monitor_event: extra?.monitor_event || '' },
            });
        }
        this._dom.chat.scrollTop = this._dom.chat.scrollHeight;
    },

    /* ─── Working folder (the harness's one root) ─── */

    _workspace() {
        return this._bootstrap?.workspace || {};
    },

    _renderWorkspace() {
        const button = this._dom.workspaceBtn;
        if (!button) return;
        const state = this._workspace();
        button.hidden = !!state.cloud;
        if (state.cloud) return;
        const name = String(state.folder_name || '');
        button.textContent = name || I18n.t('ai.workspace.choose');
        button.title = state.folder
            ? I18n.t('ai.workspace.current', { path: state.folder })
            : I18n.t('ai.workspace.none');
        button.classList.toggle('is-set', !!state.folder);
    },

    toggleFolder() {
        if (!this._dom.folderDialog) return;
        if (!this._dom.folderDialog.hidden) {
            this._dom.folderDialog.hidden = true;
            return;
        }
        this._openFolder(this._workspace().folder || '');
    },

    async _openFolder(path) {
        const host = this._dom.folderDialog;
        if (!host) return;
        host.hidden = false;
        host.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.choose')) + '…</div>';
        try {
            const response = await fetch('/api/ai/workspace/browse?path=' + encodeURIComponent(path || ''));
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'HTTP ' + response.status);
            this._folderState = data;
            this._renderFolder();
        } catch (error) {
            host.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.failed', { detail: error.message })) + '</div>';
        }
    },

    _renderFolder() {
        const host = this._dom.folderDialog;
        const state = this._folderState;
        if (!host || !state) return;
        const rows = (state.entries || []).filter((row) => row.dir);
        const list = rows.length
            ? rows.map((row) =>
                '<button type="button" class="ai-folder-row" data-ai-folder-open="' + AIRender.escape(row.path) + '">' +
                '<span class="ai-folder-ico" aria-hidden="true">▸</span>' +
                '<span class="ai-folder-name">' + AIRender.escape(row.name) + '</span></button>'
            ).join('')
            : '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.empty')) + '</div>';
        /* The roots are the OTHER disks. Walking down from one drive could never reach another
           (`dirname('C:\\')` is itself, so the Up button vanished at the root), which made every
           folder outside C: unreachable from this panel. The server answers the list per OS. */
        const roots = state.roots || [];
        const rootRow = roots.length > 1
            ? '<div class="ai-folder-roots">' + roots.map((root) =>
                '<button type="button" class="ai-folder-root' +
                (String(root.path) === String(state.path) ? ' is-current' : '') +
                '" data-ai-folder-root="' + AIRender.escape(root.path) + '">' +
                AIRender.escape(root.name) + '</button>'
            ).join('') + '</div>'
            : '';
        host.innerHTML =
            '<div class="ai-folder-head">' + AIRender.escape(I18n.t('ai.workspace.title')) + '</div>' +
            rootRow +
            '<div class="ai-folder-path" title="' + AIRender.escape(state.path) + '">' + AIRender.escape(state.path) + '</div>' +
            '<div class="ai-folder-list">' + list + '</div>' +
            '<div class="ai-folder-actions">' +
            (state.parent ? '<button type="button" class="ai-ghost" data-ai-folder-open="' + AIRender.escape(state.parent) + '">' + AIRender.escape(I18n.t('ai.workspace.up')) + '</button>' : '') +
            '<button type="button" class="ai-ghost" data-ai-folder-native="1">' + AIRender.escape(I18n.t('ai.workspace.native')) + '</button>' +
            '<button type="button" class="ai-primary" data-ai-folder-use="' + AIRender.escape(state.path) + '">' + AIRender.escape(I18n.t('ai.workspace.use')) + '</button>' +
            (this._workspace().folder ? '<button type="button" class="ai-ghost" data-ai-folder-clear="1">' + AIRender.escape(I18n.t('ai.workspace.clear')) + '</button>' : '') +
            '<button type="button" class="ai-ghost" data-ai-folder-close="1">' + AIRender.escape(I18n.t('ai.workspace.close')) + '</button>' +
            '</div>' +
            '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.hint')) + '</div>';
    },

    /* The OS's own dialog: it can jump to any disk, remembers recent places and shows network
       drives. The server opens it in a child process, so this request waits until the user picks. */
    async _pickNativeFolder() {
        const host = this._dom.folderDialog;
        if (!host) return;
        host.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.pickWaiting')) + '</div>';
        try {
            const response = await fetch('/api/ai/workspace/pick', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ start: (this._folderState && this._folderState.path) || '' }),
            });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'HTTP ' + response.status);
            if (data.cancelled || !data.path) {
                this._renderFolder();
                return;
            }
            await this._setFolder(data.path);
        } catch (error) {
            host.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.failed', { detail: error.message })) + '</div>';
        }
    },

    async _setFolder(path) {
        try {
            const response = await fetch('/api/ai/workspace', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path || '' }),
            });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'HTTP ' + response.status);
            if (this._bootstrap) this._bootstrap.workspace = data.workspace;
            this._renderWorkspace();
            if (this._dom.folderDialog) this._dom.folderDialog.hidden = true;
            this._toast(path
                ? I18n.t('ai.workspace.changed', { path: data.workspace.folder || path })
                : I18n.t('ai.workspace.none'));
            this._renderSide();
        } catch (error) {
            this._toast(I18n.t('ai.workspace.failed', { detail: error.message }));
        }
    },

    /* ─── Applying a workflow the assistant produced ─── */
    async _applyWorkflowPayload(payload, run, title) {
        if (typeof workflow === 'undefined' || !workflow || typeof workflow.loadFromJSON !== 'function') {
            this._toast(I18n.t('toast.workflowFileInvalid'));
            return false;
        }
        let ok = false;
        let detail = '';
        try {
            ok = workflow.loadFromJSON(payload) !== false;
            if (!ok) detail = 'loadFromJSON refused the file';
        } catch (error) {
            detail = String((error && error.message) || error);
        }
        if (!ok) {
            this._workflowFeedback(title, detail);
            return false;
        }
        this._toast(I18n.t('ai.workflowApplied', { name: title || '' }));
        if (run) {
            try {
                await workflow.execute();
            } catch (error) {
                this._workflowFeedback(title, String((error && error.message) || error));
                return false;
            }
        }
        return true;
    },

    /* ─── Failed nodes and rerun ─── */

    /* ``app_errors`` is the evidence the model reads after a monitor fires; its failed nodes become
       one card with a button that reruns that subtree from the SAVED file. */
    _ingestFailedNodes(result, current) {
        const runs = Array.isArray(result && result.runs) ? result.runs : [];
        if (!runs.length) return;
        const wanted = String((this._monitorFailed && this._monitorFailed.run_id) || '');
        const run = runs.find((row) => String(row.run_id || '') === wanted) || runs[0];
        const nodes = (Array.isArray(run.nodes) ? run.nodes : [])
            .filter((node) => ['failed', 'partial'].includes(String(node.status || '')) || node.error)
            .map((node) => ({ node: String(node.node || node.node_id || ''), error: String(node.error || '') }))
            .filter((node) => node.node);
        const runId = String(run.run_id || wanted || '');
        const workflowName = String(run.workflow || (this._monitorFailed && this._monitorFailed.workflow_name) || '');
        this._pushFailedCard(runId, workflowName, nodes, current);
    },

    /* ``run_status`` is the other reader a monitor turn uses; it answers one run with a node map. */
    _ingestRunNodes(result, current) {
        const run = (result && result.run) || {};
        const nodes = result && result.nodes;
        if (!nodes || typeof nodes !== 'object') return;
        const rows = Object.entries(nodes)
            .filter(([, row]) => row && (['failed', 'partial'].includes(String(row.status || '')) || row.error))
            .map(([id, row]) => ({ node: String(id), error: String((row && row.error) || '') }));
        const runId = String(run.id || run.run_id || '');
        if (!runId) return;
        this._pushFailedCard(runId, String(run.workflow_name || ''), rows, current);
    },

    _pushFailedCard(runId, workflowName, nodes, current) {
        if (!nodes.length) return;
        const existing = (current.blocks || []).find((row) => row.type === 'failed_nodes' && String(row.run_id || '') === runId);
        if (existing) {
            existing.nodes = nodes;
            existing.workflow_name = workflowName || existing.workflow_name || '';
        } else {
            current.blocks.push({ type: 'failed_nodes', run_id: runId, workflow_name: workflowName, nodes: nodes });
        }
        this._schedulePaint(current);
    },

    _markRerunStarted(runId, nodeId, workflowName, current) {
        const turn = current || this._current || this._ensureAssistant();
        const block = (turn.blocks || []).find((row) => row.type === 'failed_nodes' && String(row.run_id || '') === String(runId || ''));
        if (block) {
            block.started = nodeId;
            if (workflowName) block.workflow_name = workflowName;
            if (!(block.nodes || []).some((node) => String(node.node || '') === String(nodeId || ''))) {
                block.nodes = (block.nodes || []).concat([{ node: nodeId, error: '' }]);
            }
            return;
        }
        turn.blocks.push({
            type: 'failed_nodes',
            run_id: String(runId || ''),
            workflow_name: String(workflowName || ''),
            nodes: [{ node: String(nodeId || ''), error: '' }],
            started: String(nodeId || ''),
        });
    },

    async _rerunFailedNode(runId, nodeId, workflowName) {
        if (!runId || !nodeId) {
            this._toast(I18n.t('ai.rerunNoWorkflowHint'));
            return false;
        }
        if (typeof showDialog !== 'function') return false;
        const answer = await showDialog({
            message: I18n.t('ai.rerunConfirm', { run: runId, node: nodeId }),
            buttons: [
                { label: I18n.t('ai.rerunNode'), value: true, primary: true },
                { label: I18n.t('ai.close'), value: false },
            ],
            cancelValue: false,
        });
        if (answer !== true) return false;
        try {
            const response = await fetch('/api/ai/rerun', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    conversation_id: this._conversationId,
                    run_id: runId,
                    workflow_name: workflowName,
                    node_id: nodeId,
                }),
            });
            const data = await response.json();
            if (!data.ok) {
                this._toast(I18n.t('ai.rerunFailed', { detail: data.error || I18n.t('ai.error') }));
                return false;
            }
            this._markRerunStarted(data.run_id || runId, data.node_id || nodeId, data.workflow_name || workflowName);
            this._paintAssistant();
            this._toast(data.message || I18n.t('ai.rerunStarted', { node: nodeId }));
            return true;
        } catch (error) {
            this._toast(I18n.t('ai.rerunFailed', { detail: error.message }));
            return false;
        }
    },

    /* The skill row expands into what the skill ACTUALLY carries: its prompt, context sources and
       tools. Fetched on first open, so a long prompt costs nothing until it is asked for. */
    async _loadSkillDetail(el) {
        const body = el.querySelector('.ai-skill-body');
        if (!body || body.getAttribute('data-loaded') === '1') return;
        const id = el.getAttribute('data-ai-skill') || '';
        /* `data-loaded` is set only AFTER the answer arrives: marking it first made one failed
           request permanent — every later click returned early and the row could never load. */
        body.setAttribute('data-loading', '1');
        body.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.skillLoading')) + '</div>';
        try {
            const response = await fetch('/api/ai/skills/' + encodeURIComponent(id));
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || ('HTTP ' + response.status));
            const skill = data.skill || {};
            const context = (skill.context || []).join(', ') || '—';
            const tools = (skill.tools || []).join(', ') || '—';
            body.innerHTML =
                '<p class="ai-skill-prompt">' + AIRender.escape(String(skill.prompt || '')) + '</p>' +
                '<div class="ai-skill-meta"><span>' + AIRender.escape(I18n.t('ai.skillContext')) + ': ' +
                AIRender.escape(context) + '</span><span>' + AIRender.escape(I18n.t('ai.skillTools')) + ': ' +
                AIRender.escape(tools) + '</span></div>';
            body.setAttribute('data-loaded', '1');
        } catch (error) {
            body.removeAttribute('data-loading');
            body.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.skillLoadFailed')) + '</div>';
        }
    },

    /* A plan or a chart spec has no mechanical "apply" of its own: the honest action is to ask the
       assistant to BUILD it with the same validated tools (apply_workflow, workspace_write), so the
       card is a proposal that can become a canvas rather than a dead frame. */
    _implementArtifact(id) {
        const artifact = (this._artifactsById || {})[id] || null;
        const title = String((artifact && artifact.title) || id || '');
        this._sendText(I18n.t('ai.artifactImplementAsk', { title: title }), {});
    },

    _copyAnswer(target) {
        const message = target.closest('.ai-message');
        const flow = message ? message.querySelector('.ai-flow') : null;
        const text = flow ? String(flow.innerText || '').trim() : '';
        if (!text) return;
        const done = () => this._toast(I18n.t('ai.copied'));
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done).catch(() => this._copyFallback(text, done));
            return;
        }
        this._copyFallback(text, done);
    },

    _copyFallback(text, done) {
        /* A page served over plain HTTP has no Clipboard API; the old textarea path still works
           and is the difference between "copy" and a button that silently does nothing. */
        const area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', 'readonly');
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        let copied = false;
        try {
            copied = document.execCommand('copy');
        } catch (error) {
            copied = false;
        }
        document.body.removeChild(area);
        if (copied) done();
    },

    async retry() {
        if (this._sending || !this._conversationId) return;
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        const key = AISettings.keyFor(this._provider);
        if (provider?.requires_key && !key) {
            this._toast(I18n.t('ai.keyMissing'));
            this.openSettings();
            return;
        }
        this._current = null;
        this._beginTurn();
        this._sending = true;
        this._setSending(true);
        try {
            await this._stream('/api/ai/retry', { conversation_id: this._conversationId, api_key: key });
        } catch (error) {
            if (error.name !== 'AbortError') this._renderError(error.message);
        } finally {
            this._sending = false;
            this._setSending(false);
            this._stopClock();
            this._noteCutStream();
            this._paintAssistant();
        }
    },

    jumpLatest() {
        if (!this._dom.chat) return;
        this._dom.chat.scrollTop = this._dom.chat.scrollHeight;
        if (this._dom.jump) this._dom.jump.hidden = true;
    },

    _onChatScroll() {
        const chat = this._dom.chat;
        const jump = this._dom.jump;
        if (!chat || !jump) return;
        const away = chat.scrollHeight - chat.scrollTop - chat.clientHeight > 120;
        jump.hidden = !away;
    },

    _workflowFeedback(title, detail) {
        const turn = this._feedbackTurn || '';
        if (this._sending || (turn && turn === (this._current && this._current.turnId))) return;
        this._feedbackTurn = (this._current && this._current.turnId) || 'pending';
        /* Three attempts is already a conversation about a broken draft, not a retry loop the user
           did not ask for. After that the failure stays on screen for them to decide. */
        this._feedbackCount = (this._feedbackCount || 0) + 1;
        const text = I18n.t('ai.feedback.workflow', { name: title || 'AI', detail: detail || '—' });
        this._renderError(text);
        if (this._feedbackCount > 3) return;
        this._sendText(text, { feedback: true });
    },

    _onChange(event) {
        const target = event.target;
        if (target && target.hasAttribute('data-ai-local-only')) {
            const on = !!target.checked;
            AISettings.save({ localOnly: on });
            if (on && this._provider !== 'ollama') {
                this._provider = 'ollama';
                AISettings.setProvider('ollama');
                this._model = AISettings.modelFor('ollama', this._bootstrap?.providers);
                AISettings.setModel('ollama', this._model);
                this._renderSettings();
                this._renderModelOptions();
                this._renderToggles();
            }
            this._toast(I18n.t(on ? 'ai.localOnlyOn' : 'ai.localOnlyOff'));
            return;
        }
        if (target && target.hasAttribute('data-ai-switch-provider')) {
            this._provider = target.value;
            AISettings.setProvider(this._provider);
            this._model = AISettings.modelFor(this._provider, this._bootstrap?.providers);
            this._renderModelOptions();
            this._renderToggles();
            this._renderSettings();
            return;
        }
        if (target && target.hasAttribute('data-ai-switch-model')) {
            this._model = target.value;
            AISettings.setModel(this._provider, this._model);
            return;
        }
        if (target && target.hasAttribute('data-ai-scope')) {
            this._scope = target.value;
            AISettings.save({ scope: this._scope });
            // One owner for one fact: the server setting is what the next page load reads, so the
            // studio's choice is written there instead of living only in localStorage.
            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: { ai_context_scope: this._scope } }),
            }).catch(() => {});
        }
    },

    _findByData(root, attribute, value) {
        return Array.from(root.querySelectorAll('[' + attribute + ']')).find((el) => el.getAttribute(attribute) === String(value));
    },

    _onClick(event) {
        /* A click with no target (a synthetic event from a harness or a detached node) is nothing. */
        if (!event || !event.target) return;
        /* A tool card's own row toggles its result BEFORE the data-action lookup: the row carries no
           data-ai-* attribute, and clicking the result's body must not close what it points at. */
        const raw = event.target;
        const card = raw && raw.closest ? raw.closest('.ai-tool') : null;
        if (card && !(raw.closest('summary')) && !(raw.closest('details')) && !(raw.closest('button'))) {
            const detail = card.querySelector('details.ai-tool-detail');
            if (detail) {
                this._setDetailOpen(detail, detail.open !== true);
                return;
            }
        }
        const target = event.target.closest('[data-ai-suggest],[data-ai-conversation],[data-ai-new-session],[data-ai-rename-conversation],[data-ai-delete-conversation],[data-ai-context-refresh],[data-ai-context-preview],[data-ai-cmd],[data-ai-agents],[data-ai-context-apply],[data-ai-manual],[data-ai-answer],[data-ai-send-custom],[data-ai-copy-artifact],[data-ai-apply-skill],[data-ai-apply-plugin],[data-ai-apply-chart],[data-ai-apply-workflow],[data-ai-run-workflow],[data-ai-copy-answer],[data-ai-retry],[data-ai-jump],[data-ai-folder-open],[data-ai-folder-root],[data-ai-folder-native],[data-ai-folder-use],[data-ai-folder-clear],[data-ai-folder-close],[data-ai-apply-monitor],[data-ai-watch-only],[data-ai-disarm-monitor],[data-ai-remove-attachment],[data-ai-ref],[data-ai-remove-ref],[data-ai-remove-answer-ref],[data-ai-skill],[data-ai-rerun-node],[data-ai-studio-tab],[data-ai-python-new],[data-ai-python-edit],[data-ai-python-save],[data-ai-python-cancel],[data-ai-python-delete],[data-ai-python-fork],[data-ai-python-run],[data-ai-python-install],[data-ai-fork],[data-ai-edit-skill],[data-ai-delete-skill],[data-ai-new-skill],[data-ai-save-skill],[data-ai-cancel-skill],[data-ai-toggle-plugin],[data-ai-delete-plugin],[data-ai-install-plugin],[data-ai-studio-close],[data-ai-provider-select],[data-ai-refresh-models],[data-ai-spend-refresh],[data-ai-implement-artifact],[data-ai-test],[data-ai-save-settings],[data-ai-scope],[data-ai-switch-provider],[data-ai-switch-model],[data-ai-switch-skill],[data-ai-pin-conversation],[data-ai-archive-conversation],[data-ai-export-conversation],[data-ai-toggle-archived],[data-ai-memory-add],[data-ai-memory-delete],[data-ai-apply-memory]');
        if (!target) return;
        if (target.hasAttribute('data-ai-suggest')) {
            this._skill = target.getAttribute('data-ai-suggest');
            AISettings.save({ skill: this._skill });
            this._renderSkillOptions();
            this._dom.input.focus();
            return;
        }
        if (target.hasAttribute('data-ai-conversation')) {
            this.selectConversation(target.getAttribute('data-ai-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-new-session')) {
            this.newChat();
            if (this._sessionsOpen) this.toggleSessions();
            return;
        }
        if (target.hasAttribute('data-ai-rename-conversation')) {
            this._renameConversation(target.getAttribute('data-ai-rename-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-delete-conversation')) {
            this._deleteConversation(target.getAttribute('data-ai-delete-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-pin-conversation')) {
            this._toggleConversationPin(target.getAttribute('data-ai-pin-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-archive-conversation')) {
            this._toggleConversationArchive(target.getAttribute('data-ai-archive-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-export-conversation')) {
            this._exportConversation(target.getAttribute('data-ai-export-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-toggle-archived')) {
            this._showArchived = !this._showArchived;
            this._refreshConversations();
            return;
        }
        if (target.hasAttribute('data-ai-context-refresh')) {
            this._renderContextBar();
            return;
        }
        if (target.hasAttribute('data-ai-context-preview')) {
            this._previewContext();
            return;
        }
        if (target.closest('[data-ai-skill]')) {
            this._loadSkillDetail(target.closest('[data-ai-skill]'));
        }
        if (target.hasAttribute('data-ai-agents')) {
            this.setAgentMode(target.getAttribute('data-ai-agents'));
            return;
        }
        if (target.hasAttribute('data-ai-cmd')) {
            this._runCommand(target.getAttribute('data-ai-cmd'));
            return;
        }
        if (target.hasAttribute('data-ai-context-apply')) {
            const dataset = this._dom.side.querySelector('[data-ai-manual="dataset_id"]');
            const run = this._dom.side.querySelector('[data-ai-manual="run_id"]');
            AIContext.setManual({ dataset_id: dataset?.value || '', run_id: run?.value || '' });
            this._renderContextBar();
            this._toast(I18n.t('ai.saved'));
            return;
        }
        if (target.hasAttribute('data-ai-answer')) {
            this._answerOption(target.getAttribute('data-ai-question'), target.getAttribute('data-ai-answer'));
            return;
        }
        if (target.hasAttribute('data-ai-send-custom')) {
            const questionId = target.getAttribute('data-ai-send-custom');
            const box = this._findByData(this._dom.chat, 'data-ai-custom', questionId);
            this._answerCustom(questionId, box ? box.value : '');
            return;
        }
        if (target.hasAttribute('data-ai-copy-artifact')) {
            const id = target.getAttribute('data-ai-copy-artifact');
            const artifact = (this._current?.artifacts || []).find((item) => item.id === id);
            if (artifact) this._copyText(JSON.stringify(artifact.payload || {}, null, 2));
            return;
        }
        if (target.hasAttribute('data-ai-apply-skill')) {
            this._applySkillArtifact(target.getAttribute('data-ai-apply-skill'));
            return;
        }
        if (target.hasAttribute('data-ai-apply-plugin')) {
            this._applyPluginArtifact(target.getAttribute('data-ai-apply-plugin'));
            return;
        }
        if (target.hasAttribute('data-ai-apply-memory')) {
            this._applyMemoryArtifact(target.getAttribute('data-ai-apply-memory'));
            return;
        }
        if (target.hasAttribute('data-ai-apply-workflow') || target.hasAttribute('data-ai-run-workflow')) {
            const run = target.hasAttribute('data-ai-run-workflow');
            const id = target.getAttribute(run ? 'data-ai-run-workflow' : 'data-ai-apply-workflow');
            const artifact = (this._artifactsById || {})[id] || (this._current?.artifacts || []).find((item) => item.id === id);
            if (!artifact) {
                this._toast(I18n.t('ai.error'));
                return;
            }
            this._applyWorkflowPayload(artifact.payload || {}, run, artifact.title || '');
            return;
        }
        if (target.hasAttribute('data-ai-apply-chart')) {
            this._applyChartArtifact(target.getAttribute('data-ai-apply-chart'));
            return;
        }
        if (target.hasAttribute('data-ai-copy-answer')) {
            this._copyAnswer(target);
            return;
        }
        if (target.hasAttribute('data-ai-retry')) {
            this.retry();
            return;
        }
        if (target.hasAttribute('data-ai-folder-open')) {
            this._openFolder(target.getAttribute('data-ai-folder-open'));
            return;
        }
        if (target.hasAttribute('data-ai-folder-root')) {
            this._openFolder(target.getAttribute('data-ai-folder-root'));
            return;
        }
        if (target.hasAttribute('data-ai-folder-native')) {
            this._pickNativeFolder();
            return;
        }
        if (target.hasAttribute('data-ai-folder-use')) {
            this._setFolder(target.getAttribute('data-ai-folder-use'));
            return;
        }
        if (target.hasAttribute('data-ai-folder-clear')) {
            this._setFolder('');
            return;
        }
        if (target.hasAttribute('data-ai-folder-close')) {
            if (this._dom.folderDialog) this._dom.folderDialog.hidden = true;
            return;
        }
        if (target.hasAttribute('data-ai-apply-monitor')) {
            this._applyMonitor(target.getAttribute('data-ai-apply-monitor'), true);
            return;
        }
        if (target.hasAttribute('data-ai-watch-only')) {
            this._applyMonitor(target.getAttribute('data-ai-watch-only'), false);
            return;
        }
        if (target.hasAttribute('data-ai-disarm-monitor')) {
            this._disarmMonitor(target.getAttribute('data-ai-disarm-monitor'));
            return;
        }
        if (target.hasAttribute('data-ai-remove-attachment')) {
            this._removeAttachment(target.getAttribute('data-ai-remove-attachment'));
            return;
        }
        if (target.hasAttribute('data-ai-ref')) {
            const [kind, id] = String(target.getAttribute('data-ai-ref') || '').split('|');
            const row = this._refResults.find((item) => item.kind === kind && item.id === id) || {};
            this._pickRef(kind, id, row.label || id);
            return;
        }
        if (target.hasAttribute('data-ai-remove-ref')) {
            const [kind, id] = String(target.getAttribute('data-ai-remove-ref') || '').split('|');
            this._removeRef(kind, id);
            return;
        }
        if (target.hasAttribute('data-ai-remove-answer-ref')) {
            const [kind, id, questionId] = String(target.getAttribute('data-ai-remove-answer-ref') || '').split('|');
            const rows = this._answerRefs(questionId).filter((row) => !(row.kind === kind && row.id === id));
            if (this._current && this._current.answerRefs) this._current.answerRefs[String(questionId)] = rows;
            this._renderAnswerRefs(questionId);
            return;
        }
        if (target.hasAttribute('data-ai-rerun-node')) {
            this._rerunFailedNode(
                target.getAttribute('data-ai-rerun-run'),
                target.getAttribute('data-ai-rerun-node'),
                target.getAttribute('data-ai-rerun-workflow')
            );
            return;
        }
        if (target.hasAttribute('data-ai-memory-add')) {
            AIStudio.saveMemory(this);
            return;
        }
        if (target.hasAttribute('data-ai-memory-delete')) {
            AIStudio.deleteMemory(this, target.getAttribute('data-ai-memory-delete'));
            return;
        }
        if (target.hasAttribute('data-ai-python-new')) {
            AIStudio.newPython(this);
            return;
        }
        if (target.hasAttribute('data-ai-python-edit')) {
            AIStudio.editPython(this, target.getAttribute('data-ai-python-edit'));
            return;
        }
        if (target.hasAttribute('data-ai-python-save')) {
            AIStudio.savePython(this);
            return;
        }
        if (target.hasAttribute('data-ai-python-cancel')) {
            this._pythonScript = null;
            this.openStudio('python');
            return;
        }
        if (target.hasAttribute('data-ai-python-delete')) {
            AIStudio.deletePython(this, target.getAttribute('data-ai-python-delete'));
            return;
        }
        if (target.hasAttribute('data-ai-python-fork')) {
            AIStudio.forkPython(this, target.getAttribute('data-ai-python-fork'));
            return;
        }
        if (target.hasAttribute('data-ai-python-run')) {
            AIStudio.runPython(this);
            return;
        }
        if (target.hasAttribute('data-ai-python-install')) {
            AIStudio.installPython(this);
            return;
        }
        if (target.hasAttribute('data-ai-studio-tab')) {
            this._studioTab = target.getAttribute('data-ai-studio-tab');
            AIStudio.render(this._dom.chat, this);
            if (this._studioTab === 'python' && typeof AIStudio.loadPython === 'function') AIStudio.loadPython(this);
            if (this._studioTab === 'memory' && typeof AIStudio.loadMemory === 'function') AIStudio.loadMemory(this);
            return;
        }
        if (target.hasAttribute('data-ai-studio-close')) {
            this._mode = 'chat';
            this._editingSkill = null;
            this._renderMessages();
            return;
        }
        if (target.hasAttribute('data-ai-new-skill')) {
            this._editingSkill = { id: '', name: '', prompt: '', context: [], tools: [], suggested: [], ask_policy: 'auto' };
            AIStudio.render(this._dom.chat, this);
            return;
        }
        if (target.hasAttribute('data-ai-edit-skill')) {
            const id = target.getAttribute('data-ai-edit-skill');
            const skill = (this._bootstrap?.skills || []).find((item) => item.id === id);
            this._editingSkill = skill ? Object.assign({}, skill, { prompt: skill.prompt || '' }) : null;
            this._loadSkillForEdit(id);
            return;
        }
        if (target.hasAttribute('data-ai-fork')) {
            this._forkSkill(target.getAttribute('data-ai-fork'));
            return;
        }
        if (target.hasAttribute('data-ai-delete-skill')) {
            this._deleteSkill(target.getAttribute('data-ai-delete-skill'));
            return;
        }
        if (target.hasAttribute('data-ai-save-skill')) {
            this._saveSkillFromEditor();
            return;
        }
        if (target.hasAttribute('data-ai-cancel-skill')) {
            this._editingSkill = null;
            AIStudio.render(this._dom.chat, this);
            return;
        }
        if (target.hasAttribute('data-ai-toggle-plugin')) {
            this._togglePlugin(target.getAttribute('data-ai-toggle-plugin'), target.getAttribute('data-ai-enabled') === '1');
            return;
        }
        if (target.hasAttribute('data-ai-delete-plugin')) {
            this._deletePlugin(target.getAttribute('data-ai-delete-plugin'));
            return;
        }
        if (target.hasAttribute('data-ai-install-plugin')) {
            this._installPlugin();
            return;
        }
        if (target.hasAttribute('data-ai-provider-select')) {
            this._provider = target.value;
            AISettings.setProvider(this._provider);
            this._model = AISettings.modelFor(this._provider, this._bootstrap?.providers);
            this._renderModelOptions();
            this._renderToggles();
            return;
        }
        if (target.hasAttribute('data-ai-switch-provider')) {
            this._provider = target.value;
            AISettings.setProvider(this._provider);
            this._model = AISettings.modelFor(this._provider, this._bootstrap?.providers);
            this._renderModelOptions();
            return;
        }
        if (target.hasAttribute('data-ai-switch-model')) {
            this._model = target.value;
            AISettings.setModel(this._provider, this._model);
            return;
        }
        if (target.hasAttribute('data-ai-switch-skill')) {
            this._skill = target.value;
            AISettings.save({ skill: this._skill });
            return;
        }
        if (target.hasAttribute('data-ai-scope')) {
            this._scope = target.value;
            AISettings.save({ scope: this._scope });
            return;
        }
        /* The settings page's three buttons. They were in the delegated selector above but had no
           branch here, so clicking 保存 (the only place the API key is typed) did nothing at all —
           no toast, no request, no error. Pinned by harness_ai_workspace.mjs. */
        if (target.hasAttribute('data-ai-save-settings')) {
            this._saveSettings();
            return;
        }
        if (target.hasAttribute('data-ai-refresh-models')) {
            this._refreshModels();
            return;
        }
        if (target.hasAttribute('data-ai-spend-refresh')) {
            this._loadSpend();
            return;
        }
        if (target.hasAttribute('data-ai-implement-artifact')) {
            this._implementArtifact(target.getAttribute('data-ai-implement-artifact'));
            return;
        }
        if (target.hasAttribute('data-ai-test')) {
            this._testProvider();
            return;
        }
    },

    async _previewContext() {
        /* One preview, toggled: every click used to PREPEND another copy of the same section, so
           the side panel filled with duplicates and the button never became "hide". The text is
           kept here (not in the DOM) because `_renderSide` rebuilds the panel after every turn. */
        if (this._contextPreview) {
            this._contextPreview = '';
            this._renderSide();
            return;
        }
        const query = this._dom.input?.value || '';
        const context = AIContext.collect();
        try {
            let endpoint = '/api/ai/context';
            let body = { query, context };
            if (this._conversationId) {
                endpoint = '/api/ai/conversations/' + encodeURIComponent(this._conversationId) + '/context';
            }
            const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'context failed');
            this._contextMeta = data.meta || {};
            this._contextPreview = String(data.context || '');
            this._renderSide();
        } catch (error) {
            this._toast(I18n.t('ai.error') + ': ' + error.message);
        }
    },

    async selectConversation(id) {
        if (!id) return;
        /* The turn in flight owns this DOM. Re-selecting the same conversation while it streams
           (which is what reopening the dock does) would repaint from the store and drop the live
           bubble, so the answer would continue in a second bubble. */
        if (this._sending && String(id) === String(this._conversationId)) return;
        this._conversationId = id;
        this._mode = 'chat';
        this._editingSkill = null;
        try {
            const response = await fetch('/api/ai/conversations/' + encodeURIComponent(id));
            const data = await response.json();
            if (!data.ok) {
                /* A conversation deleted here or in another tab: forget it instead of reopening a
                   chat that no longer exists on every reload. */
                if (response.status === 404) {
                    this._conversationId = '';
                    this._rememberConversation('');
                    this._renderWelcome();
                    return;
                }
                throw new Error(data.error || 'not found');
            }
            this._messages = data.messages || [];
            this._conversationId = data.conversation.id;
            this._rememberConversation(this._conversationId);
            /* The header names the model this conversation used; the picker below keeps the model
               the NEXT message will use, which may be a different one. */
            this._conversationModel = [data.conversation.provider, data.conversation.model].filter(Boolean).join(' / ');
            this._renderMessages(data.pending_questions || []);
            this._renderSessions();
            this._renderSide();
            this._loadSpend();
            if (this._dom.title) {
                this._dom.title.textContent = data.conversation.title || I18n.t('ai.title');
                this._dom.title.title = this._conversationModel;
            }
        } catch (error) {
            this._toast(I18n.t('ai.error') + ': ' + error.message);
        }
    },

    _autoGrow() {
        const input = this._dom.input;
        if (!input) return;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight || 0, 220) + 'px';
        this._syncComposerHeight();
    },

    /* The “back to the latest message” button is anchored ABOVE the composer, and the composer grows
       with the textarea — a fixed `bottom: 96px` put the button on top of the composer's own row.
       Its measured height is published as `--ai-composer-h`, which the stylesheet reads. */
    _syncComposerHeight() {
        const root = this._dom.root;
        if (!root || typeof root.querySelector !== 'function') return;
        const composer = root.querySelector('.ai-composer');
        const rect = composer && composer.getBoundingClientRect ? composer.getBoundingClientRect() : null;
        const height = rect && rect.height ? Math.round(rect.height) : 0;
        if (height > 0) root.style.setProperty('--ai-composer-h', height + 'px');
    },

    /* The transcript the user was reading survives a reload: the id is browser-local state, the
       messages stay on the server. A conversation deleted elsewhere is cleared when its fetch 404s
       (``selectConversation``), not silently reopened forever. */
    _restoreConversation() {
        if (!this._conversationId) {
            const saved = String(AISettings.load().conversation || '');
            if (saved) this._conversationId = saved;
        }
        return this._conversationId;
    },

    _rememberConversation(id) {
        AISettings.save({ conversation: String(id || '') });
    },

    _showChat() {
        /* Settings and the studio paint into the same column as the transcript. Sending while one
           of them is up used to look inerta: the click ran, the panel stayed on settings, and the
           user saw no reaction at all. A send always returns to the conversation first. */
        if (this._mode === 'chat') return;
        this._mode = 'chat';
        if (this._dom.chat) this._dom.chat.innerHTML = '';
        this._renderMessages();
    },

    _renderMessages(pending) {
        if (!this._dom.chat) return;
        this._mode = 'chat';
        this._dom.chat.innerHTML = '';
        /* The live turn's element lived in the DOM just wiped. Keeping the pointer made a pending
           question paint into a DETACHED node — the card was built and never visible, which reads
           as “my question disappeared after the reload”. */
        this._current = null;
        if (!this._messages.length) {
            this._renderWelcome();
            return;
        }
        /* Tool calls already drawn INSIDE their assistant bubble (a `tool_use` block). Their `tool`
           row must not draw a second, detached card between bubbles — that was the misaligned box
           above every "AI" label. Rows we render in their own right (an answered question, an
           artifact) stay. */
        this._inlineToolCalls = new Set();
        for (const message of this._messages) {
            if (message.role !== 'assistant') continue;
            for (const block of message.blocks || []) {
                if (block && block.type === 'tool_use' && block.id) this._inlineToolCalls.add(String(block.id));
            }
        }
        /* A turn is SEVERAL stored assistant rows — one per provider round — all sharing a
           turn_id. The live view draws one bubble for the whole turn, so the reopened transcript
           must too: grouping by turn_id is what makes “while it streams” and “after it finished”
           the same picture. Round-per-bubble was the screenshot with a detached card above every
           “AI”. */
        const order = [];
        const turns = new Map();
        /* A tool RESULT is stored in its own `tool` row, never inside the assistant's `tool_use`
           block. Live the block carries it (the event sets `result`), so a reloaded card had no
           `result`, therefore no `<details>` — a card that could not be opened. The rows are folded
           back into their blocks here, before anything is painted. */
        const toolPayloads = new Map();
        const turnFor = (message) => {
            const meta = message.meta || {};
            const turnId = String(meta.turn_id || message.id || '');
            let turn = turns.get(turnId);
            if (!turn) {
                turn = { kind: 'turn', turnId: turnId, messageId: message.id, blocks: [], usage: null, error: '', extras: [] };
                turns.set(turnId, turn);
                order.push(turn);
            }
            return turn;
        };
        for (const message of this._messages) {
            if (message.role === 'user') {
                order.push({ kind: 'user', message: message });
                continue;
            }
            if (message.role === 'assistant') {
                const turn = turnFor(message);
                turn.blocks.push(...(message.blocks || []));
                if (message.usage && Object.keys(message.usage).length) turn.usage = message.usage;
                const error = String((message.meta || {}).error || '');
                if (error) turn.error = error;
                /* The turn's LAST row carries the turn's verdict: an intermediate round cut at
                   `max_tokens` and then recovered is not a truncated answer. */
                turn.stopReason = String((message.meta || {}).stop_reason || '');
                /* ...and its status: a row still `streaming` or already `interrupted` means the
                   answer never reached its ending. Reopening such a conversation used to show a
                   half answer with nothing to say it was half — the reader could only guess
                   between "it finished" and "it broke". */
                turn.status = String(message.status || '');
                continue;
            }
            if (message.role !== 'tool') continue;
            const meta = message.meta || {};
            const callId = String(meta.tool_call_id || '');
            const inline = !!(callId && this._inlineToolCalls.has(callId));
            if (callId && inline) {
                let payload = message.content || null;
                try {
                    payload = JSON.parse(payload);
                } catch (e) {
                    /* a plain-text tool output stays a string; the card shows it verbatim */
                }
                toolPayloads.set(callId, { payload: payload, isError: !!meta.is_error });
            }
            if (!this._isStandaloneToolRow(message, inline)) continue;
            const turnId = String(meta.turn_id || '');
            const turn = turnId ? turns.get(turnId) : null;
            if (turn) turn.extras.push(message);
            else order.push({ kind: 'tool', message: message });
        }
        for (const turn of turns.values()) {
            if (turn.stopReason === 'max_tokens') turn.truncated = true;
            if (turn.stopReason === 'cancelled') turn.stopped = true;
            /* The last row never reached an ending: say WHICH fact it is, because they are not the
               same. `streaming` may still be running in another page; `interrupted` is the server's
               own verdict on a turn whose reader (or process) went away. */
            if (turn.status === 'interrupted') turn.interrupted = true;
            else if (turn.status === 'streaming') turn.live = true;
            for (const block of turn.blocks) {
                if (!block || block.type !== 'tool_use') continue;
                const found = toolPayloads.get(String(block.id || ''));
                if (!found) continue;
                block.status = found.isError ? 'failed' : 'done';
                block.result = found.payload;
            }
        }
        for (const item of order) {
            if (item.kind === 'user') this._appendUser(item.message.content, item.message.meta?.context, item.message.meta?.attachments, null, false);
            else if (item.kind === 'turn') this._renderTurn(item);
            else this._renderStoredTool(item.message);
        }
        for (const question of pending || []) {
            this._appendQuestion(question);
        }
        this._dom.chat.scrollTop = this._dom.chat.scrollHeight;
    },

    /* One stored row that deserves its own element: an answered/abandoned question (the answer is
       part of the transcript), an artifact (its card exists nowhere else), or a tool call whose
       assistant block is missing. Everything else was already drawn inline. */
    _isStandaloneToolRow(message, inline) {
        let payload = message.content || '';
        try {
            payload = JSON.parse(payload);
        } catch (e) {
            payload = null;
        }
        if (payload && payload.tool === 'ask_user_question' && (payload.cancelled || Array.isArray(payload.answers))) return true;
        if (payload && payload.artifact) return true;
        const meta = message.meta || {};
        return !inline && !!meta.name && meta.name !== 'update_plan';
    },

    _renderTurn(turn) {
        const el = document.createElement('article');
        el.className = 'ai-message assistant';
        if (turn.messageId) el.setAttribute('data-ai-message', turn.messageId);
        el.innerHTML =
            '<div class="ai-message-role">' + AIRender.escape(I18n.t('ai.assistant')) + '</div><div class="ai-message-body">' +
            '<div class="ai-flow">' + AIRender.assistantFlow(turn.blocks) + '</div>' +
            /* A turn that ENDED in an error is part of the transcript: the reason was painted into
               this page once and then lost on every reload, so a user reopening the conversation
               saw a silent gap where the provider had said exactly what was wrong. */
            (turn.error ? '<div class="ai-error-text">' + AIRender.escape(turn.error) + '</div>' : '') +
            /* A turn cut by the output limit is not an error, but it is not a finished answer
               either: the sentence stopped mid-way and the provider said so. A STOPPED turn is the
               same kind of fact, and used to come back as a red error line. */
            (turn.truncated ? '<div class="ai-note">' + AIRender.escape(I18n.t('ai.truncated')) + '</div>' : '') +
            (turn.stopped ? '<div class="ai-note">' + AIRender.escape(I18n.t('ai.stopped')) + '</div>' : '') +
            (turn.interrupted ? '<div class="ai-note">' + AIRender.escape(I18n.t('ai.interrupted')) + '</div>' : '') +
            (turn.live ? '<div class="ai-note">' + AIRender.escape(I18n.t('ai.stillStreaming')) + '</div>' : '') +
            '<div class="ai-extras"></div>' +
            '<div class="ai-usage">' + AIRender.usage(turn.usage || {}) + '</div>' +
            '<div class="ai-message-actions">' +
            '<button type="button" class="ai-ghost" data-ai-copy-answer="1">' + AIRender.escape(I18n.t('ai.copyAnswer')) + '</button>' +
            '<button type="button" class="ai-ghost" data-ai-retry="1">' + AIRender.escape(I18n.t('ai.retry')) + '</button>' +
            '</div>' +
            '</div>';
        this._dom.chat.appendChild(el);
        const extras = el.querySelector('.ai-extras');
        for (const message of turn.extras) {
            const node = this._storedRowNode(message);
            if (node && extras) extras.appendChild(node);
        }
        this._applyOpenDetails(el);
    },

    /* A stored row that stands on its own (an answered question, an artifact) still belongs in the
       assistant's COLUMN: `.ai-message` is a role + body grid, and appending a bare card put it at
       the panel's left edge, above the next "AI" label. */
    _wrapStoredRow(el) {
        if (!el) return;
        const article = document.createElement('article');
        article.className = 'ai-message assistant ai-message-tool';
        article.innerHTML = '<div class="ai-message-role"></div><div class="ai-message-body"></div>';
        const body = article.querySelector('.ai-message-body');
        if (body) body.appendChild(el);
        else article.appendChild(el);
        this._dom.chat.appendChild(article);
        this._applyOpenDetails(article);
    },

    /* The element for one standalone stored row, or null when it has no rendering of its own. */
    _storedRowNode(message) {
        let payload = message.content || '';
        try {
            payload = JSON.parse(payload);
        } catch (e) {
            /* plain text tool output is shown verbatim */
        }
        const meta = message.meta || {};
        /* An answered (or abandoned) question is its own row: what was ASKED and what was
           ANSWERED are both part of the transcript, so a reload must not reduce it to a bare
           “answered” line — the question text used to vanish with the live card. */
        const answers = payload && Array.isArray(payload.answers) ? payload.answers : null;
        const cancelled = !!(payload && payload.cancelled);
        if ((answers || cancelled) && payload.tool === 'ask_user_question') {
            const chosen = answers ? answers.flatMap((item) => (item && item.selected) || []).filter(Boolean).join(', ') : '';
            const asked = (payload.questions || []).filter((item) => item && item.question);
            const approval = asked.some((item) => String(item.kind || '') === 'approval');
            let picked = {};
            let preview = '';
            if (approval) {
                const question = asked.find((item) => String(item.kind || '') === 'approval') || {};
                picked = (question.options || []).find((option) => option && option.label === chosen) || {};
                /* The answered row is what a reload shows: keep the exact target visible there too,
                   or the card would reduce an approved file write to “this call was answered”. */
                preview = AIRender.approvalPreview(question.preview);
            }
            const el = document.createElement('section');
            el.className = 'ai-question' + (approval ? ' ai-question-approval' : '');
            const lines = asked.map((item) => '<p class="ai-question-text">' + AIRender.escape(String(item.question)) + '</p>');
            let verdict = I18n.t('ai.questionUnansweredRow');
            if (cancelled) verdict = I18n.t('ai.questionCancelled');
            else if (String(picked.value || '') === 'deny') verdict = I18n.t('ai.approvalDenied');
            else if (chosen) {
                verdict = (approval ? I18n.t('ai.approvalAnswered') : I18n.t('ai.questionAnswered')) + ': ' + chosen;
            }
            el.innerHTML =
                '<div class="ai-question-head"><span class="ai-dot"></span>' +
                AIRender.escape((asked[0] && asked[0].header) || I18n.t('ai.questionTitle')) +
                '</div>' +
                lines.join('') +
                preview +
                '<div class="ai-question-answered">' + AIRender.escape(verdict) + '</div>';
            return el;
        }
        const artifact = payload && payload.artifact;
        if (artifact) {
            /* A reloaded transcript's artifacts must answer their own buttons: the payload lives in
               this row, not in an event, so it is remembered here as well. */
            this._artifactsById = this._artifactsById || {};
            if (artifact.id) this._artifactsById[artifact.id] = artifact;
            const holder = document.createElement('div');
            holder.innerHTML = AIRender.artifactCard(artifact);
            return holder.firstElementChild;
        }
        if (meta.name && meta.name !== 'update_plan') {
            const holder = document.createElement('div');
            holder.innerHTML = AIRender.toolCard(meta.name, {}, meta.is_error ? 'failed' : 'done', payload);
            return holder.firstElementChild;
        }
        return null;
    },

    _renderStoredTool(message) {
        const node = this._storedRowNode(message);
        if (node) this._wrapStoredRow(node);
    },

    _appendQuestion(question) {
        const current = this._ensureAssistant();
        this._current.questions = question.questions || [];
        this._current.answers = this._current.answers || {};
        this._current.questionId = question.id;
        this._current.questionMessageId = question.message_id;
        this._current.questionEl.innerHTML = this._current.questions.map((item) => AIRender.questionCard(item, false)).join('');
    },

    async send() {
        const text = (this._dom.input?.value || '').trim();
        /* Any early return inside `_sendText` says why (toast); a throw says why too. Silence is
           what makes a slow turn and a dead button look identical. */
        try {
            await this._sendText(text, {});
        } catch (error) {
            this._toast((I18n.t('ai.error') || '') + ': ' + String((error && error.message) || error));
        }
    },

    async _sendText(text, options) {
        const opts = options || {};
        if (this._sending) {
            if (!opts.monitor) this._toast(I18n.t('ai.busy'));
            return false;
        }
        if (!opts.monitor && !opts.feedback) this._feedbackCount = 0;
        /* A failed-node card belongs to the monitor turn that named the run; a user's own message
           starts a new turn and must not inherit the previous run's nodes. */
        if (!opts.monitor) this._monitorFailed = null;
        const pendingAttachments = opts.monitor ? [] : this._attachments.slice();
        const pendingRefs = opts.monitor ? [] : this._refs.slice();
        if (!text && !pendingAttachments.length && !pendingRefs.length) {
            this._toast(I18n.t('ai.emptyMessage'));
            return false;
        }
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        /* Local-only: a paid provider is refused BEFORE any request leaves the page. This is the
           switch that makes "I only want the free local model" enforceable, not a preference. */
        if (AISettings.load().localOnly && (!provider || !provider.local_only)) {
            this._toast(I18n.t('ai.localOnlyBlocked'));
            return false;
        }
        const key = AISettings.keyFor(this._provider);
        if (provider?.requires_key && !key) {
            this._toast(I18n.t('ai.keyMissing'));
            // A monitor turn has no user watching to fill the key: opening the settings panel every
            // five seconds was the retry loop's visible symptom. Say it once, let the watch give up.
            if (!opts.monitor) this.openSettings();
            return false;
        }
        if (!this._model) {
            this._toast(I18n.t('ai.modelMissing'));
            return false;
        }
        if (pendingAttachments.length && !(provider?.capabilities || []).includes('files')) {
            this._toast(I18n.t('ai.fileUnsupported'));
            return false;
        }
        if (pendingRefs.some((row) => row.kind === 'file') && !(provider?.capabilities || []).includes('files')) {
            this._toast(I18n.t('ai.fileUnsupported'));
            return false;
        }
        const context = opts.monitor ? {} : AIContext.collect();
        if (!opts.monitor) {
            this._dom.input.value = '';
            this._autoGrow();
            this._appendUser(text, context, pendingAttachments, { feedback: !!opts.feedback });
            this._attachments = [];
            this._renderAttachments();
            this._refs = [];
            this._renderRefs();
            this._contextPreview = '';
            this._renderSide();
        } else {
            this._appendUser(text, context, [], { monitor_event: opts.monitorEventId });
        }
        this._current = null;
        this._showChat();
        this._beginTurn();
        this._sending = true;
        this._setSending(true);
        /* The reaction is the point: the user must see their message AND a live turn before the
           first byte from the provider, otherwise a slow model looks like a dead button. */
        this._ensureAssistant();
        this._paintAssistant();
        if (this._dom.chat) this._dom.chat.scrollTop = this._dom.chat.scrollHeight;
        const body = {
            conversation_id: this._conversationId || '',
            text,
            provider: this._provider,
            model: this._model,
            api_key: key,
            thinking: this._thinkingOn(),
            web_search: !!AISettings.load().search && (provider?.capabilities || []).includes('web_search'),
            skill: this._skill || 'auto',
            locale: (typeof I18n !== 'undefined' && I18n.lang) || 'zh',
            context,
            scope: this._scope,
            attachments: pendingAttachments.map((row) => row.id),
            references: pendingRefs.map((row) => ({ kind: row.kind, id: row.id })),
            monitor_event_id: opts.monitorEventId || '',
            feedback: !!opts.feedback,
            agent_mode: this._agentMode || 'build',
        };
        try {
            await this._stream('/api/ai/chat', body);
        } catch (error) {
            if (error.name !== 'AbortError') this._renderError(error.message);
        } finally {
            this._sending = false;
            this._setSending(false);
            this._stopClock();
            this._noteCutStream();
        }
        return true;
    },

    async deliverMonitor(event) {
        const monitor = (this._bootstrap?.monitors || []).find((item) => item.id === event.monitor_id);
        const auto = !!monitor?.auto_analyze;
        if (!auto) {
            if (this._open && this._conversationId === event.conversation_id) {
                const meta = event.payload || {};
                this._appendUser(
                    I18n.t('ai.monitor.notice') + ': ' + String(meta.event || '') + ' · ' + String(meta.run_id || ''),
                    {},
                    [],
                    { monitor_event: event.id }
                );
            }
            this._toast(I18n.t('ai.monitor.armed') + ' · ' + I18n.t('ai.monitor.notice'));
            return true;
        }
        // A turn already streaming owns the transcript; leave the event pending so the next tick
        // delivers it after the answer, instead of interleaving two conversations.
        if (this._sending) return false;
        const target = String(event.conversation_id || '');
        if (target && target !== this._conversationId) {
            if (!this._open) this.open({ silent: true });
            await this.selectConversation(target);
        }
        const conversation = (this._bootstrap?.conversations || []).find((item) => item.id === (target || this._conversationId));
        if (conversation?.provider) {
            this._provider = conversation.provider;
            this._model = conversation.model || AISettings.modelFor(this._provider, this._bootstrap?.providers);
        }
        const facts = JSON.stringify(event.payload || {}, null, 2);
        const failed = ['failed', 'partial', 'stopped'].includes(String((event.payload || {}).outcome || (event.payload || {}).status || ''));
        if (failed) {
            // The card is built from the run this event names, not from whatever app_errors returns
            // first: a conversation may know about several runs.
            const payload = event.payload || {};
            this._monitorFailed = {
                run_id: String(payload.run_id || ''),
                workflow_name: String(payload.workflow || payload.workflow_name || ''),
                node_id: String(payload.node_id || ''),
                label: String(payload.label || ''),
            };
        } else {
            this._monitorFailed = null;
        }
        const tail = failed
            ? I18n.t('ai.monitor.promptFailure')
            : I18n.t('ai.monitor.promptAsk');
        const text = I18n.t('ai.monitor.promptHead') + '\n```json\n' + facts + '\n```\n' + tail;
        return this._sendText(text, { monitor: true, monitorEventId: event.id });
    },

    async _applyMonitor(artifactId, auto) {
        const artifact = (this._current?.artifacts || []).find((item) => item.id === artifactId);
        if (!artifact) return;
        try {
            const conversationId = await this._ensureConversation();
            const response = await fetch('/api/ai/monitors', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    conversation_id: conversationId,
                    spec: artifact.payload || {},
                    auto_analyze: !!auto,
                }),
            });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'monitor failed');
            this._bootstrap.monitors = [data.monitor, ...(this._bootstrap.monitors || [])];
            this._renderSide();
            this._toast(I18n.t('ai.monitor.armed'));
        } catch (error) {
            this._toast(I18n.t('ai.monitor.failed') + ': ' + error.message);
        }
    },

    async _disarmMonitor(monitorId) {
        try {
            await fetch('/api/ai/monitors/' + encodeURIComponent(monitorId), { method: 'DELETE' });
        } catch (error) {
            /* the row may already be retired; the list refresh below tells the truth */
        }
        this._bootstrap.monitors = (this._bootstrap?.monitors || []).filter((item) => item.id !== monitorId);
        this._renderSide();
    },

    async _stream(url, body) {
        this._abort = new AbortController();
        await AIStream.post(url, body, (event) => this._onEvent(event), this._abort.signal);
    },

    _setSending(sending) {
        if (this._dom.send) this._dom.send.disabled = sending;
        if (this._dom.stop) this._dom.stop.hidden = !sending;
        /* The composer stays ENABLED while a turn runs: disabling it threw away the caret and the
           user could not even draft the next message. A second send is refused by `_sendText` with
           one toast, which is a better answer than a dead input. */
        if (this._dom.input) this._dom.input.disabled = false;
        this._renderToggles();
        /* A closed turn no longer owns a conversation: the next one states its own. */
        if (!sending) this._streamConversation = '';
        /* The live line follows the same switch as the buttons: it is shown exactly while a turn is
           open. One funnel, so no ending path can leave "生成中" painted on a finished answer. */
        this._renderStatus();
    },

    _onEvent(event) {
        /* Any byte from the provider is proof of life; the live line's "no answer yet" wording and
           its seconds both hang off this. */
        this._lastEventAt = Date.now();
        const type = event.type;
        /* A turn belongs to the conversation that started it. Selecting another conversation while
           an answer streams is allowed (the dock stays usable), and the rest of that answer used to
           be painted into the NEW transcript — one conversation's words under another's question.
           Events for a conversation nobody is looking at are dropped; the store still has them. */
        const owner = String(this._streamConversation || '');
        if (owner && String(this._conversationId || '') !== owner) return;
        if (type === 'meta') {
            this._conversationId = event.conversation_id || this._conversationId;
            if (!this._streamConversation) this._streamConversation = this._conversationId;
            /* The first turn of a new chat learns its id here; remember it so a reload reopens THIS
               transcript instead of an empty page. */
            if (event.conversation_id) this._rememberConversation(this._conversationId);
            this._current = this._ensureAssistant();
            this._current.messageId = event.message_id;
            this._current.turnId = event.turn_id;
            this._current.runId = event.run_id;
            this._contextMeta = event.context || {};
            /* The server opens EVERY provider round with a meta event, and all rounds of one turn
               share the turn_id. The skill row describes the TURN, so pushing it per round printed
               “技能 · 画布建构师” twice in one answer. */
            if (event.skill && !this._current.blocks.some((block) => block.type === 'skill')) {
                this._current.blocks.push({ type: 'skill', name: String(event.skill), reason: String(event.skill_reason || '') });
            }
            this._renderSide();
            this._paintAssistant();
            if (event.skill_name_key) {
                const chip = this._dom.modelChip;
                if (chip) chip.title = I18n.has(event.skill_name_key) ? I18n.t(event.skill_name_key) : (event.skill || '');
            }
            return;
        }
        if (type === 'thinking') {
            const current = this._ensureAssistant();
            const text = event.text || '';
            if (!text) return;
            const last = current.blocks[current.blocks.length - 1];
            if (last && last.type === 'thinking') last.thinking += text;
            else current.blocks.push({ type: 'thinking', thinking: text });
            this._schedulePaint(current);
            return;
        }
        if (type === 'text') {
            const current = this._ensureAssistant();
            const text = event.text || '';
            if (!text) return;
            const last = current.blocks[current.blocks.length - 1];
            if (last && last.type === 'text') last.text += text;
            else current.blocks.push({ type: 'text', text: text });
            this._schedulePaint(current);
            return;
        }
        if (type === 'citation') {
            const current = this._ensureAssistant();
            const url = event.citation?.url || '';
            if (!url) return;
            current.blocks.push({ type: 'server_tool_use', id: 'cite:' + url, input: { action: 'read_link', url: url } });
            this._schedulePaint(current);
            return;
        }
        if (type === 'server_tool') {
            const current = this._ensureAssistant();
            const block = event.block || {};
            current.blocks.push(block);
            this._schedulePaint(current);
            return;
        }
        if (type === 'tool_start') {
            const current = this._ensureAssistant();
            current.blocks.push({
                type: 'tool_use',
                id: String(event.id || ''),
                name: String(event.name || ''),
                input: event.arguments || {},
                status: 'running',
                startedAt: Date.now(),
            });
            this._schedulePaint(current);
            return;
        }
        if (type === 'tool_result') {
            const current = this._ensureAssistant();
            const block = current.blocks.find((row) => row.type === 'tool_use' && String(row.id || '') === String(event.id || ''));
            if (block) {
                block.status = event.ok ? 'done' : 'failed';
                block.result = event.ok ? (event.result || null) : (event.error || null);
                block.endedAt = Date.now();
                this._schedulePaint(current);
            }
            if (event.ok && event.result) {
                const name = String(event.name || '');
                if (name === 'app_errors') this._ingestFailedNodes(event.result, current);
                else if (name === 'run_status') this._ingestRunNodes(event.result, current);
            }
            /* The clock keeps running: the turn is still open (the next round may take a while), and
               the live line is the proof of that. It is stopped only by an ending event. */
            return;
        }
        if (type === 'rerun_started') {
            /* The model reran a node with the tool (not the card's button): the card is the run's
               mark either way, so the same node is shown as started. */
            const current = this._ensureAssistant();
            this._markRerunStarted(
                String(event.run_id || ''),
                String(event.node_id || ''),
                String(event.workflow_name || ''),
                current
            );
            this._schedulePaint(current);
            return;
        }
        if (type === 'plan') {
            this._plan = event.steps || [];
            const current = this._ensureAssistant();
            current.blocks.push({ type: 'plan', steps: this._plan });
            this._schedulePaint(current);
            this._renderSide();
            return;
        }
        if (type === 'question') {
            const current = this._ensureAssistant();
            current.messageId = event.message_id;
            current.questionId = event.question_id;
            current.questions = event.questions || [];
            current.answers = {};
            current.questionEl.innerHTML = current.questions.map((item) => AIRender.questionCard(item, false)).join('');
            /* The card IS the state now ("waiting for your answer"), so the live line must go: it
               used to stay painted under the card, announcing work nobody was doing. */
            this._turnEnded = true;
            this._sending = false;
            this._setSending(false);
            this._renderSide();
            return;
        }
        if (type === 'artifact') {
            const current = this._ensureAssistant();
            current.artifacts = current.artifacts || [];
            current.artifacts.push(event.artifact);
            this._artifactsById = this._artifactsById || {};
            if (event.artifact && event.artifact.id) this._artifactsById[event.artifact.id] = event.artifact;
            const holder = document.createElement('div');
            holder.innerHTML = AIRender.artifactCard(event.artifact);
            if (holder.firstElementChild) current.artifactsEl.appendChild(holder.firstElementChild);
            return;
        }
        if (type === 'workflow_apply') {
            this._applyWorkflowPayload(event.workflow || {}, !!event.run, String(event.name || ''));
            return;
        }
        if (type === 'usage') {
            this._usage = event.usage || {};
            const current = this._ensureAssistant();
            current.usageEl.innerHTML = AIRender.usage(this._usage);
            this._renderSide();
            return;
        }
        if (type === 'title') {
            if (this._dom.title) this._dom.title.textContent = event.title || I18n.t('ai.title');
            if (this._bootstrap) this._bootstrap.conversations = (this._bootstrap.conversations || []).map((row) => row.id === this._conversationId ? { ...row, title: event.title } : row);
            this._renderSessions();
            return;
        }
        if (type === 'refusal') {
            this._toast(event.error || I18n.t('ai.refusal'));
            return;
        }
        if (type === 'paused') {
            if (this._current?.thinking) this._current.thinking.classList.remove('is-live');
            /* A pause is an ending of THIS stream (the answer resumes through `/api/ai/answer`), so
               it must not be reported as a cut connection by `_noteCutStream`. */
            this._turnEnded = true;
            this._sending = false;
            this._setSending(false);
            this._stopClock();
            this._paintAssistant();
            return;
        }
        if (type === 'error') {
            this._renderError(event.error || I18n.t('ai.error'));
            return;
        }
        if (type === 'done') {
            if (this._current?.thinking) this._current.thinking.classList.remove('is-live');
            this._turnEnded = true;
            this._sending = false;
            this._setSending(false);
            this._stopClock();
            /* `stop_reason` is the provider's own verdict, and `max_tokens` means the answer was
               CUT. Painting it as a finished answer was the silent failure: the sentence stopped
               mid-way and nothing said why. */
            if (String(event.stop_reason || '') === 'max_tokens' && this._current?.blocks) {
                this._current.blocks.push({ type: 'note', text: I18n.t('ai.truncated') });
                this._toast(I18n.t('ai.truncated'));
            }
            /* A stop triggered from another tab (or the stop route answering while the stream was
               still open) ends the stream too — say it once, never twice. */
            const stopped = I18n.t('ai.stopped');
            if (
                String(event.stop_reason || '') === 'cancelled' &&
                this._current?.blocks &&
                !this._current.blocks.some((block) => block.type === 'note' && block.text === stopped)
            ) {
                this._current.blocks.push({ type: 'note', text: stopped });
            }
            this._paintAssistant();
            this._refreshConversations();
            /* A finished turn changed the numbers the side panel shows (usage, and the balance).
               One read, after the turn, not a poller. */
            this._loadSpend();
            return;
        }
    },

    _schedulePaint(current) {
        if (this._renderTimer) return;
        this._renderTimer = setTimeout(() => {
            this._renderTimer = null;
            this._paintAssistant();
        }, 90);
    },

    /* A turn opened: the live line starts at 0s and the clock that keeps it (and every running tool
       card) ticking starts with it. Called where `_sending` becomes true, so a slow first byte is
       already visible as "生成中 · 1s" instead of a dead send button. */
    _beginTurn() {
        this._turnStartedAt = Date.now();
        this._lastEventAt = this._turnStartedAt;
        this._turnEnded = false;
        /* Which conversation this turn paints into; a new chat learns it from the first `meta`. */
        this._streamConversation = this._conversationId || '';
        this._startClock();
    },

    /* An ending the stream did not announce: the server died, a proxy dropped the connection, a
       laptop slept past the request timeout. `_stream` then simply RESOLVES — no `done` — and the
       bubble kept a half answer that read as a finished one. Name it instead of leaving the reader
       to guess (and never twice: `stop()` and the `done`+`cancelled` path each add their own note). */
    _noteCutStream() {
        if (this._turnEnded) return;
        this._turnEnded = true;
        if (!this._current || !this._current.blocks) return;
        const said = String(I18n.t('ai.stopped'));
        if (this._current.blocks.some((block) => block.type === 'note' && block.text === said)) return;
        this._current.blocks.push({ type: 'note', text: I18n.t('ai.streamLost') });
        this._paintAssistant();
    },

    _renderError(message) {
        this._turnEnded = true;
        const current = this._ensureAssistant();
        /* The failure belongs at the END of whatever the turn already produced, in order. */
        current.blocks.push({ type: 'text', text: '' });
        current.blocks.push({ type: 'error', text: String(message || '') });
        this._paintAssistant();
        this._toast(message);
    },

    _selectedLabels(questionId) {
        return Array.from(this._dom.chat.querySelectorAll('[data-ai-answer]'))
            .filter((el) => el.getAttribute('data-ai-question') === String(questionId) && el.classList.contains('selected'))
            .map((el) => el.getAttribute('data-ai-answer'));
    },

    async _answerOption(questionId, label) {
        const current = this._current;
        if (!current || !current.questions) return;
        const multi = current.questions.find((item) => item.id === questionId)?.multi_select;
        if (multi) {
            const button = this._findByData(this._dom.chat, 'data-ai-answer', label);
            if (button && button.getAttribute('data-ai-question') === String(questionId)) button.classList.toggle('selected');
            return;
        }
        current.answers[questionId] = { id: questionId, selected: [label] };
        /* The click must SHOW that it registered: one visible choice per question, and a line that
           says how many answers are still missing (a card with three questions submitted only when
           all three were answered, so a first click looked like a dead button). */
        this._markAnswer(questionId, label);
        this._maybeAnswer();
    },

    _markAnswer(questionId, label) {
        const card = this._dom.chat ? this._dom.chat.querySelector('[data-ai-question-card="' + String(questionId) + '"]') : null;
        if (card) {
            for (const el of card.querySelectorAll('[data-ai-answer]')) {
                el.classList.toggle('selected', String(el.getAttribute('data-ai-answer')) === String(label));
            }
        }
        this._renderAnswerProgress();
    },

    _renderAnswerProgress() {
        const current = this._current;
        if (!current || !current.questions || !this._dom.chat) return;
        const missing = current.questions.filter((item) => !current.answers[item.id]).length;
        for (const item of current.questions) {
            const card = this._dom.chat.querySelector('[data-ai-question-card="' + String(item.id) + '"]');
            if (!card) continue;
            let hint = card.querySelector('.ai-question-pending');
            const answered = !!current.answers[item.id];
            if (answered && missing) {
                if (!hint) {
                    hint = document.createElement('div');
                    hint.className = 'ai-question-pending';
                    card.appendChild(hint);
                }
                hint.textContent = I18n.t('ai.answersWaiting', { n: missing });
            } else if (hint) {
                hint.remove();
            }
        }
    },

    _answerCustom(questionId, value) {
        const current = this._current;
        if (!current) return;
        const text = String(value || '').trim();
        const selected = this._selectedLabels(questionId);
        const refs = this._answerRefs(questionId).map((row) => ({ kind: row.kind, id: row.id }));
        if (!text && !selected.length && !refs.length) return;
        current.answers[questionId] = {
            id: questionId,
            selected,
            ...(text ? { custom: text } : {}),
            ...(refs.length ? { references: refs } : {}),
        };
        this._renderAnswerProgress();
        this._maybeAnswer();
    },

    async _maybeAnswer() {
        const current = this._current;
        if (!current || !current.questions) return;
        if (!current.questions.every((item) => current.answers[item.id])) return;
        const answers = current.questions.map((item) => current.answers[item.id]);
        /* One flat list for the server: the answer that named them may be the custom box of any
           card, and the resumed turn resolves each reference the same bounded way the composer's
           `@` does. */
        const references = answers.flatMap((item) => (item && item.references) || []);
        const approval = current.questions.some((item) => item.kind === 'approval');
        if (approval) {
            /* The decision stays visible in the turn: an approval card that vanished into
               "已回答" left the user unable to see whether they allowed or denied this call. */
            const chosen = answers.flatMap((item) => item.selected || []).filter(Boolean).join(', ');
            const question = current.questions.find((item) => item.kind === 'approval') || {};
            const picked = (question.options || []).find((option) => option.label === chosen) || {};
            current.questionEl.innerHTML =
                '<div class="ai-question-answered">' +
                AIRender.escape(
                    String(picked.value || '') === 'deny'
                        ? I18n.t('ai.approvalDenied')
                        : I18n.t('ai.approvalAnswered') + (chosen ? ': ' + chosen : '')
                ) +
                '</div>';
        } else {
            current.questionEl.innerHTML = '<div class="ai-question-answered">' + AIRender.escape(I18n.t('ai.questionAnswered')) + '</div>';
        }
        this._beginTurn();
        this._sending = true;
        this._setSending(true);
        /* The resumed turn waits for the provider too: show the live line now, not after the first
           event (a slow local model made an answered question look unanswered). */
        this._ensureAssistant();
        this._paintAssistant();
        try {
            await this._stream('/api/ai/answer', {
                conversation_id: this._conversationId,
                message_id: current.messageId,
                question_id: current.questionId,
                answers,
                references,
                api_key: AISettings.keyFor(this._provider),
            });
        } catch (error) {
            if (error.name !== 'AbortError') this._renderError(error.message);
        } finally {
            this._sending = false;
            this._setSending(false);
            this._stopClock();
            this._noteCutStream();
        }
    },

    async stop() {
        this._turnEnded = true;
        if (this._abort) this._abort.abort();
        try {
            await fetch('/api/ai/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conversation_id: this._conversationId }) });
        } catch (e) {
            /* stopping is best-effort; the stream abort already closed the page side */
        }
        this._sending = false;
        this._setSending(false);
        this._stopClock();
        /* A stopped turn used to end in silence: the bubble just stopped growing. Say it, and say
           that the commands it started went with it (the route stops that conversation's children).
           Once only: the server may also answer the abort with `done`+`cancelled` first. */
        const said = String(I18n.t('ai.stopped'));
        if (this._current && this._current.blocks) {
            if (!this._current.blocks.some((block) => block.type === 'note' && block.text === said)) {
                this._current.blocks.push({ type: 'note', text: said });
            }
            this._paintAssistant();
        }
    },

    async newChat() {
        this._conversationId = '';
        this._rememberConversation('');
        this._openDetails.clear();
        this._messages = [];
        this._current = null;
        this._plan = [];
        this._usage = null;
        this._contextMeta = null;
        this._attachments = [];
        this._mode = 'chat';
        this._renderWelcome();
        this._renderSessions();
        this._renderSide();
        this._renderAttachments();
        if (this._dom.title) this._dom.title.textContent = I18n.t('ai.title');
        if (this._dom.input) this._dom.input.focus();
    },

    async _refreshConversations() {
        try {
            const params = new URLSearchParams();
            if (this._sessionQuery) params.set('q', this._sessionQuery);
            if (this._showArchived) params.set('archived', '1');
            const suffix = params.toString() ? '?' + params.toString() : '';
            const response = await fetch('/api/ai/conversations' + suffix);
            const data = await response.json();
            if (data.ok && this._bootstrap) {
                this._bootstrap.conversations = data.conversations || [];
                this._renderSessions();
            }
        } catch (e) {
            /* the transcript is still usable when the list refresh fails */
        }
    },

    async _toggleConversationPin(id) {
        const row = (this._bootstrap?.conversations || []).find((item) => item.id === id);
        if (!row) return;
        try {
            await fetch('/api/ai/conversations/' + encodeURIComponent(id), {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pinned: !row.pinned }),
            });
            await this._refreshConversations();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _toggleConversationArchive(id) {
        const row = (this._bootstrap?.conversations || []).find((item) => item.id === id);
        if (!row) return;
        const archiving = !row.archived;
        try {
            await fetch('/api/ai/conversations/' + encodeURIComponent(id), {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ archived: archiving }),
            });
            /* The open conversation just left the list: keep the reader on a chat that exists. */
            if (archiving && this._conversationId === id) this.newChat();
            await this._refreshConversations();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _exportConversation(id) {
        let format = 'md';
        if (typeof showDialog === 'function') {
            const choice = await showDialog({
                message: I18n.t('ai.exportHint'),
                buttons: [
                    { label: I18n.t('ai.exportMarkdown'), value: 'md', primary: true },
                    { label: I18n.t('ai.exportJson'), value: 'json' },
                    { label: I18n.t('ai.close'), value: '' },
                ],
                cancelValue: '',
            });
            if (!choice) return;
            format = choice;
        }
        const link = document.createElement('a');
        link.href = '/api/ai/conversations/' + encodeURIComponent(id) + '/export?format=' + encodeURIComponent(format);
        link.setAttribute('download', '');
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        link.remove();
    },

    async _confirm(message) {
        if (typeof showDialog !== 'function') return false;
        const answer = await showDialog({
            message,
            buttons: [
                { label: I18n.t('ai.delete'), value: true, primary: true },
                { label: I18n.t('ai.close'), value: false },
            ],
            cancelValue: false,
        });
        return answer === true;
    },

    async _prompt(message, value) {
        if (typeof showDialog !== 'function') return '';
        const answer = await showDialog({
            message,
            input: { placeholder: I18n.t('ai.renamePrompt') },
            buttons: [
                { label: I18n.t('ai.save'), value: true, primary: true, withInput: true },
                { label: I18n.t('ai.close'), value: false },
            ],
            cancelValue: false,
        });
        // A dialog with an input is answered by `{value, input}` only when the button asks for both;
        // reading `answer.value` from a bare `true` made this return '' for every rename.
        if (!answer || answer.value !== true) return '';
        return String(answer.input || '').trim();
    },

    _artifactById(id) {
        const artifacts = this._current?.artifacts || [];
        return artifacts.find((item) => item.id === id) || null;
    },

    _applySkillArtifact(id) {
        const artifact = this._artifactById(id);
        if (!artifact) return;
        const payload = artifact.payload || {};
        this._editingSkill = {
            id: payload.id || '',
            name: payload.name || '',
            description: payload.description || '',
            prompt: payload.prompt || '',
            context: payload.context || [],
            tools: payload.tools || [],
            suggested: payload.suggested || [],
            ask_policy: payload.ask_policy || 'auto',
        };
        this._mode = 'studio';
        this._studioTab = 'skills';
        AIStudio.render(this._dom.chat, this);
    },

    _applyPluginArtifact(id) {
        const artifact = this._artifactById(id);
        if (!artifact) return;
        this._mode = 'studio';
        this._studioTab = 'plugins';
        AIStudio.render(this._dom.chat, this);
        const box = this._dom.chat.querySelector('[data-ai-plugin-manifest]');
        if (box) box.value = JSON.stringify(artifact.payload || {}, null, 2);
    },

    _applyMemoryArtifact(id) {
        const artifact = this._artifactById(id);
        if (!artifact) return;
        const text = String((artifact.payload || {}).text || '').trim();
        if (!text) return;
        fetch('/api/ai/memories', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        })
            .then((response) => response.json())
            .then((data) => {
                if (!data.ok) throw new Error(data.error || 'save failed');
                this._toast(I18n.t(data.duplicate ? 'ai.memoryDuplicate' : 'ai.memorySaved'));
            })
            .catch((error) => this._toast(error.message));
    },

    /* A chart_spec is a proposal with ONE mechanical action: render it through the SAME endpoint
       the dashboard uses. The server validates the chart type, the dataset and every named column;
       this page holds no second opinion about either the registry or the data contract. */
    async _applyChartArtifact(id) {
        const artifact = (this._artifactsById || {})[id] || this._artifactById(id);
        if (!artifact) return;
        try {
            const prepared = await fetch('/api/ai/chart/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec: artifact.payload || {} }),
            }).then((response) => response.json());
            if (!prepared.ok) throw new Error(prepared.error || I18n.t('ai.error'));
            const result = await fetch('/api/visualize/render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(prepared.request),
            }).then((response) => response.json());
            if (!result.ok) throw new Error(result.error || I18n.t('ai.error'));
            if (typeof renderChartPreview !== 'function') throw new Error(I18n.t('ai.chartPainterMissing'));
            renderChartPreview(result);
            this._toast(I18n.t('ai.chartRendered'));
        } catch (error) {
            this._toast(error.message || I18n.t('ai.error'));
        }
    },

    async _deleteConversation(id) {
        if (!(await this._confirm(I18n.t('ai.deleteConfirm')))) return;
        try {
            await fetch('/api/ai/conversations/' + encodeURIComponent(id), { method: 'DELETE' });
            if (this._conversationId === id) this.newChat();
            this._refreshConversations();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _renameConversation(id) {
        const title = await this._prompt(I18n.t('ai.renamePrompt'), '');
        if (!title) return;
        await fetch('/api/ai/conversations/' + encodeURIComponent(id), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
        });
        this._refreshConversations();
    },

    openSettings() {
        this._mode = 'settings';
        this._renderSettings();
    },

    _renderSettings() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider) || { id: this._provider, models: [] };
        const key = AISettings.keyFor(this._provider);
        const models = provider.models || [];
        const capabilityRows = (provider.capabilities || []).map((cap) => '<span class="ai-chip">' + AIRender.escape(I18n.has('ai.cap.' + cap) ? I18n.t('ai.cap.' + cap) : cap) + '</span>').join('');
        this._dom.chat.innerHTML =
            '<section class="ai-settings">' +
            '<header class="ai-studio-head"><div><h2>' + AIRender.escape(I18n.t('ai.settingsTitle')) + '</h2><p class="ai-hint">' + AIRender.escape(I18n.t('ai.settingsHint')) + '</p></div><button type="button" class="ai-ghost" data-ai-studio-close="1">' + AIRender.escape(I18n.t('ai.close')) + '</button></header>' +
            '<div class="ai-field-row"><label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.provider')) + '</span><select class="ai-select" data-ai-switch-provider>' +
            (this._bootstrap?.providers || []).map((item) => '<option value="' + AIRender.escape(item.id) + '"' + (item.id === this._provider ? ' selected' : '') + '>' + AIRender.escape(I18n.has(item.label_key) ? I18n.t(item.label_key) : item.id) + '</option>').join('') +
            '</select></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.model')) + '</span><select class="ai-select" data-ai-switch-model>' +
            models.map((item) => '<option value="' + AIRender.escape(item.id) + '"' + (item.id === this._model ? ' selected' : '') + '>' + AIRender.escape(item.label || item.id) + '</option>').join('') +
            '</select></label></div>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.key')) + '</span><input class="ai-input" type="password" autocomplete="off" data-ai-key value="' + AIRender.escape(key) + '" placeholder="' + AIRender.escape(I18n.t('ai.keyPlaceholder')) + '" /></label>' +
            /* The one switch that protects a wallet: with it on, every send must go to the local
               daemon, and a paid provider is refused with a sentence instead of a charge. */
            '<label class="ai-field ai-field-check"><input type="checkbox" data-ai-local-only="1"' + (AISettings.load().localOnly ? ' checked' : '') + ' /><span>' + AIRender.escape(I18n.t('ai.localOnly')) + '</span></label>' +
            '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.localOnlyHint')) + '</p>' +
            '<div class="ai-skill-meta">' + capabilityRows + '</div>' +
            '<p class="ai-hint">' + AIRender.escape(I18n.has(provider.notes_key) ? I18n.t(provider.notes_key) : '') + '</p>' +
            '<div class="ai-editor-actions"><button type="button" class="ai-primary" data-ai-save-settings="1">' + AIRender.escape(I18n.t('ai.save')) + '</button>' +
            '<button type="button" class="ai-ghost" data-ai-refresh-models="1">' + AIRender.escape(I18n.t('ai.refreshModelsBtn')) + '</button>' +
            '<button type="button" class="ai-ghost" data-ai-test="1">' + AIRender.escape(I18n.t('ai.test')) + '</button></div>' +
            '<div class="ai-test-result" data-ai-test-result></div>' +
            '</section>';
    },

    async _saveSettings() {
        const key = this._dom.chat.querySelector('[data-ai-key]');
        if (key) AISettings.setKey(this._provider, key.value.trim());
        AISettings.setProvider(this._provider);
        AISettings.setModel(this._provider, this._model);
        this._toast(I18n.t('ai.saved'));
        await this._loadBootstrap();
        this._mode = 'chat';
        this._renderWelcome();
    },

    async _refreshModels() {
        const key = AISettings.keyFor(this._provider);
        try {
            const response = await fetch('/api/ai/providers/' + encodeURIComponent(this._provider) + '/models', {
                headers: { 'X-Provider-Key': key },
            });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'models failed');
            const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
            if (provider) provider.models = data.models.map((item) => ({ id: item.id, label: item.label || item.id, capabilities: provider.capabilities || [] }));
            this._renderSettings();
            this._toast(I18n.t('ai.refreshModelsBtn') + ': ' + (data.models || []).length);
        } catch (error) {
            this._toast(I18n.t('ai.testFail') + ': ' + error.message);
        }
    },

    async _testProvider() {
        const keyInput = this._dom.chat.querySelector('[data-ai-key]');
        const key = keyInput ? keyInput.value.trim() : AISettings.keyFor(this._provider);
        const result = this._dom.chat.querySelector('[data-ai-test-result]');
        if (result) result.textContent = I18n.t('ai.testing');
        try {
            const response = await fetch('/api/ai/providers/' + encodeURIComponent(this._provider) + '/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: this._model, api_key: key }),
            });
            const data = await response.json();
            if (result) result.textContent = data.ok ? I18n.t('ai.testOk', { ms: data.latency_ms }) : I18n.t('ai.testFail') + ': ' + (data.error || '');
        } catch (error) {
            if (result) result.textContent = I18n.t('ai.testFail') + ': ' + error.message;
        }
    },

    /* ─── Entry from a panel outside the workspace ─────────────────────────────
       A dataset / run / node panel hands over the ids of the thing it is showing and the question
       to ask. This opens a NEW chat (an entry from a table must not inherit an unrelated
       conversation), attaches the ids as manual context so the server re-reads that object, and
       PRE-FILLS the question without sending it: the send button stays the user's, and a prompt
       they can edit is the point of an entry. */
    async askAbout(target) {
        const spec = target || {};
        const context = {};
        if (spec.dataset_id) context.dataset_id = String(spec.dataset_id);
        if (spec.run_id) context.run_id = String(spec.run_id);
        AIContext.setManual(context);
        this.open({ context });
        await this.newChat();
        if (this._dom.input) {
            this._dom.input.value = String(spec.prompt || '');
            this._dom.input.focus();
        }
        this._renderContextBar();
    },

    openStudio(tab) {
        if (tab) this._studioTab = tab;
        /* The panel may be closed: a control OUTSIDE it (the Python node's 管理脚本) called this
           and nothing appeared — `_mode` only decides what the transcript draws. Opening first is
           what makes that button act; `_renderWelcome` then declines to paint over the studio
           because the mode is no longer 'chat'. */
        if (!this._open) this.open({ silent: true });
        this._mode = 'studio';
        AIStudio.render(this._dom.chat, this);
        if (this._studioTab === 'python' && typeof AIStudio.loadPython === 'function') {
            AIStudio.loadPython(this);
        }
        if (this._studioTab === 'memory' && typeof AIStudio.loadMemory === 'function') {
            AIStudio.loadMemory(this);
        }
    },

    async _loadSkillForEdit(id) {
        try {
            const response = await fetch('/api/ai/skills/' + encodeURIComponent(id));
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'skill not found');
            this._editingSkill = { ...data.skill, builtin: !!data.skill.builtin };
        } catch (e) {
            this._editingSkill = (this._bootstrap?.skills || []).find((item) => item.id === id) || null;
        }
        AIStudio.render(this._dom.chat, this);
    },

    async _saveSkillFromEditor() {
        const editor = this._editingSkill;
        if (!editor) return;
        const value = (name) => this._dom.chat.querySelector('[data-ai-skill-field="' + name + '"]')?.value || '';
        const context = Array.from(this._dom.chat.querySelectorAll('[data-ai-skill-context]:checked')).map((el) => el.getAttribute('data-ai-skill-context'));
        const tools = Array.from(this._dom.chat.querySelectorAll('[data-ai-skill-tool]:checked')).map((el) => el.getAttribute('data-ai-skill-tool'));
        const payload = {
            id: editor.builtin ? (editor.id || value('id')) : value('id') || editor.id,
            name: value('name'),
            description: value('description'),
            name_key: editor.name_key || ('ai.skill.' + (value('id') || editor.id) + '.name'),
            description_key: editor.description_key || ('ai.skill.' + (value('id') || editor.id) + '.desc'),
            prompt: value('prompt'),
            context,
            tools,
            suggested: value('suggested').split('\n').map((item) => item.trim()).filter(Boolean),
            ask_policy: this._dom.chat.querySelector('[data-ai-skill-field="ask_policy"]')?.value || 'auto',
        };
        try {
            const response = await fetch('/api/ai/skills', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'save failed');
            this._editingSkill = null;
            await this._loadBootstrap();
            this.openStudio();
            this._toast(I18n.t('ai.saved'));
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _forkSkill(id) {
        try {
            const response = await fetch('/api/ai/skills/' + encodeURIComponent(id) + '/fork', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'fork failed');
            await this._loadBootstrap();
            this.openStudio();
            this._toast(I18n.t('ai.saved'));
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _deleteSkill(id) {
        if (!(await this._confirm(I18n.t('ai.deleteConfirm')))) return;
        try {
            await fetch('/api/ai/skills/' + encodeURIComponent(id), { method: 'DELETE' });
            await this._loadBootstrap();
            this.openStudio();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _togglePlugin(id, enabled) {
        try {
            await fetch('/api/ai/plugins/' + encodeURIComponent(id) + '/enable', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled }),
            });
            await this._loadBootstrap();
            this.openStudio();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _deletePlugin(id) {
        if (!(await this._confirm(I18n.t('ai.deleteConfirm')))) return;
        try {
            await fetch('/api/ai/plugins/' + encodeURIComponent(id), { method: 'DELETE' });
            await this._loadBootstrap();
            this.openStudio();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _installPlugin() {
        const box = this._dom.chat.querySelector('[data-ai-plugin-manifest]');
        if (!box) return;
        let payload;
        try {
            payload = JSON.parse(box.value || '{}');
        } catch (error) {
            this._toast(I18n.t('ai.testFail') + ': ' + error.message);
            return;
        }
        const permissions = (payload.permissions || []).join(', ');
        if (!(await this._confirm((payload.name || payload.id || '') + '\n' + I18n.t('ai.pluginPermissions') + ': ' + permissions))) return;
        try {
            const response = await fetch('/api/ai/plugins/install', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'install failed');
            await this._loadBootstrap();
            this.openStudio();
            this._toast(I18n.t('ai.saved'));
        } catch (error) {
            this._toast(error.message);
        }
    },

    _toast(message) {
        if (typeof showToast === 'function') showToast(message);
    },

    _copyText(text) {
        /* A packaged window (WebView2/WKWebView) and a plain-http LAN page are both outside the
           secure-context guarantee, so navigator.clipboard can be absent or reject. The textarea
           fallback is the only path left; it must not leave a visible node behind. */
        const done = () => this._toast(I18n.t('ai.copied'));
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done, () => this._copyWithTextarea(text, done));
            return;
        }
        this._copyWithTextarea(text, done);
    },

    _copyWithTextarea(text, done) {
        const area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', 'readonly');
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        try {
            area.select();
            if (document.execCommand && document.execCommand('copy')) done();
            else this._toast(I18n.t('ai.error'));
        } finally {
            area.remove();
        }
    },

    setProviderFromBar(value) {
        this._provider = value;
        AISettings.setProvider(value);
        this._model = AISettings.modelFor(value, this._bootstrap?.providers);
        this._renderModelOptions();
        this._renderToggles();
        this._loadBootstrap();
    },

    setModelFromBar(value) {
        this._model = value;
        AISettings.setModel(this._provider, value);
        this._loadBootstrap();
    },

    setSkillFromBar(value) {
        this._skill = value;
        AISettings.save({ skill: value });
    },

    /* The local daemon is its own choice: qwen3.5 thinks by default, which doubles a batch call's
       wall time, so a local turn stays non-thinking unless this switch says otherwise. */
    _thinkingOn() {
        const settings = AISettings.load();
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        const caps = (provider && provider.capabilities) || [];
        const wanted = provider && provider.local_only ? settings.thinkingLocal : settings.thinking;
        return !!wanted && caps.includes('thinking');
    },

    toggleThinking() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        const local = !!(provider && provider.local_only);
        const settings = AISettings.load();
        AISettings.save(local ? { thinkingLocal: !settings.thinkingLocal } : { thinking: !settings.thinking });
        this._renderToggles();
    },

    toggleSearch() {
        const settings = AISettings.load();
        AISettings.save({ search: !settings.search });
        this._renderToggles();
    },

    /* The attach button, a drop and a paste all need the same two answers first: does this provider
       take files, and is a key present. One place decides, so a drop cannot bypass the refusal. */
    _attachKey() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        if (!(provider?.capabilities || []).includes('files')) {
            this._toast(I18n.t('ai.fileUnsupported'));
            return '';
        }
        const key = AISettings.keyFor(this._provider);
        if (!key) {
            this._toast(I18n.t('ai.keyMissing'));
            this.openSettings();
            return '';
        }
        return key;
    },

    async attach() {
        const key = this._attachKey();
        if (!key) return;
        const input = document.createElement('input');
        input.type = 'file';
        input.multiple = true;
        input.accept = '.pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.csv,.json,.log,.xlsx,.xls,.png,.jpg,.jpeg,.gif,.webp';
        input.onchange = () => {
            const files = Array.from(input.files || []);
            if (files.length) this._uploadFiles(files, key);
        };
        input.click();
    },

    /* One attachment per request (the endpoint takes one), so a multi-file pick is a loop that
       keeps going: a refused file must not throw away the ones that already uploaded. Failures are
       collected and reported together — a toast per file would replace the previous one. */
    async _uploadFiles(files, key = '') {
        const rows = Array.from(files || []).filter(Boolean);
        if (!rows.length) return;
        const apiKey = key || this._attachKey();
        if (!apiKey) return;
        this._uploading = true;
        this._renderToggles();
        let added = 0;
        let datasetImported = false;
        const failures = [];
        try {
            const conversationId = await this._ensureConversation();
            for (const file of rows) {
                try {
                    const form = new FormData();
                    form.append('file', file);
                    form.append('conversation_id', conversationId);
                    form.append('provider', this._provider);
                    form.append('api_key', apiKey);
                    const response = await fetch('/api/ai/files', { method: 'POST', body: form });
                    const data = await response.json();
                    if (!data.ok) throw new Error(data.error || 'upload failed');
                    if (data.dataset) {
                        /* A big table: the server registered it as a dataset instead of sending every
                           row to the model. Reference it, so the assistant reads a bounded slice. */
                        this._pickRef('dataset', data.dataset.dataset_id, data.dataset.name);
                        this._toast(I18n.t('ai.datasetFromUpload', { name: data.dataset.name, rows: data.dataset.rows }));
                        datasetImported = true;
                    } else {
                        this._attachments.push(data.attachment);
                    }
                    added += 1;
                } catch (error) {
                    failures.push({ name: file.name || '', reason: error.message });
                }
            }
        } catch (error) {
            failures.push({ name: '', reason: error.message });
        } finally {
            this._uploading = false;
            this._renderAttachments();
            this._renderToggles();
        }
        if (failures.length) {
            const first = failures[0];
            this._toast(
                added
                    ? I18n.t('ai.attachPartial', { saved: added, failed: failures.length })
                    : (first.name ? first.name + ': ' : '') + first.reason
            );
        } else if (added && !datasetImported) {
            this._toast(I18n.t('ai.saved'));
        }
    },

    _hasFileDrag(event) {
        const transfer = event && event.dataTransfer;
        if (!transfer) return false;
        if (transfer.files && transfer.files.length) return true;
        /* Chrome reports no `files` on dragenter; the type list is what says a file is coming. */
        return transfer.types ? Array.from(transfer.types).includes('Files') : false;
    },

    _droppedFiles(event) {
        const transfer = event && event.dataTransfer;
        if (!transfer || !transfer.files || !transfer.files.length) return [];
        return Array.from(transfer.files).filter(Boolean);
    },

    _bindAttachDrop(root) {
        let depth = 0;
        root.addEventListener('dragenter', (event) => {
            if (!this._hasFileDrag(event)) return;
            event.preventDefault();
            depth += 1;
            root.classList.add('ai-drop-active');
        });
        root.addEventListener('dragover', (event) => {
            if (!this._hasFileDrag(event)) return;
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        });
        root.addEventListener('dragleave', () => {
            /* No file check here: browsers report an empty `dataTransfer.files` on dragleave for
               security, so requiring one left the highlight stuck after the drag left the panel. */
            if (!depth) return;
            depth = Math.max(0, depth - 1);
            if (!depth) root.classList.remove('ai-drop-active');
        });
        root.addEventListener('drop', (event) => {
            const files = this._droppedFiles(event);
            if (!files.length) return;
            event.preventDefault();
            depth = 0;
            root.classList.remove('ai-drop-active');
            this._uploadFiles(files);
        });
    },

    async _ensureConversation() {
        if (this._conversationId) return this._conversationId;
        const response = await fetch('/api/ai/conversations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: this._provider, model: this._model, skill: this._skill || 'auto' }),
        });
        const data = await response.json();
        if (!data.ok) throw new Error(data.error || 'conversation failed');
        this._conversationId = data.conversation.id;
        if (this._bootstrap) {
            this._bootstrap.conversations = [data.conversation, ...(this._bootstrap.conversations || [])];
            this._renderSessions();
        }
        return this._conversationId;
    },

    async _removeAttachment(id) {
        this._attachments = this._attachments.filter((row) => row.id !== id);
        this._renderAttachments();
        try {
            await fetch('/api/ai/files/' + encodeURIComponent(id), {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: AISettings.keyFor(this._provider) }),
            });
        } catch (e) {
            /* local chip removal is enough; the server row is cleaned on the next delete */
        }
    },
};
window.AIWorkspace = AIWorkspace;

/* The composer controls are inline markup; these small wrappers keep the markup readable and
 * forward the value rather than the event, so the handler never sees a stale element. */
function aiSetProvider(value) { AIWorkspace.setProviderFromBar(value); }
function aiSetModel(value) { AIWorkspace.setModelFromBar(value); }
function aiSetSkill(value) { AIWorkspace.setSkillFromBar(value); }
