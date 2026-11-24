/* Answering a question card: which options are chosen, the custom box with its own `@` references,
 * and the single submit that becomes a tool result on the server.
 *
 * The card submits only when every question is answered; a click has to show that it registered
 * before that, or a multi-question card reads as a dead button.
 */

Object.assign(AIWorkspace, {
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

    _appendQuestion(question, turn = null) {
        const messageId = String(question.message_id || '');
        /* A restored pending card belongs to the turn that ASKED it (the stored assistant row),
           not to a fresh "AI" bubble appended after the transcript. That extra bubble was the
           second message area a reopened chat showed. */
        const hostEl = messageId
            ? this._dom.chat.querySelector('[data-ai-message="' + messageId.replace(/"/g, '') + '"]')
            : null;
        if (!this._current || (hostEl && this._current.el !== hostEl)) {
            if (!hostEl) {
                this._current = this._ensureAssistant();
            } else {
                this._current = {
                    el: hostEl,
                    blocks: turn ? (turn.blocks || []).slice() : [],
                    questions: [],
                    answers: {},
                    turnId: turn ? turn.turnId : '',
                    flowEl: hostEl.querySelector('.ai-flow'),
                    artifactsEl: hostEl.querySelector('.ai-artifacts'),
                    usageEl: hostEl.querySelector('.ai-usage'),
                };
            }
        }
        let slot = this._current.questionEl;
        if (!slot || !slot.parentElement) {
            slot = hostEl ? hostEl.querySelector('.ai-question-slot') : null;
            if (!slot) {
                slot = document.createElement('div');
                slot.className = 'ai-question-slot';
                const body = (hostEl && hostEl.querySelector('.ai-message-body')) || hostEl || this._current.el;
                body.appendChild(slot);
            }
            this._current.questionEl = slot;
        }
        this._current.conversationId = this._conversationId;
        this._current.questions = question.questions || [];
        this._current.answers = this._current.answers || {};
        this._current.questionId = question.id;
        this._current.questionMessageId = question.message_id;
        /* A restored card has no live `messageId`; the answer request must still carry the
           assistant row that asked it. The server also derives it from the question row, but
           keeping both in sync here makes the DOM state honest on its own. */
        this._current.messageId = question.message_id || this._current.messageId;
        const cardId = String(question.id || '').replace(/"/g, '');
        if (cardId && slot.querySelector('[data-ai-question-card="' + cardId + '"]')) return;
        this._current.questionEl.innerHTML = this._current.questions.map((item) => AIRender.questionCard(item, false)).join('');
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
            /* Multi-select is confirmed by the card's answer box/button, not by the first
               click: writing the current set here keeps the progress hint honest and lets
               the user pick several options before submitting. */
            current.answers[questionId] = { id: questionId, selected: this._selectedLabels(questionId) };
            this._renderAnswerProgress();
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
            await this._stream(AI_BASE + '/answer', {
                conversation_id: this._conversationId,
                message_id: current.messageId || current.questionMessageId,
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

});
