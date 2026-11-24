/* The transcript: one bubble per turn, the live "generating" line, and switching the panel back to
 * the chat.
 *
 * A stored row is not drawn here; it comes from the server transcript in stored.js. The live turn
 * and a reopened one must produce the same picture, which is why both call the same turn HTML.
 */

/* How long a turn may send NOTHING before the live line says so. A local model on a long context is
 * genuinely silent for tens of seconds while it thinks, and a line that never changes reads as a
 * dead stream — the reader then assumes the answer was cut. 15 s is long enough not to cry wolf on
 * an ordinary pause and short enough to answer "is it still alive?" before doubt sets in. */
const STALL_AFTER_MS = 15000;

Object.assign(AIWorkspace, {
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
            this._current.conversationId = this._conversationId;
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
        /* Replacing the flow's innerHTML briefly empties it; the browser clamps scrollTop to 0
           before the new content is measured. Keep the reader's position and restore it after the
           paint, unless they were at the bottom (then follow the new text). */
        const keepScroll = chat ? chat.scrollTop : 0;
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
        if (chat) {
            const behavior = chat.style.scrollBehavior;
            /* `smooth` would animate a restore back to the reader's old line; the restore is not a
               navigation, it is undoing the innerHTML's layout side effect. */
            if (behavior) chat.style.scrollBehavior = 'auto';
            chat.scrollTop = atBottom ? chat.scrollHeight : keepScroll;
            if (behavior) chat.style.scrollBehavior = behavior;
        }
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

    /* ``record`` is what separates a new turn from a repaint. ``_renderMessages`` replays stored
       rows and already has them; pushing there used to append into the array it was iterating,
       which never terminates. A repaint draws only. */
    _appendUser(text, context, attachments, extra, record = true, messageId = '') {
        const el = document.createElement('article');
        el.className = 'ai-message user';
        /* The stored id is the identity a repaint matches on; a row just typed has none until the
           server writes it, and is therefore never mistaken for an older message. */
        if (messageId) {
            el.setAttribute('data-ai-key', 'message:' + String(messageId));
            el.setAttribute('data-ai-message', String(messageId));
        }
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
        return el;
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

    /* Settings and the studio get their OWN surface. They used to paint into `#ai-chat`, which
       destroyed the transcript: a live answer kept streaming into a detached bubble, and closing
       the studio rebuilt the list from the store, so an unanswered card and the live DOM were
       lost. `_showPanel` hides the transcript (never clears it); `_showChat` brings it back as it
       was, then re-reads the conversation so a pending question that arrived meanwhile appears. */
    _showPanel() {
        if (this._dom.panel) this._dom.panel.hidden = false;
        if (this._dom.chat) this._dom.chat.hidden = true;
    },

    /* The studio owns its own surface; one entry point so no caller can render it into the
       transcript (which used to erase a live answer). */
    _renderStudio() {
        this._showPanel();
        AIStudio.render(this._dom.panel, this);
    },

    _showChat(refresh = false) {
        if (this._dom.panel) this._dom.panel.hidden = true;
        if (this._dom.chat) this._dom.chat.hidden = false;
        /* A send always returns to the conversation first: the click ran while settings were up
           and looked inert because the panel stayed painted. */
        if (this._mode === 'chat' && !refresh) return;
        this._mode = 'chat';
        if (!this._dom.chat) return;
        if (!this._messages.length && !this._conversationId) {
            this._renderWelcome();
            return;
        }
        if (refresh && this._conversationId && !this._sending) {
            /* One fetch through the ordinary selection path: it reconciles the same DOM nodes
               (`_renderMessages`) and re-applies pending questions, instead of a second renderer. */
            this.selectConversation(this._conversationId);
        }
    },

    _renderMessages(pending) {
        if (!this._dom.chat) return;
        this._mode = 'chat';
        const chat = this._dom.chat;
        /* The transcript is RECONCILED by stored identity, never wiped and rebuilt. Two defects
           came from the wipe: switching A→B→A re-drew every row (a second area whenever a turn was
           still streaming), and a live bubble the repaint could not see was left orphaned while a
           new one was appended. */
        const existing = new Map();
        for (const child of Array.from(chat.children)) {
            const key = child.getAttribute ? String(child.getAttribute('data-ai-key') || '') : '';
            if (key && !existing.has(key)) existing.set(key, child);
        }
        if (!this._messages.length) {
            for (const child of Array.from(chat.children)) child.remove();
            this._current = null;
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
                const origin = (this._turnsById || new Map()).get(String(turnId)) || {};
                turn = {
                    kind: 'turn',
                    turnId: turnId,
                    messageId: message.id,
                    blocks: [],
                    usage: null,
                    error: '',
                    extras: [],
                    model: [origin.provider, origin.model].filter(Boolean).join(' / '),
                    skills: (origin.skills || []).map((row) => String((row && row.id) || row)).filter(Boolean),
                };
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
        /* Adopt the live bubble only while it is actually part of THIS snapshot: either the list
           carries its turn (a repaint of the same conversation mid-stream) or it carries no
           assistant row at all (the server has not written the turn's first row yet). Otherwise it
           belongs to a transcript this render is replacing. */
        const liveTurnId = String(this._current?.turnId || '');
        const storedTurns = order.filter((item) => item.kind === 'turn');
        const liveIsInSnapshot =
            !storedTurns.length || (!!liveTurnId && storedTurns.some((item) => String(item.turnId || '') === liveTurnId));
        const live =
            this._sending &&
            liveIsInSnapshot &&
            this._current &&
            this._current.el &&
            this._current.conversationId === this._conversationId
                ? this._current.el
                : null;
        if (!live) this._current = null;
        const ordered = [];
        const placed = new Set();
        const seenKeys = new Set();
        for (const item of order) {
            let key = '';
            if (item.kind === 'user') key = item.message.id ? 'message:' + String(item.message.id) : '';
            else if (item.kind === 'turn') {
                key = item.turnId || item.messageId ? 'turn:' + String(item.turnId || item.messageId) : '';
            } else key = item.message.id ? 'row:' + String(item.message.id) : '';
            if (key && seenKeys.has(key)) continue;
            if (key) seenKeys.add(key);
            let el = key ? existing.get(key) : null;
            if (el) {
                if (item.kind === 'turn') this._refreshTurnEl(el, item);
            } else if (item.kind === 'user') {
                el = this._appendUser(
                    item.message.content,
                    item.message.meta?.context,
                    item.message.meta?.attachments,
                    null,
                    false,
                    item.message.id || '',
                );
            } else if (item.kind === 'turn') {
                el = this._renderTurn(item);
            } else {
                el = this._renderStoredTool(item.message);
            }
            if (el) {
                placed.add(el);
                ordered.push(el);
            }
        }
        if (live && !placed.has(live)) ordered.push(live);
        for (const child of Array.from(chat.children)) {
            if (ordered.includes(child)) continue;
            child.remove();
        }
        /* appendChild MOVES an existing node, so walking the list in order is what places them. */
        for (const el of ordered) chat.appendChild(el);
        /* Coming back to a turn that is still streaming in another tab: its live element is stale
           by however much went by while another conversation was shown. The stored row is the
           server's truth, so adopt it when it has MORE rounds than the view already holds; equal
           length means the live text is the fresher copy of the same round. */
        if (live && this._current) {
            const stored = order.find(
                (item) => item.kind === 'turn' && String(item.turnId || '') === String(this._current.turnId || '')
            );
            if (stored && (stored.blocks || []).length > (this._current.blocks || []).length) {
                this._current.blocks = (stored.blocks || []).slice();
                this._current._flowHtml = '';
                this._paintAssistant();
            }
        }
        /* Back on a conversation whose turn is STILL streaming: adopt the stored turn element as
           the live one, so the next delta paints into it instead of appending a second bubble.
           Without this, A→B→A drew the partial answer and then a duplicate "AI" area beside it. */
        if (this._sending && this._streamTurnId && String(this._streamConversation || '') === String(this._conversationId || '')) {
            const streamEntry = order.find(
                (item) => item.kind === 'turn' && String(item.turnId || '') === String(this._streamTurnId)
            );
            const el = chat.querySelector('[data-ai-key="turn:' + String(this._streamTurnId).replace(/"/g, '') + '"]');
            if (el && (!this._current || this._current.el !== el)) {
                this._current = {
                    el,
                    conversationId: this._conversationId,
                    turnId: this._streamTurnId,
                    messageId: streamEntry ? streamEntry.messageId : '',
                    blocks: streamEntry ? (streamEntry.blocks || []).slice() : [],
                    questions: [],
                    answers: {},
                    flowEl: el.querySelector('.ai-flow'),
                    artifactsEl: el.querySelector('.ai-artifacts'),
                    questionEl: el.querySelector('.ai-question-slot'),
                    usageEl: el.querySelector('.ai-usage'),
                    _flowHtml: '',
                };
                this._paintAssistant();
            }
        }
        for (const question of pending || []) {
            /* The turn entry carries the blocks the element was drawn from; seeding the bound live
               state with them is what lets an ANSWER to this card repaint the whole turn instead of
               replacing its earlier paragraphs with only the continuation. */
            const owner = order.find(
                (item) => item.kind === 'turn' && String(item.messageId || '') === String(question.message_id || '')
            );
            this._appendQuestion(question, owner || null);
        }
        chat.scrollTop = chat.scrollHeight;
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

    /* The inside of one turn bubble. Shared by a first paint and a repaint of an element that was
       reused, so a keyed reconciliation cannot drift from a fresh render. */
    _turnHtml(turn) {
        return (
            '<div class="ai-message-role">' + AIRender.escape(I18n.t('ai.assistant')) +
            (turn.model ? ' <span class="ai-turn-model">' + AIRender.escape(turn.model) + '</span>' : '') +
            '</div><div class="ai-message-body">' +
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
            ((turn.skills || []).length
                ? '<div class="ai-note">' + AIRender.escape(I18n.t('ai.turnSkills', { skills: turn.skills.join(', ') })) + '</div>'
                : '') +
            '<div class="ai-question-slot"></div>' +
            '<div class="ai-extras"></div>' +
            '<div class="ai-usage">' + AIRender.usage(turn.usage || {}) + '</div>' +
            '<div class="ai-message-actions">' +
            '<button type="button" class="ai-ghost" data-ai-copy-answer="1">' + AIRender.escape(I18n.t('ai.copyAnswer')) + '</button>' +
            '<button type="button" class="ai-ghost" data-ai-retry="1">' + AIRender.escape(I18n.t('ai.retry')) + '</button>' +
            '</div>' +
            '</div>'
        );
    },

    _fillTurnExtras(el, turn) {
        const extras = el.querySelector('.ai-extras');
        if (!extras) return;
        extras.innerHTML = '';
        for (const message of turn.extras || []) {
            const node = this._storedRowNode(message);
            if (node) extras.appendChild(node);
        }
    },

    _turnSignature(turn) {
        return JSON.stringify({
            blocks: turn.blocks || [],
            error: turn.error || '',
            usage: turn.usage || {},
            flags: [!!turn.truncated, !!turn.stopped, !!turn.interrupted, !!turn.live],
            extras: (turn.extras || []).map((row) => String((row || {}).id || '')),
        });
    },

    _renderTurn(turn) {
        const el = document.createElement('article');
        el.className = 'ai-message assistant';
        if (turn.turnId || turn.messageId) el.setAttribute('data-ai-key', 'turn:' + String(turn.turnId || turn.messageId));
        if (turn.messageId) el.setAttribute('data-ai-message', String(turn.messageId));
        el.innerHTML = this._turnHtml(turn);
        el.__aiSig = this._turnSignature(turn);
        this._dom.chat.appendChild(el);
        this._fillTurnExtras(el, turn);
        this._applyOpenDetails(el);
        return el;
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

});
