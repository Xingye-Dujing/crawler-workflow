/* A reopened turn: the rows the server stored, drawn the same way the live one was.
 *
 * Each row knows its own tool and artifact cards, so a reload neither duplicates a card nor drops
 * one, and a two-round turn stays one bubble.
 */

Object.assign(AIWorkspace, {
    /* A stored row that stands on its own (an answered question, an artifact) still belongs in the
       assistant's COLUMN: `.ai-message` is a role + body grid, and appending a bare card put it at
       the panel's left edge, above the next "AI" label. */
    _wrapStoredRow(el) {
        if (!el) return null;
        const article = document.createElement('article');
        article.className = 'ai-message assistant ai-message-tool';
        article.innerHTML = '<div class="ai-message-role"></div><div class="ai-message-body"></div>';
        const body = article.querySelector('.ai-message-body');
        if (body) body.appendChild(el);
        else article.appendChild(el);
        this._dom.chat.appendChild(article);
        this._applyOpenDetails(article);
        return article;
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
        if (!node) return null;
        const article = this._wrapStoredRow(node);
        if (article && message && message.id) {
            article.setAttribute('data-ai-key', 'row:' + String(message.id));
            article.setAttribute('data-ai-message', String(message.id));
        }
        return article;
    },

});
