/* Artifact cards: the proposal a turn produced (workflow draft, plan, chart, memory, monitor)
 * and the failed-node card that offers a rerun. A card is a preview, never a write.
 */

Object.assign(AIRender, {
    failedNodesCard(block) {
        /* A monitor's failure answer names the nodes it could rerun; the button calls the same
           server decision as the canvas's 重跑节点 and never loads the canvas here. */
        const nodes = Array.isArray(block && block.nodes) ? block.nodes : [];
        if (!nodes.length) return '';
        const runId = String(block.run_id || '');
        const workflow = String(block.workflow_name || '');
        const rows = nodes.map((node) => {
            const nid = String(node.node || node.id || '');
            const error = String(node.error || '') || I18n.t('ai.failedNodeNoError');
            const action = runId
                ? '<button type="button" class="ai-ghost" data-ai-rerun-run="' + this.escape(runId) + '" data-ai-rerun-workflow="' + this.escape(workflow) + '" data-ai-rerun-node="' + this.escape(nid) + '">' + this.escape(I18n.t('ai.rerunNode')) + '</button>'
                : '<span class="ai-hint">' + this.escape(I18n.t('ai.rerunNoWorkflowHint')) + '</span>';
            return (
                '<li class="ai-failed-node">' +
                '<span class="ai-failed-node-id">' + this.escape(nid) + '</span>' +
                '<span class="ai-failed-node-error">' + this.escape(error) + '</span>' +
                action +
                '</li>'
            );
        }).join('');
        const started = String(block.started || '');
        return (
            '<section class="ai-failed-nodes' + (started ? ' is-started' : '') + '">' +
            '<div class="ai-question-head"><span class="ai-dot"></span>' + this.escape(I18n.t('ai.failedNodesTitle')) + '</div>' +
            '<ul>' + rows + '</ul>' +
            (started ? '<div class="ai-question-answered">' + this.escape(I18n.t('ai.rerunStarted', { node: started })) + '</div>' : '') +
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
        const apply = artifact.kind === 'skill_draft'
            ? '<button type="button" class="ai-primary" data-ai-apply-skill="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.openEditor')) + '</button>'
            : artifact.kind === 'plugin_manifest'
                ? '<button type="button" class="ai-primary" data-ai-apply-plugin="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.openInstaller')) + '</button>'
                : artifact.kind === 'monitor'
                    ? '<button type="button" class="ai-primary" data-ai-apply-monitor="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.monitor.auto')) + '</button>' +
                      '<button type="button" class="ai-ghost" data-ai-watch-only="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.monitor.watchOnly')) + '</button>'
                    : artifact.kind === 'memory'
                        ? '<button type="button" class="ai-primary" data-ai-apply-memory="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.remember')) + '</button>'
                    : (artifact.kind === 'workflow' || artifact.kind === 'workflow_draft')
                        ? '<button type="button" class="ai-primary" data-ai-apply-workflow="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.workflowLoad')) + '</button>' +
                          '<button type="button" class="ai-ghost" data-ai-run-workflow="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.workflowLoadRun')) + '</button>'
                        : artifact.kind === 'chart_spec'
                            ? '<button type="button" class="ai-primary" data-ai-apply-chart="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.chartRender')) + '</button>'
                        /* Every OTHER artifact (a plan, a report) is a proposal with no
                           mechanical "apply" of its own — but it must still be actionable, or it reads
                           as a dead card. The button hands the proposal back to the assistant, which
                           builds the canvas with its validated tools. */
                        : '<button type="button" class="ai-primary" data-ai-implement-artifact="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.artifactImplement')) + '</button>';
        /* A previewable artifact gets a second, additive door: the primary button still applies
           directly, but this one shows the exact change first and lets the user pick the parts.
           The server decides which kinds have a published preview — this is only the card. */
        const previewable = ['memory', 'workflow', 'workflow_draft', 'monitor', 'chart_spec'];
        const previewButton = previewable.includes(String(artifact.kind || ''))
            ? '<button type="button" class="ai-ghost" data-ai-preview-artifact="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.preview.button')) + '</button>'
            : '';
        return (
            '<section class="ai-artifact" data-ai-artifact="' + this.escape(artifact.id || '') + '">' +
            '<div class="ai-artifact-head"><span class="ai-artifact-kind">' + this.escape(label) + '</span><span>' + this.escape(artifact.title || '') + '</span></div>' +
            summary +
            '<details class="ai-artifact-body" data-ai-detail="artifact:' + this.escape(String(artifact.id || '')) + ':body"><summary>' + this.escape(I18n.t('ai.preview')) + '</summary><pre class="ai-code">' + this.escape(JSON.stringify(artifact.payload || {}, null, 2)) + '</pre></details>' +
            '<div class="ai-artifact-actions">' + apply + previewButton + '<button type="button" class="ai-ghost" data-ai-copy-artifact="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.copy')) + '</button><span class="ai-hint">' + this.escape(I18n.t('ai.applyHint')) + '</span></div>' +
            '</section>'
        );
    },

    /* While a tool runs, say WHAT is being produced — a plan, a question, a workflow — instead of a
       generic “读取中…”. The model emits no prose before `present_artifact` / `ask_user_question`, so
       without this the turn looks stalled exactly when the useful part is being built. */
});
