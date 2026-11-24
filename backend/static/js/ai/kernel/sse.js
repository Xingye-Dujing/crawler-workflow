/* The event stream and the live turn.
 *
 * POST + `fetch` is used instead of EventSource because the request carries a body and the
 * Authorization material is never placed in a URL. The decoder follows the WHATWG framing rules:
 * multi-line data joins with a newline, comments are ignored, and a blank line dispatches.
 * `_onEvent` is the reducer: every provider is reduced to the same event names by the server, and
 * the turn's blocks, plan, usage and verdict are written by that one function. */

const AIStream = {
    async post(url, body, onEvent, signal) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
            body: JSON.stringify(body),
            signal,
        });
        if (!response.ok) {
            let message = response.statusText || ('HTTP ' + response.status);
            try {
                const payload = await response.json();
                message = payload.error || message;
            } catch (e) {
                /* a non-JSON error keeps the status text */
            }
            throw new Error(message);
        }
        if (!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
            const separator = url.includes('?') ? '&' : '?';
            const fallback = await fetch(url + separator + 'stream=0', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal,
            });
            const payload = await fallback.json();
            if (!fallback.ok || payload.ok === false) throw new Error(payload.error || 'request failed');
            for (const event of payload.events || []) onEvent(event);
            return;
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let dataLines = [];
        const dispatch = () => {
            if (!dataLines.length) return;
            const raw = dataLines.join('\n');
            dataLines = [];
            let event;
            try {
                event = JSON.parse(raw);
            } catch (e) {
                return;
            }
            onEvent(event);
        };
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let lineStart = 0;
            for (let index = 0; index < buffer.length; index += 1) {
                if (buffer[index] !== '\n' && buffer[index] !== '\r') continue;
                const line = buffer.slice(lineStart, index);
                lineStart = index + 1;
                if (line === '') {
                    dispatch();
                } else if (line.startsWith('data:')) {
                    dataLines.push(line.slice(5).replace(/^ /, ''));
                }
            }
            buffer = buffer.slice(lineStart);
        }
        buffer += decoder.decode();
        if (buffer.startsWith('data:')) dataLines.push(buffer.slice(5).replace(/^ /, ''));
        dispatch();
    },
};
window.AIStream = AIStream;

Object.assign(AIWorkspace, {
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

    /* Follow a node-trace conversation while a run writes it. There is no SSE stream to this page:
       the row runner appends new messages (one per row) and streams tokens into the current one.
       Two jobs, kept apart so the recording neither misses rows nor flickers:
         - NEW message (another row answered): re-render the whole transcript once via
           selectConversation, so the user sees all 3 rows' Q&A appear in sequence;
         - tokens arriving in an EXISTING message: update only that bubble's `.ai-flow`, with a per
           message HTML memo, so a repaint with no new text never rewrites the DOM (no flicker).
       Stops when the run's closing trace_result row appears — NOT on a quiet poll: a multi-batch
       run has gaps between rows, and a traditional node has no streaming row at all before its
       final sample. If the user selects another conversation or starts their own turn, stop
       following so we never repaint the transcript they are reading. */
    async pumpTraceStream(conversationId) {
        if (!conversationId || !this._dom.chat) return;
        const memos = new Map();
        const seen = new Set();
        const deadline = Date.now() + 180000;
        let adopted = false;  // becomes true once this trace has actually been painted
        while (Date.now() < deadline) {
            if (this._sending || (adopted && this._conversationId && this._conversationId !== conversationId)) break;
            try {
                const { data } = await AIHttp.get('/conversations/' + encodeURIComponent(conversationId));
                if (!data.ok) break;
                const messages = data.messages || [];
                const ids = messages.map((message) => String(message.id));
                const isNew = ids.some((id) => !seen.has(id));
                ids.forEach((id) => seen.add(id));

                if (isNew) {
                    /* A fresh row's Q&A just landed — repaint once so its bubble exists at all.
                       This is the one full re-render per new message (3 rows => at most 3). */
                    await this.selectConversation(conversationId);
                    adopted = true;
                    for (const message of messages) {
                        if (message.role === 'assistant' && String(message.status || '') !== 'streaming') {
                            const html = AIRender.assistantFlow(message.blocks || []);
                            memos.set(String(message.id), html);
                        }
                    }
                }

                let closed = false;
                for (const message of messages) {
                    if (String((message.meta || {}).kind || '') === 'trace_result') closed = true;
                    if (message.role !== 'assistant') continue;
                    const streaming = String(message.status || '') === 'streaming';
                    const selector = '[data-ai-message="' + String(message.id).replace(/"/g, '') + '"]';
                    const el = this._dom.chat.querySelector(selector);
                    const flow = el && el.querySelector('.ai-flow');
                    if (!flow) continue;
                    const html = AIRender.assistantFlow(message.blocks || []);
                    if (memos.get(String(message.id)) === html) continue;
                    memos.set(String(message.id), html);
                    flow.innerHTML = html;
                    if (!streaming && el.querySelector('.ai-note')) {
                        const noteText = I18n.t('ai.stillStreaming');
                        for (const note of el.querySelectorAll('.ai-note')) {
                            if (note.textContent.indexOf(noteText) >= 0) note.hidden = true;
                        }
                    }
                }
                if (closed) break;
            } catch (e) {
                break;
            }
            await new Promise((resolve) => setTimeout(resolve, 350));
        }
    },

    /* `path` is a workspace route (``/chat``), not a URL: the prefix is `AIHttp`'s, so this file and
       the three callers never spell it. */
    async _stream(path, body) {
        this._abort = new AbortController();
        await AIStream.post(AIHttp.url(path), body, (event) => this._onEvent(event), this._abort.signal);
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
            this._streamTurnId = String(event.turn_id || '');
            this._current.conversationId = this._conversationId;
            /* The SAME identity the stored row will carry. A later reconcile matches the live
               bubble by this key instead of building a second one for the same turn. */
            if (event.turn_id) this._current.el.setAttribute('data-ai-key', 'turn:' + String(event.turn_id));
            if (event.message_id) this._current.el.setAttribute('data-ai-message', String(event.message_id));
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
        if (type === 'recipe') {
            /* The server owns the run; this event is its current step. A done run hides the strip. */
            this._recipe = event;
            this._renderRecipe();
            return;
        }
        if (type === 'plan') {            this._plan = event.steps || [];
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
            this._applyWorkflowPayload(event.workflow || {}, !!event.run, String(event.name || ''), { detach: true });
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
            /* A pause is an ending of THIS stream (the answer resumes through `/api/ai/ws/answer`), so
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
            /* An answered access card may have created a grant; the panel must show it without
               waiting for the user to reopen the conversation. */
            this._loadDatasetGrants();
            return;
        }
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
        this._streamTurnId = '';
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

});
