/* The panel itself: open, close, pin, full screen, the three column widths and the outside press.
 *
 * The dock keeps no transcript state; it only decides which of the three columns the reader sees,
 * and it is the one place that remembers a width between sessions (through AISettings).
 */

Object.assign(AIWorkspace, {
    restore() {
        const settings = AISettings.load();
        if (settings.open) this.open({ silent: true });
        /* Monitors are page-level: a run can finish while the dock is closed, and the delivery must
           still reach the account that armed it. The poller never calls a provider without a key. */
        if (typeof AIWatch !== 'undefined') AIWatch.start();
    },

    _measuredWidth() {
        const root = this._dom.root;
        if (!root) return 0;
        const rect = typeof root.getBoundingClientRect === 'function' ? root.getBoundingClientRect() : null;
        const measured = rect && rect.width ? rect.width : 0;
        if (measured) return measured;
        return parseInt(root.style.getPropertyValue('--ai-width'), 10) || 0;
    },

    _applyWidthClass(width) {
        if (!this._dom.root) return;
        /* The configured width and the painted width differ when the viewport caps the dock
           (`max-width: calc(100vw - 24px)`). The layout class must follow what is on screen, or a
           narrow dock keeps the three-column grid and squeezes the chat to a few pixels. */
        const actual = this._measuredWidth() || width;
        this._dom.root.classList.toggle('narrow', !this._full && actual < 480);
        this._dom.root.classList.toggle('tiny', !this._full && actual < 390);
    },

    /* A demo deep link may widen the dock for one recording. The override is transient: it must NOT
       be written to localStorage, or following a link would permanently change the user's panel. */
    setRunWidth(width) {
        const value = Math.max(360, Math.min(900, Number(width) || 0));
        this._runWidth = value;
        if (this._dom.root) {
            this._dom.root.style.setProperty('--ai-width', value + 'px');
            this._applyWidthClass(value);
        }
    },

    /* The two sidebars are draggable, each within a range that keeps its content readable. The
       width lives in a CSS variable so the grid follows the pointer without a repaint rule, and
       it is remembered per browser like the panel's own width. */
    _bindColumns() {
        const root = this._dom.root;
        if (!root) return;
        const saved = AISettings.load();
        /* The two sidebars share the dock with the chat. Their clamps must know the dock width,
           or 150 + 200 on a 360px dock leaves the chat a few pixels and the grip unreachable. */
        const limits = () => {
            const dock = this._measuredWidth() || 520;
            return {
                sessions: { min: 120, max: Math.max(120, Math.min(360, dock - 240)) },
                side: { min: 160, max: Math.max(160, Math.min(440, dock - 220)) },
            };
        };
        const clamp = (value, range) => Math.max(range.min, Math.min(range.max, value));
        let sessions = clamp(Number(saved.sessionsWidth) || 190, limits().sessions);
        let side = clamp(Number(saved.sideWidth) || 260, limits().side);
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
                        sessions = clamp(start + (moveEvent.clientX - startX), limits().sessions);
                    } else {
                        side = clamp(start + (startX - moveEvent.clientX), limits().side);
                    }
                    apply();
                };
                const up = () => {
                    AISettings.save({ sessionsWidth: sessions, sideWidth: side });
                    document.removeEventListener('pointermove', move);
                    document.removeEventListener('pointerup', up);
                    document.removeEventListener('pointercancel', up);
                };
                if (grip.setPointerCapture) {
                    try {
                        grip.setPointerCapture(event.pointerId);
                    } catch (error) {
                        /* No active pointer (a synthetic event in the browser tier, or a pointer
                           already released): capture is an enhancement, not a precondition. */
                    }
                }
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', up);
                document.addEventListener('pointercancel', up);
            });
        });
    },

    _bindDock() {
        const root = this._dom.root;
        if (!root) return;
        const width = this._runWidth || Math.max(360, Math.min(900, Number(AISettings.load().width) || 520));
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
                document.removeEventListener('pointercancel', up);
            };
            this._dom.resizer.addEventListener('pointerdown', (event) => {
                event.preventDefault();
                dragging = true;
                startX = event.clientX;
                startWidth = parseInt(root.style.getPropertyValue('--ai-width'), 10) || width;
                /* Capture the pointer so a drag that leaves the 8px handle keeps resizing; without
                   it the browser can hand the move to the canvas and the dock appears stuck. */
                if (this._dom.resizer.setPointerCapture) {
                    try {
                        this._dom.resizer.setPointerCapture(event.pointerId);
                    } catch (error) {
                        /* See the column grip: a synthetic/expired pointer must not abort the drag. */
                    }
                }
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', up);
                document.addEventListener('pointercancel', up);
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
        /* A viewport resize can cap the dock without a pointer event. Re-evaluate the layout class
           from the measured width so `.narrow`/`.tiny` match what the user sees. */
        if (typeof ResizeObserver !== 'undefined' && !this._widthObserver) {
            this._widthObserver = new ResizeObserver(() => this._applyWidthClass());
            this._widthObserver.observe(root);
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
            /* A demo deep link may open the workspace straight onto a specific (node-trace)
               conversation. It wins over the remembered one so the recording shows the trace the
               run just created, not a stale chat from a previous take. */
            const wanted = opts && opts.conversation;
            /* Never repaint a live turn's DOM — the stream is still writing into those bubbles. */
            if (wanted && !this._sending) this.selectConversation(wanted);
            else if (this._conversationId && !this._sending) this.selectConversation(this._conversationId);
            else if (!this._conversationId) this._renderWelcome();
            this._loadSpend();
            if (opts && opts.prompt && this._dom.input) this._dom.input.focus();
        });
    },

    async _refreshLocalModels() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        if (!provider || !provider.local_only || provider.requires_key) return;
        try {
            const response = await fetch(AI_BASE + '/providers/' + encodeURIComponent(this._provider) + '/models');
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

});
