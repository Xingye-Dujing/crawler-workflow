/* The question card and its approval preview: what the model asks, and the exact target it
 * wants approved. A card carries data-ai-* actions only; the click is delegated.
 */

Object.assign(AIRender, {
    approvalPreview(preview) {
        if (!preview || !preview.kind) return '';
        const facts = (preview.facts || []).map((fact) => {
            const key = String(fact.key || '');
            const label = I18n.has('ai.approvalField.' + key) ? I18n.t('ai.approvalField.' + key) : key;
            return (
                '<div class="ai-approval-fact"><dt>' + this.escape(label) + '</dt>' +
                '<dd><code>' + this.escape(String(fact.value || '')) + '</code></dd></div>'
            );
        }).join('');
        let diff = '';
        const lines = preview.diff || [];
        if (lines.length) {
            const rows = lines.map((line) => {
                const text = String(line);
                const tone = text.startsWith('+') ? ' add' : text.startsWith('-') ? ' del' : text.startsWith('@@') ? ' hunk' : '';
                return '<span class="ai-diff-line' + tone + '">' + this.escape(text) + '</span>';
            }).join('');
            diff =
                '<div class="ai-approval-diff">' +
                '<div class="ai-approval-diff-head">' +
                this.escape(I18n.t(preview.exists ? 'ai.approvalDiffOverwrite' : 'ai.approvalDiffNew')) +
                (preview.changed ? '' : ' · ' + this.escape(I18n.t('ai.approvalNoChange'))) +
                '</div><pre class="ai-diff">' + rows + '</pre>' +
                (preview.truncated ? '<div class="ai-hint">' + this.escape(I18n.t('ai.approvalDiffCut')) + '</div>' : '') +
                '</div>';
        } else if (preview.kind === 'write' && !preview.error) {
            diff =
                '<div class="ai-hint">' +
                this.escape(I18n.t(preview.changed ? 'ai.approvalNoDiff' : 'ai.approvalNoChange')) +
                '</div>';
        }
        return (
            '<div class="ai-approval-preview">' +
            (facts ? '<dl class="ai-approval-facts">' + facts + '</dl>' : '') +
            diff +
            (preview.error ? '<div class="ai-approval-error">' + this.escape(preview.error) + '</div>' : '') +
            '</div>'
        );
    },

    questionCard(question, answered) {
        /* An approval question is the same card with a danger tone: the runtime marks it with
           ``kind`` (and the stable id ``approval``), never with a translated sentence. */
        const approval = String(question.kind || '') === 'approval' || String(question.id || '') === 'approval';
        const options = (question.options || []).map((option, index) => {
            const description = option.description ? '<span class="ai-option-desc">' + this.escape(option.description) + '</span>' : '';
            return (
                '<button type="button" class="ai-option" data-ai-answer="' + this.escape(option.label) + '" data-ai-question="' + this.escape(question.id) + '">' +
                '<span class="ai-option-key">' + (index + 1) + '</span>' +
                '<span class="ai-option-label">' + this.escape(option.label) + description + '</span>' +
                '</button>'
            );
        }).join('');
        const custom = answered ? '' :
            '<div class="ai-question-refs" data-ai-question-refs="' + this.escape(question.id) + '"></div>' +
            '<textarea class="ai-answer-custom" data-ai-custom="' + this.escape(question.id) + '" rows="2" placeholder="' + this.escape(I18n.t('ai.customAnswerRefs')) + '"></textarea>';
        const customButton = answered ? '' : '<button type="button" class="ai-ghost" data-ai-send-custom="' + this.escape(question.id) + '">' + this.escape(I18n.t('ai.answer')) + '</button>';
        return (
            '<section class="ai-question' + (approval ? ' ai-question-approval' : '') + '" data-ai-question-card="' + this.escape(question.id) + '">' +
            '<div class="ai-question-head"><span class="ai-dot"></span>' + this.escape(question.header || I18n.t('ai.questionTitle')) +
            (approval ? '<span class="ai-chip ai-chip-danger">' + this.escape(I18n.t('ai.approvalBadge')) + '</span>' : '') +
            '</div>' +
            '<p class="ai-question-text">' + this.inline(question.question) + '</p>' +
            this.approvalPreview(question.preview) +
            '<div class="ai-options">' + options + '</div>' +
            custom + customButton +
            (answered ? '<div class="ai-question-answered">' + this.escape(I18n.t('ai.questionAnswered')) + '</div>' : '') +
            '</section>'
        );
    },

});
