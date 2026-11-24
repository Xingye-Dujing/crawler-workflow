/* AI workspace: the right-side agent window. The entry file.
 *
 * The object itself is declared in `ai/kernel/store.js` (first script: one object, one state
 * record), and every surface extends it with `Object.assign(AIWorkspace, { ... })` from its own file:
 * `ai/kernel/` holds the state, the DOM paint, the routes and the stream; `ai/features/` holds the
 * panels; `ai/render/` turns model text into elements. `tests/frontend/splits.json` is the map and
 * `index.html` is the only load order.
 *
 * What stays here is the wiring: `init()` binds the markup, the delegated listeners and the boot
 * hooks, and the inline-onclick wrappers forward their value to the object. Nothing else: a new
 * behaviour belongs to the file that owns the surface.
 */
Object.assign(AIWorkspace, {
    init() {
        if (this._init) return;
        this._init = true;
        const ids = {
            root: 'ai-workspace',
            resizer: 'ai-resizer',
            sessions: 'ai-sessions',
            /* The transcript is its own element inside the chat column. Settings and the studio
               render into `panel`, so opening either one can never destroy a live answer. */
            chat: 'ai-transcript',
            panel: 'ai-panel',
            chatHost: 'ai-chat',
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
            recipe: 'ai-recipe',
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

});

/* The composer controls are inline markup; these small wrappers keep the markup readable and
 * forward the value rather than the event, so the handler never sees a stale element. */
function aiSetProvider(value) { AIWorkspace.setProviderFromBar(value); }
function aiSetModel(value) { AIWorkspace.setModelFromBar(value); }
function aiSetSkill(value) { AIWorkspace.setSkillFromBar(value); }

window.AIWorkspace = AIWorkspace;
