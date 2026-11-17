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

const AIWorkspace = {
    _init: false,
    _open: false,
    _full: false,
    _sessionsOpen: false,
    _sending: false,
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
        };
        for (const [key, id] of Object.entries(ids)) this._dom[key] = document.getElementById(id);
        const root = this._dom.root;
        if (!root) return;
        this._sessionsOpen = !!AISettings.load().sessionsOpen;
        root.classList.toggle('sessions-open', this._sessionsOpen);
        AISettings.save({ open: this._open });
        this._provider = AISettings.providerId(null);
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
        }
        if (this._dom.root) {
            /* Delegated from the dock, not from the transcript: sessions, the side panel and the
               context bar are siblings of #ai-chat, so a listener on the chat could never see them
               (switching conversations, refreshing context and stopping a monitor were inert). */
            this._dom.root.addEventListener('click', (event) => this._onClick(event));
            this._dom.root.addEventListener('change', (event) => this._onChange(event));
            if (this._dom.chat) this._dom.chat.addEventListener('scroll', () => this._onChatScroll());
            this._dom.root.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' && !event.shiftKey && event.target && event.target.matches('textarea[data-ai-custom]')) {
                    event.preventDefault();
                    const questionId = event.target.getAttribute('data-ai-custom');
                    this._answerCustom(questionId, event.target.value);
                }
            });
        }
        this._bindDock();
        this._bindColumns();
        this._renderWelcome();
        this._renderComposer();
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
    },

    /* True when a press lands outside every surface this panel owns. */
    _onOutsidePress(event) {
        if (!this._open || !this._dom.root) return;
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
        this._loadBootstrap().then(() => {
            this._renderComposer();
            this._renderContextBar();
            if (this._conversationId) this.selectConversation(this._conversationId);
            else this._renderWelcome();
            if (opts && opts.prompt && this._dom.input) this._dom.input.focus();
        });
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
        try {
            const response = await fetch('/api/ai/bootstrap?provider=' + encodeURIComponent(provider) + '&model=' + encodeURIComponent(model));
            const data = await response.json();
            this._bootstrap = data;
            const ids = (data.providers || []).map((item) => item.id);
            this._provider = ids.includes(provider) ? provider : (ids[0] || 'deepseek');
            this._model = AISettings.modelFor(this._provider, data.providers);
            this._skill = settings.skill || 'auto';
            this._scope = data.settings?.context_scope || settings.scope || 'summary';
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
        const thinking = !!AISettings.load().thinking && capabilities.includes('thinking');
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

    _onRefInput() {
        if (!this._dom.input) return;
        const match = /(?:^|[\s(])@([^\s@]{0,60})$/.exec(this._dom.input.value);
        if (!match) {
            this._closeRefs();
            return;
        }
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
        this._dom.refMenu.hidden = false;
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
        const value = String(this._dom.input.value || '').replace(/@[^\s@]{0,60}$/, '').replace(/\s+$/, '');
        this._dom.input.value = value ? value + ' ' : '';
        if (!this._refs.some((row) => row.kind === kind && row.id === id)) {
            this._refs.push({kind: kind, id: id, label: label || id});
            this._renderRefs();
        }
        this._closeRefs();
        if (this._dom.input.focus) this._dom.input.focus();
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
        }
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
        const items = rows.map((row) => {
            const id = AIRender.escape(row.id);
            const rename = AIRender.escape(I18n.t('ai.rename'));
            const remove = AIRender.escape(I18n.t('ai.delete'));
            return (
                '<div class="ai-session-row">' +
                '<button type="button" class="ai-session ' + (row.id === this._conversationId ? 'selected' : '') + '" data-ai-conversation="' + id + '">' +
                '<span class="ai-session-title">' + AIRender.escape(row.title || I18n.t('ai.noConversation')) + '</span>' +
                '<span class="ai-session-meta">' + AIRender.escape(String(row.message_count || 0)) + '</span>' +
                '</button>' +
                '<span class="ai-session-actions">' +
                '<button type="button" class="ai-icon-btn" data-ai-rename-conversation="' + id + '" title="' + rename + '" aria-label="' + rename + '">✎</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-delete-conversation="' + id + '" title="' + remove + '" aria-label="' + remove + '">×</button>' +
                '</span></div>'
            );
        }).join('');
        this._dom.sessions.innerHTML =
            '<div class="ai-sessions-head"><strong>' + AIRender.escape(I18n.t('ai.sessions')) + '</strong>' +
            '<button type="button" class="ai-ghost" data-ai-new-session="1">' + AIRender.escape(I18n.t('ai.newChat')) + '</button></div>' +
            '<div class="ai-session-list">' + (items || '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.noSessions')) + '</p>') + '</div>';
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
            '<ul class="ai-context-list">' + (items || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.contextEmpty')) + '</li>') + '</ul>' +
            '<div class="ai-context-actions"><button type="button" class="ai-ghost" data-ai-context-preview="1">' + AIRender.escape(I18n.t(previewLabel)) + '</button></div>' +
            '<div class="ai-context-fields"><label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.datasetId')) + '</span><input class="ai-input" data-ai-manual="dataset_id" value="' + AIRender.escape(AIContext.manual.dataset_id || '') + '" /></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.runId')) + '</span><input class="ai-input" data-ai-manual="run_id" value="' + AIRender.escape(AIContext.manual.run_id || '') + '" /></label>' +
            '<button type="button" class="ai-ghost" data-ai-context-apply="1">' + AIRender.escape(I18n.t('ai.applyContext')) + '</button></div>' +
            '</section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.monitor.heading')) + '</h3>' +
            '<ul class="ai-monitor-list">' + (monitorRows || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.monitor.empty')) + '</li>') + '</ul></section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.agentTrace')) + '</h3>' +
            '<ol class="ai-trace">' + (plan || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.planEmpty')) + '</li>') + '</ol></section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.usage')) + '</h3>' + (usage || '<p class="ai-hint">—</p>') + '</section>';
    },

    _ensureAssistant() {
        if (!this._current || !this._current.el) {
            const el = document.createElement('article');
            el.className = 'ai-message assistant';
            el.innerHTML =
                '<div class="ai-message-role">' + AIRender.escape(I18n.t('ai.assistant')) + '</div>' +
                '<div class="ai-message-body">' +
                '<div class="ai-flow"></div>' +
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
        const last = blocks[blocks.length - 1];
        /* Between steps the model says nothing and the stream is silent: after a tool card there is
           no sign of life until the app answers. A text block means the model IS visibly writing, so
           the waiting line is for the other cases (turn just started, thinking, a running tool). */
        const waiting = this._sending && (!last || String(last.type) !== 'text');
        current.flowEl.innerHTML =
            AIRender.assistantFlow(blocks) +
            (waiting ? AIRender.workingRow(I18n.t(last && last.type === 'tool_use' && last.status === 'running' ? 'ai.waiting' : 'ai.working')) : '');
        if (atBottom && chat) chat.scrollTop = chat.scrollHeight;
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
        host.innerHTML =
            '<div class="ai-folder-head">' + AIRender.escape(I18n.t('ai.workspace.title')) + '</div>' +
            '<div class="ai-folder-path" title="' + AIRender.escape(state.path) + '">' + AIRender.escape(state.path) + '</div>' +
            '<div class="ai-folder-list">' + list + '</div>' +
            '<div class="ai-folder-actions">' +
            (state.parent ? '<button type="button" class="ai-ghost" data-ai-folder-open="' + AIRender.escape(state.parent) + '">' + AIRender.escape(I18n.t('ai.workspace.up')) + '</button>' : '') +
            '<button type="button" class="ai-primary" data-ai-folder-use="' + AIRender.escape(state.path) + '">' + AIRender.escape(I18n.t('ai.workspace.use')) + '</button>' +
            (this._workspace().folder ? '<button type="button" class="ai-ghost" data-ai-folder-clear="1">' + AIRender.escape(I18n.t('ai.workspace.clear')) + '</button>' : '') +
            '<button type="button" class="ai-ghost" data-ai-folder-close="1">' + AIRender.escape(I18n.t('ai.workspace.close')) + '</button>' +
            '</div>' +
            '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.hint')) + '</div>';
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
        this._sending = true;
        this._setSending(true);
        try {
            await this._stream('/api/ai/retry', { conversation_id: this._conversationId, api_key: key });
        } catch (error) {
            if (error.name !== 'AbortError') this._renderError(error.message);
        } finally {
            this._sending = false;
            this._setSending(false);
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
        const target = event.target.closest('[data-ai-suggest],[data-ai-conversation],[data-ai-new-session],[data-ai-rename-conversation],[data-ai-delete-conversation],[data-ai-context-refresh],[data-ai-context-preview],[data-ai-cmd],[data-ai-agents],[data-ai-context-apply],[data-ai-manual],[data-ai-answer],[data-ai-send-custom],[data-ai-copy-artifact],[data-ai-apply-skill],[data-ai-apply-plugin],[data-ai-apply-workflow],[data-ai-run-workflow],[data-ai-copy-answer],[data-ai-retry],[data-ai-jump],[data-ai-folder-open],[data-ai-folder-use],[data-ai-folder-clear],[data-ai-folder-close],[data-ai-apply-monitor],[data-ai-watch-only],[data-ai-disarm-monitor],[data-ai-remove-attachment],[data-ai-ref],[data-ai-remove-ref],[data-ai-studio-tab],[data-ai-python-new],[data-ai-python-edit],[data-ai-python-save],[data-ai-python-cancel],[data-ai-python-delete],[data-ai-python-fork],[data-ai-python-run],[data-ai-python-install],[data-ai-fork],[data-ai-edit-skill],[data-ai-delete-skill],[data-ai-new-skill],[data-ai-save-skill],[data-ai-cancel-skill],[data-ai-toggle-plugin],[data-ai-delete-plugin],[data-ai-install-plugin],[data-ai-studio-close],[data-ai-provider-select],[data-ai-refresh-models],[data-ai-test],[data-ai-save-settings],[data-ai-scope],[data-ai-switch-provider],[data-ai-switch-model],[data-ai-switch-skill]');
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
        if (target.hasAttribute('data-ai-context-refresh')) {
            this._renderContextBar();
            return;
        }
        if (target.hasAttribute('data-ai-context-preview')) {
            this._previewContext();
            return;
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
        this._conversationId = id;
        this._mode = 'chat';
        this._editingSkill = null;
        try {
            const response = await fetch('/api/ai/conversations/' + encodeURIComponent(id));
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'not found');
            this._messages = data.messages || [];
            this._conversationId = data.conversation.id;
            this._renderMessages(data.pending_questions || []);
            this._renderSessions();
            this._renderSide();
            if (this._dom.title) this._dom.title.textContent = data.conversation.title || I18n.t('ai.title');
        } catch (error) {
            this._toast(I18n.t('ai.error') + ': ' + error.message);
        }
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
        if (!this._messages.length) {
            this._renderWelcome();
            return;
        }
        /* A snapshot, and no recording: this function paints the transcript it was given. Iterating
           the live array while appending to it is an infinite loop, not a slow repaint. */
        for (const message of [...this._messages]) {
            if (message.role === 'user') {
                this._appendUser(message.content, message.meta?.context, message.meta?.attachments, null, false);
            } else if (message.role === 'assistant') {
                this._renderStoredAssistant(message);
            } else if (message.role === 'tool') {
                this._renderStoredTool(message);
            }
        }
        for (const question of pending || []) {
            this._appendQuestion(question);
        }
        this._dom.chat.scrollTop = this._dom.chat.scrollHeight;
    },

    _renderStoredAssistant(message) {
        const blocks = message.blocks || [];
        const el = document.createElement('article');
        el.className = 'ai-message assistant';
        el.innerHTML =
            '<div class="ai-message-role">' + AIRender.escape(I18n.t('ai.assistant')) + '</div><div class="ai-message-body">' +
            '<div class="ai-flow">' + AIRender.assistantFlow(blocks) + '</div>' +
            '<div class="ai-usage">' + AIRender.usage(message.usage || {}) + '</div>' +
            '<div class="ai-message-actions">' +
            '<button type="button" class="ai-ghost" data-ai-copy-answer="1">' + AIRender.escape(I18n.t('ai.copyAnswer')) + '</button>' +
            '<button type="button" class="ai-ghost" data-ai-retry="1">' + AIRender.escape(I18n.t('ai.retry')) + '</button>' +
            '</div>' +
            '</div>';
        this._dom.chat.appendChild(el);
    },

    _renderStoredTool(message) {
        let payload = message.content || '';
        try {
            payload = JSON.parse(payload);
        } catch (e) {
            /* plain text tool output is shown verbatim */
        }
        const artifact = payload && payload.artifact;
        if (artifact) {
            const holder = document.createElement('div');
            holder.innerHTML = AIRender.artifactCard(artifact);
            this._dom.chat.appendChild(holder.firstElementChild);
            return;
        }
        const meta = message.meta || {};
        if (meta.name) {
            const holder = document.createElement('div');
            holder.innerHTML = AIRender.toolCard(meta.name, {}, meta.is_error ? 'failed' : 'done', payload);
            this._dom.chat.appendChild(holder.firstElementChild);
        }
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
        const pendingAttachments = opts.monitor ? [] : this._attachments.slice();
        const pendingRefs = opts.monitor ? [] : this._refs.slice();
        if (!text && !pendingAttachments.length && !pendingRefs.length) {
            this._toast(I18n.t('ai.emptyMessage'));
            return false;
        }
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
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
        this._sending = true;
        this._setSending(true);
        /* The reaction is the point: the user must see their message AND a "working" turn before
           the first byte from the provider, otherwise a slow model looks like a dead button. */
        this._ensureAssistant();
        this._paintAssistant();
        if (this._dom.chat) this._dom.chat.scrollTop = this._dom.chat.scrollHeight;
        const body = {
            conversation_id: this._conversationId || '',
            text,
            provider: this._provider,
            model: this._model,
            api_key: key,
            thinking: !!AISettings.load().thinking && (provider?.capabilities || []).includes('thinking'),
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
        const text = I18n.t('ai.monitor.promptHead') + '\n```json\n' + facts + '\n```\n' + I18n.t('ai.monitor.promptAsk');
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
        if (this._dom.input) this._dom.input.disabled = sending;
        this._renderToggles();
    },

    _onEvent(event) {
        const type = event.type;
        if (type === 'meta') {
            this._conversationId = event.conversation_id || this._conversationId;
            this._current = this._ensureAssistant();
            this._current.messageId = event.message_id;
            this._current.turnId = event.turn_id;
            this._current.runId = event.run_id;
            this._contextMeta = event.context || {};
            if (event.skill) {
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
                this._schedulePaint(current);
            }
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
            current.artifactsEl.insertAdjacentHTML('beforeend', AIRender.artifactCard(event.artifact));
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
            this._sending = false;
            this._setSending(false);
            this._paintAssistant();
            return;
        }
        if (type === 'error') {
            this._renderError(event.error || I18n.t('ai.error'));
            return;
        }
        if (type === 'done') {
            if (this._current?.thinking) this._current.thinking.classList.remove('is-live');
            this._sending = false;
            this._setSending(false);
            this._paintAssistant();
            this._refreshConversations();
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

    _renderError(message) {
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
        this._maybeAnswer();
    },

    _answerCustom(questionId, value) {
        const current = this._current;
        if (!current) return;
        const text = String(value || '').trim();
        const selected = this._selectedLabels(questionId);
        if (!text && !selected.length) return;
        current.answers[questionId] = { id: questionId, selected, ...(text ? { custom: text } : {}) };
        this._maybeAnswer();
    },

    async _maybeAnswer() {
        const current = this._current;
        if (!current || !current.questions) return;
        if (!current.questions.every((item) => current.answers[item.id])) return;
        const answers = current.questions.map((item) => current.answers[item.id]);
        current.questionEl.innerHTML = '<div class="ai-question-answered">' + AIRender.escape(I18n.t('ai.questionAnswered')) + '</div>';
        this._sending = true;
        this._setSending(true);
        try {
            await this._stream('/api/ai/answer', {
                conversation_id: this._conversationId,
                message_id: current.messageId,
                question_id: current.questionId,
                answers,
                api_key: AISettings.keyFor(this._provider),
            });
        } catch (error) {
            if (error.name !== 'AbortError') this._renderError(error.message);
        } finally {
            this._sending = false;
            this._setSending(false);
        }
    },

    async stop() {
        if (this._abort) this._abort.abort();
        try {
            await fetch('/api/ai/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conversation_id: this._conversationId }) });
        } catch (e) {
            /* stopping is best-effort; the stream abort already closed the page side */
        }
        this._sending = false;
        this._setSending(false);
    },

    async newChat() {
        this._conversationId = '';
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
            const response = await fetch('/api/ai/conversations');
            const data = await response.json();
            if (data.ok && this._bootstrap) {
                this._bootstrap.conversations = data.conversations || [];
                this._renderSessions();
            }
        } catch (e) {
            /* the transcript is still usable when the list refresh fails */
        }
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

    toggleThinking() {
        const settings = AISettings.load();
        AISettings.save({ thinking: !settings.thinking });
        this._renderToggles();
    },

    toggleSearch() {
        const settings = AISettings.load();
        AISettings.save({ search: !settings.search });
        this._renderToggles();
    },

    async attach() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        if (!(provider?.capabilities || []).includes('files')) {
            this._toast(I18n.t('ai.fileUnsupported'));
            return;
        }
        const key = AISettings.keyFor(this._provider);
        if (!key) {
            this._toast(I18n.t('ai.keyMissing'));
            this.openSettings();
            return;
        }
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.csv,.json,.log,.xlsx,.xls,.png,.jpg,.jpeg,.gif,.webp';
        input.onchange = async () => {
            const file = input.files && input.files[0];
            if (!file) return;
            this._uploading = true;
            this._renderToggles();
            try {
                const conversationId = await this._ensureConversation();
                const form = new FormData();
                form.append('file', file);
                form.append('conversation_id', conversationId);
                form.append('provider', this._provider);
                form.append('api_key', key);
                const response = await fetch('/api/ai/files', { method: 'POST', body: form });
                const data = await response.json();
                if (!data.ok) throw new Error(data.error || 'upload failed');
                if (data.dataset) {
                    /* A big table: the server registered it as a dataset instead of sending every
                       row to the model. Reference it, so the assistant reads a bounded slice. */
                    this._pickRef('dataset', data.dataset.dataset_id, data.dataset.name);
                    this._toast(I18n.t('ai.datasetFromUpload', { name: data.dataset.name, rows: data.dataset.rows }));
                    return;
                }
                this._attachments.push(data.attachment);
                this._renderAttachments();
                this._toast(I18n.t('ai.saved'));
            } catch (error) {
                this._toast(I18n.t('ai.error') + ': ' + error.message);
            } finally {
                this._uploading = false;
                this._renderToggles();
            }
        };
        input.click();
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
