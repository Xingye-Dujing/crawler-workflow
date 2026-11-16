/* Safe rendering for model output. Everything is escaped FIRST, then a small Markdown subset is
 * turned into elements; raw HTML never survives. Links are limited to http/https. */
const AIRender = {
    escape(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    safeUrl(value) {
        const raw = String(value || '').trim();
        return /^https?:\/\//i.test(raw) ? raw : '';
    },

    inline(text) {
        let out = this.escape(text);
        out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
        out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        out = out.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
        out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (match, label, url) => {
            const safe = this.safeUrl(url);
            return safe ? '<a href="' + this.escape(safe) + '" target="_blank" rel="noopener noreferrer">' + label + '</a>' : label;
        });
        return out;
    },

    markdown(text) {
        const source = String(text || '');
        const parts = [];
        let buffer = [];
        let inCode = false;
        let code = [];
        const flush = () => {
            if (buffer.length) {
                parts.push(this.paragraphs(buffer.join('\n')));
                buffer = [];
            }
        };
        for (const line of source.split(/\r?\n/)) {
            if (line.trim().startsWith('```')) {
                if (inCode) {
                    parts.push('<pre class="ai-code"><code>' + this.escape(code.join('\n')) + '</code></pre>');
                    code = [];
                    inCode = false;
                } else {
                    flush();
                    inCode = true;
                }
                continue;
            }
            if (inCode) {
                code.push(line);
            } else {
                buffer.push(line);
            }
        }
        if (inCode) parts.push('<pre class="ai-code"><code>' + this.escape(code.join('\n')) + '</code></pre>');
        flush();
        return parts.join('');
    },

    paragraphs(text) {
        const lines = text.split(/\r?\n/);
        const out = [];
        let list = null;
        let table = null;
        const closeList = () => {
            if (list) {
                out.push('<' + list.tag + '>' + list.items.map((item) => '<li>' + this.inline(item) + '</li>').join('') + '</' + list.tag + '>');
                list = null;
            }
        };
        const closeTable = () => {
            if (table) {
                const head = '<thead><tr>' + table.head.map((cell) => '<th>' + this.inline(cell) + '</th>').join('') + '</tr></thead>';
                const body = '<tbody>' + table.rows.map((row) => '<tr>' + row.map((cell) => '<td>' + this.inline(cell) + '</td>').join('') + '</tr>').join('') + '</tbody>';
                out.push('<div class="ai-table-wrap"><table class="ai-table">' + head + body + '</table></div>');
                table = null;
            }
        };
        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) {
                closeList();
                closeTable();
                continue;
            }
            if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
                closeList();
                const cells = trimmed.slice(1, -1).split('|').map((cell) => cell.trim());
                if (cells.every((cell) => /^:?-{2,}:?$/.test(cell))) continue;
                if (!table) table = { head: cells, rows: [] };
                else table.rows.push(cells);
                continue;
            }
            closeTable();
            const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
            if (heading) {
                closeList();
                const level = Math.min(4, heading[1].length);
                out.push('<h' + level + '>' + this.inline(heading[2]) + '</h' + level + '>');
                continue;
            }
            if (/^>\s?/.test(trimmed)) {
                closeList();
                out.push('<blockquote>' + this.inline(trimmed.replace(/^>\s?/, '')) + '</blockquote>');
                continue;
            }
            const ordered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
            const bullet = /^[-*+]\s+(.*)$/.exec(trimmed);
            if (ordered || bullet) {
                closeTable();
                const tag = ordered ? 'ol' : 'ul';
                if (!list || list.tag !== tag) {
                    closeList();
                    list = { tag, items: [] };
                }
                list.items.push((ordered || bullet)[1]);
                continue;
            }
            closeList();
            out.push('<p>' + this.inline(trimmed) + '</p>');
        }
        closeList();
        closeTable();
        return out.join('');
    },

    questionCard(question, answered) {
        const options = (question.options || []).map((option, index) => {
            const description = option.description ? '<span class="ai-option-desc">' + this.escape(option.description) + '</span>' : '';
            return (
                '<button type="button" class="ai-option" data-ai-answer="' + this.escape(option.label) + '" data-ai-question="' + this.escape(question.id) + '">' +
                '<span class="ai-option-key">' + (index + 1) + '</span>' +
                '<span class="ai-option-label">' + this.escape(option.label) + description + '</span>' +
                '</button>'
            );
        }).join('');
        const custom = answered ? '' : '<textarea class="ai-answer-custom" data-ai-custom="' + this.escape(question.id) + '" rows="2" placeholder="' + this.escape(I18n.t('ai.customAnswer')) + '"></textarea>';
        const customButton = answered ? '' : '<button type="button" class="ai-ghost" data-ai-send-custom="' + this.escape(question.id) + '">' + this.escape(I18n.t('ai.answer')) + '</button>';
        return (
            '<section class="ai-question" data-ai-question-card="' + this.escape(question.id) + '">' +
            '<div class="ai-question-head"><span class="ai-dot"></span>' + this.escape(question.header || I18n.t('ai.questionTitle')) + '</div>' +
            '<p class="ai-question-text">' + this.inline(question.question) + '</p>' +
            '<div class="ai-options">' + options + '</div>' +
            custom + customButton +
            (answered ? '<div class="ai-question-answered">' + this.escape(I18n.t('ai.questionAnswered')) + '</div>' : '') +
            '</section>'
        );
    },

    sourceCard(block) {
        if (!block || typeof block !== 'object') return '';
        if (block.type === 'server_tool_use') {
            const action = block.input || {};
            if (action.action === 'search' || action.action === 'deep_search') {
                const queries = (action.queries || []).map((query) => '“' + this.escape(query) + '”').join(' ');
                return '<div class="ai-source-card"><span class="ai-source-kind">' + this.escape(I18n.t('ai.searching')) + '</span>' + queries + '</div>';
            }
            if (action.action === 'open_page' || action.action === 'read_link') {
                const url = this.safeUrl(action.url);
                return '<div class="ai-source-card"><span class="ai-source-kind">' + this.escape(I18n.t('ai.reading')) + '</span>' + (url ? '<a href="' + this.escape(url) + '" target="_blank" rel="noopener noreferrer">' + this.escape(url) + '</a>' : this.escape(action.url || '')) + '</div>';
            }
            if (action.action === 'find_in_page') {
                return '<div class="ai-source-card"><span class="ai-source-kind">' + this.escape(I18n.t('ai.reading')) + '</span>' + this.escape(action.pattern || '') + '</div>';
            }
            return '';
        }
        if (block.type === 'web_search_tool_result') {
            const results = (block.content || []).filter((item) => item && item.type === 'web_search_result');
            if (!results.length) {
                const error = (block.content || [])[0] || {};
                return '<div class="ai-source-card ai-source-error">' + this.escape(error.error_code || 'search unavailable') + '</div>';
            }
            return results.map((item, index) =>
                '<a class="ai-source-card ai-source-link" href="' + this.escape(this.safeUrl(item.url)) + '" target="_blank" rel="noopener noreferrer">' +
                '<span class="ai-source-index">' + (index + 1) + '</span>' +
                '<span class="ai-source-body"><span class="ai-source-title">' + this.escape(item.title || item.url) + '</span>' +
                '<span class="ai-source-meta">' + this.escape(item.site_name || '') + (item.page_age ? ' · ' + this.escape(String(item.page_age).slice(0, 10)) : '') + '</span>' +
                (item.snippet ? '<span class="ai-source-snippet">' + this.escape(item.snippet) + '</span>' : '') +
                '</span></a>'
            ).join('');
        }
        if (block.type === 'web_fetch_tool_result') {
            const content = block.content || {};
            if (content.type === 'web_fetch_tool_result_error') {
                return '<div class="ai-source-card ai-source-error">' + this.escape(content.error_code || 'fetch failed') + '</div>';
            }
            const url = this.safeUrl(content.url);
            return '<div class="ai-source-card"><span class="ai-source-kind">' + this.escape(I18n.t('ai.reading')) + '</span>' + (url ? '<a href="' + this.escape(url) + '" target="_blank" rel="noopener noreferrer">' + this.escape(content.content?.title || url) + '</a>' : this.escape(content.content?.title || '')) + '</div>';
        }
        return '';
    },

    artifactCard(artifact) {
        if (!artifact) return '';
        const label = I18n.t('ai.artifact') + ' · ' + String(artifact.kind || 'markdown');
        const summary = artifact.summary ? '<p class="ai-artifact-summary">' + this.inline(artifact.summary) + '</p>' : '';
        return (
            '<section class="ai-artifact" data-ai-artifact="' + this.escape(artifact.id || '') + '">' +
            '<div class="ai-artifact-head"><span class="ai-artifact-kind">' + this.escape(label) + '</span><span>' + this.escape(artifact.title || '') + '</span></div>' +
            summary +
            '<details class="ai-artifact-body"><summary>' + this.escape(I18n.t('ai.preview')) + '</summary><pre class="ai-code">' + this.escape(JSON.stringify(artifact.payload || {}, null, 2)) + '</pre></details>' +
            '<div class="ai-artifact-actions"><button type="button" class="ai-ghost" data-ai-copy-artifact="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.copy')) + '</button><span class="ai-hint">' + this.escape(I18n.t('ai.applyHint')) + '</span></div>' +
            '</section>'
        );
    },

    toolCard(name, args, status, result) {
        const summary = status === 'running' ? I18n.t('ai.toolRunning') : status === 'failed' ? I18n.t('ai.toolFailed') : I18n.t('ai.toolDone');
        const detail = status === 'done' && result
            ? '<details class="ai-tool-detail"><summary>' + this.escape(I18n.t('ai.toolResult')) + '</summary><pre class="ai-code">' + this.escape(JSON.stringify(result, null, 2)) + '</pre></details>'
            : '';
        return (
            '<div class="ai-tool ' + (status === 'running' ? 'is-running' : status === 'failed' ? 'is-failed' : '') + '">' +
            '<span class="ai-tool-dot"></span><span class="ai-tool-name">' + this.escape(name) + '</span>' +
            '<span class="ai-tool-state">' + this.escape(summary) + '</span>' +
            detail +
            '</div>'
        );
    },

    usage(usage) {
        if (!usage) return '';
        return (
            '<div class="ai-usage">' +
            this.escape(I18n.t('ai.usageLine', {
                prompt: usage.prompt_tokens || 0,
                completion: usage.completion_tokens || 0,
                cached: usage.cached_tokens || 0,
            })) +
            '</div>'
        );
    },

    number(value) {
        return Number(value || 0).toLocaleString();
    },
};
window.AIRender = AIRender;
