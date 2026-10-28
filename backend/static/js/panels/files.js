/* The workflow-file manager: saved canvases, canvas history and reusable templates.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-29) byte for byte. Three tabs rather than three
 * panels, because all three answer "what is stored for THIS canvas" and the dock slot is already
 * where a person looks for a saved canvas. The run gate that refuses these actions mid-run is not
 * this panel's business and stayed in ``workflow.js``.
 */

/* The workflow-file manager (task #115). The menu 「打开」 only ever had a file
   picker; this lists what is saved and lets the user 打开 / 重命名 / 删除 without
   guessing which stems exist. It reuses the runs/dataset panels' delegated-button +
   escaping shape, not a second invention. */
var wfFiles = {
    /* The panel answers three different questions: which files exist (open/rename/delete),
       which canvas states the user kept (restore/delete/baseline), and which reusable
       templates are stored (insert/delete). They are tabs rather than panels because all
       three are about "this canvas", and the dock slot is already the place a person looks
       for a saved canvas. */
    _tab: 'files',
    _history: null,
    _historyMax: 0,
    _templates: null,

    panel() {
        return document.getElementById('workflows-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('workflows-panel');
        panel.classList.add('open');
        this.refresh();
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        panel.style.height = '';
    },

    /* ── project bundle: one zip for a canvas and the files it reads ──
       The server decides what a bundle contains and rewrites ids on import; the
       browser only chooses current/all, downloads the attachment, and explains
       the rename/warning summary it gets back. */
    async exportProject() {
        var current = (typeof workflow !== 'undefined' && workflow.currentFile) || '';
        var choice = await showDialog({
            message: I18n.t('wfProject.exportPrompt'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('wfProject.current'), value: 'current', primary: true },
                { label: I18n.t('wfProject.all'), value: 'all' },
            ],
        });
        if (!choice) return;
        if (choice === 'current' && !current) {
            showToast(I18n.t('wfProject.noWorkflow'));
            return;
        }
        var query = choice === 'all' ? 'all=1' : 'workflow=' + encodeURIComponent(current);
        var response = await fetch('/api/project/export?' + query);
        if (!response.ok) {
            var detail = null;
            try { detail = await response.json(); } catch (e) { detail = null; }
            showToast((detail && detail.error) || I18n.t('wfProject.exportFailed'));
            return;
        }
        var blob = await response.blob();
        var filename = 'project.zip';
        var disposition = response.headers.get('Content-Disposition') || '';
        var match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition);
        if (match) {
            try { filename = decodeURIComponent(match[1].replace(/"/g, '')); } catch (e) { /* keep the fallback */ }
        }
        var url = URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = url;
        link.download = filename;
        link.style.display = 'none';
        document.body.appendChild(link);
        if (typeof link.click === 'function') link.click();
        if (link.parentNode) link.parentNode.removeChild(link);
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        var warnings = Number(response.headers.get('X-Project-Warnings') || 0) || 0;
        showToast(warnings ? I18n.t('wfProject.exportedWarn', { n: warnings }) : I18n.t('wfProject.exported'));
    },

    pickProjectBundle() {
        var input = document.getElementById('project-bundle-input');
        if (!input) return;
        input.value = '';
        input.click();
    },

    async importProject(input) {
        var file = input && input.files && input.files[0];
        if (input) input.value = '';
        if (!file) return;
        var form = new FormData();
        form.append('file', file, file.name || 'project.zip');
        var response = await fetch('/api/project/import', { method: 'POST', body: form });
        var result = null;
        try { result = await response.json(); } catch (e) { result = null; }
        if (!response.ok || !result || !result.ok) {
            showToast((result && result.error) || I18n.t('wfProject.importFailed'));
            return;
        }
        var summary = result.summary || {};
        var workflows = summary.workflows || [];
        var names = workflows.map(function (row) { return row.to || row.from; }).join(', ');
        var message = workflows.length
            ? I18n.t('wfProject.imported', { n: workflows.length, names: names })
            : I18n.t('wfProject.importedNone');
        var warnings = (summary.warnings || []).length;
        if (warnings) message += ' ' + I18n.t('wfProject.warnings', { n: warnings });
        showToast(message, 8000);
        this._tab = 'files';
        await this.refresh();
    },

    async refresh() {
        var body = document.getElementById('workflows-mgr-body');
        if (!body) return;
        this.renderTabs();
        var bar = document.getElementById('workflows-history-bar');
        if (bar) bar.hidden = this._tab !== 'history';
        if (this._tab === 'history') {
            await this.refreshHistory();
            return;
        }
        if (this._tab === 'reusable') {
            await this.refreshReusable();
            return;
        }
        body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfMgr.loading') + '</div>';
        var result = await fetchJSON('/api/workflow/list').catch(function () { return null; });
        if (!result || !result.ok) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfMgr.loadFailed') + '</div>';
            return;
        }
        this._last = result.workflows || [];
        this.render();
    },

    /* Three views, one body. 工作流文件 is "what is on disk"; 画布历史 is "what this
       canvas has been"; 可复用节点 is "which saved fragments can be inserted or deleted".
       Keeping the label of the inactive tab out of the table means the switch is a
       repaint, not a second panel with its own close button. */
    renderTabs() {
        var tabs = document.getElementById('workflows-tabs');
        if (!tabs) return;
        var historyCount = (this._history || []).length;
        var templateCount = (this._templates || []).length;
        var self = this;
        var label = function (key, textKey, count) {
            var active = self._tab === key;
            return (
                '<div class="runs-tab' + (active ? ' active' : '') +
                '" role="tab" aria-selected="' + (active ? 'true' : 'false') +
                '" onclick="wfFiles.switchTab(\'' + key + '\')">' +
                I18n.t(textKey) +
                (count ? ' (' + count + ')' : '') +
                '</div>'
            );
        };
        tabs.innerHTML =
            label('files', 'wfHistory.tabFiles', 0) +
            label('history', 'wfHistory.tabHistory', historyCount) +
            label('reusable', 'reusable.templatesTab', templateCount);
    },

    switchTab(tab) {
        var next = tab === 'history' ? 'history' : (tab === 'reusable' ? 'reusable' : 'files');
        if (next === this._tab) return;
        this._tab = next;
        this.refresh();
    },

    /* Reachable from the Style menu's baseline row: a person choosing a baseline needs
       the list in front of them, not a second place that merely mentions it. */
    openHistory() {
        var panel = this.panel();
        if (!panel) return;
        if (typeof closeStyleMenu === 'function') closeStyleMenu();
        if (!panel.classList.contains('open')) {
            closeDockedPanels('workflows-panel');
            panel.classList.add('open');
        }
        this._tab = 'history';
        this.refresh();
    },

    async refreshHistory() {
        var body = document.getElementById('workflows-mgr-body');
        if (!body) return;
        body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfHistory.loading') + '</div>';
        var result = await fetchJSON('/api/workflow/history');
        if (!result || !result.ok) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfHistory.loadFailed') + '</div>';
            return;
        }
        this._history = result.snapshots || [];
        this._historyMax = result.max || 0;
        /* The baseline tag belongs to the same row list; one read keeps the tag and
           the Style menu's hint from disagreeing after a delete. */
        if (typeof LayoutStrategy !== 'undefined') await LayoutStrategy.refresh();
        this.renderTabs();
        this.renderHistory();
    },

    renderHistory() {
        var body = document.getElementById('workflows-mgr-body');
        if (!body) return;
        this._paintCapacity();
        var rows = this._history || [];
        if (!rows.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfHistory.empty') + '</div>';
            return;
        }
        var self = this;
        var layout = (typeof LayoutStrategy !== 'undefined' && LayoutStrategy.current) ? LayoutStrategy.current() : {};
        var baselineId = (layout.snapshot && layout.snapshot.id) || '';
        var html = rows.map(function (row) {
            var name = String(row.label || '') || I18n.t('wfHistory.untitled');
            var source = String(row.workflow_name || '') || I18n.t('wfHistory.noWorkflow');
            var tag = row.id === baselineId
                ? '<span class="wf-snap-baseline">' + escapeHtml(I18n.t('wfHistory.baselineTag')) + '</span>'
                : '';
            var ops =
                '<button class="runs-mgr-btn" onclick="wfFiles.restoreSnapshot(\'' + self._quote(row.id) + '\')">' +
                I18n.t('wfHistory.restore') + '</button>' +
                '<button class="runs-mgr-btn" onclick="wfFiles.renameSnapshot(\'' + self._quote(row.id) + '\')">' +
                I18n.t('wfHistory.rename') + '</button>' +
                '<button class="runs-mgr-btn" onclick="wfFiles.setBaseline(\'' + self._quote(row.id) + '\')">' +
                I18n.t('wfHistory.baseline') + '</button>' +
                '<button class="runs-mgr-btn del" onclick="wfFiles.deleteSnapshot(\'' + self._quote(row.id) + '\')">' +
                I18n.t('wfHistory.remove') + '</button>';
            return '<tr>' +
                '<td class="runs-mgr-wf"><span class="wf-snap-name">' + escapeHtml(name) + tag + '</span>' +
                '<span class="wf-snap-source">' + escapeHtml(source) + '</span></td>' +
                '<td>' + (row.nodes || 0) + ' / ' + (row.connections || 0) + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(self._when(row.created_at)) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        body.innerHTML =
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('wfHistory.colSnapshot') + '</th>' +
            '<th>' + I18n.t('wfHistory.colNodes') + '</th>' +
            '<th>' + I18n.t('wfHistory.colSaved') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>';
    },

    /* ── Reusable templates: insert / delete ─────────────────────────
       The template store has had a delete endpoint since the feature landed;
       without a list a saved template could only be removed through the API.
       This is the management door, and it says plainly that deleting a template
       does not touch instances (they carry their own snapshot). */
    async refreshReusable() {
        var body = document.getElementById('workflows-mgr-body');
        if (!body) return;
        body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfHistory.loading') + '</div>';
        var result = await fetchJSON('/api/reusable');
        if (!result || !result.ok) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('reusable.loadFailed') + '</div>';
            return;
        }
        this._templates = result.templates || [];
        this.renderTabs();
        this.renderReusable();
    },

    renderReusable() {
        var body = document.getElementById('workflows-mgr-body');
        if (!body) return;
        var rows = this._templates || [];
        if (!rows.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('reusable.none') + '</div>';
            return;
        }
        var self = this;
        var html = rows.map(function (row) {
            var name = String(row.name || '') || String(row.id || '');
            var source = String(row.description || '') || String(row.id || '');
            var broken = row.broken
                ? ' <span class="runs-mgr-cur">' + escapeHtml(I18n.t('wfMgr.broken')) + '</span>'
                : '';
            var handle = row.broken
                ? ''
                : '<span class="wf-template-drag" draggable="true" title="' +
                    escapeHtml(I18n.t('reusable.dragHint')) + '"' +
                    ' ondragstart="wfFiles.dragTemplate(event, \'' + self._quote(row.id) + '\')"' +
                    ' ondragend="wfFiles.endTemplateDrag(event)">⋮⋮</span>';
            var ops = '';
            if (!row.broken) {
                ops += '<button class="runs-mgr-btn" onclick="wfFiles.previewTemplate(\'' + self._quote(row.id) + '\')">' +
                    I18n.t('reusable.preview') + '</button>';
                ops += '<button class="runs-mgr-btn" onclick="wfFiles.insertTemplate(\'' + self._quote(row.id) + '\')">' +
                    I18n.t('reusable.insert') + '</button>';
                ops += '<button class="runs-mgr-btn" onclick="wfFiles.renameTemplate(\'' + self._quote(row.id) + '\')">' +
                    I18n.t('reusable.rename') + '</button>';
            }
            ops += '<button class="runs-mgr-btn del" onclick="wfFiles.removeTemplate(\'' + self._quote(row.id) + '\')">' +
                I18n.t('reusable.removeTemplate') + '</button>';
            var seconds = Date.parse(String(row.updated_at || '')) / 1000;
            return '<tr>' +
                '<td class="runs-mgr-wf"><span class="wf-snap-name">' +
                handle + escapeHtml(name) + broken + '</span>' +
                '<span class="wf-snap-source">' + escapeHtml(source) + '</span></td>' +
                '<td>' + (row.nodes || 0) + ' / ' + (row.inputs || 0) + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(self._when(seconds)) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        body.innerHTML =
            '<div class="wf-tab-hint">' + I18n.t('reusable.dragHint') + '</div>' +
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('reusable.colName') + '</th>' +
            '<th>' + I18n.t('reusable.colNodes') + '</th>' +
            '<th>' + I18n.t('reusable.colUpdated') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>';
    },

    /* HTML5 drag from the template row: the private MIME type tells the canvas which
       template is in flight; the landing coordinates come from the drop event, so a
       drag can never be confused with the panel's fixed-position insertion. */
    dragTemplate(event, id) {
        if (!event || !event.dataTransfer) return;
        var row = this._templateRow(id);
        if (!row || row.broken) return;
        event.dataTransfer.setData('application/x-reusable-template', String(id));
        event.dataTransfer.effectAllowed = 'copy';
        if (event.currentTarget && event.currentTarget.classList) event.currentTarget.classList.add('dragging');
    },

    endTemplateDrag(event) {
        if (event && event.currentTarget && event.currentTarget.classList) {
            event.currentTarget.classList.remove('dragging');
        }
    },

    _templateRow(id) {
        var wanted = String(id || '');
        return (this._templates || []).find(function (row) { return String(row.id) === wanted; }) || null;
    },

    async previewTemplate(id) {
        if (typeof ReusableNodes === 'undefined' || !ReusableNodes.previewTemplate) {
            showToast(I18n.t('reusable.previewFailed'));
            return;
        }
        var result = await fetchJSON('/api/reusable/get?id=' + encodeURIComponent(id));
        if (!result || !result.ok || !result.template) {
            showToast((result && result.error) || I18n.t('reusable.previewFailed'));
            return;
        }
        ReusableNodes.previewTemplate(result.template);
    },

    async renameTemplate(id) {
        var row = this._templateRow(id);
        if (!row || row.broken) return;
        var current = String(row.name || '');
        var answer = await showDialog({
            message: I18n.t('reusable.renamePrompt', { name: current }),
            input: { value: current, placeholder: I18n.t('reusable.renamePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('reusable.rename'), primary: true },
            ],
        });
        if (answer === null) return;
        var name = String(answer || '').trim();
        if (!name) {
            showToast(I18n.t('reusable.nameRequired'));
            return;
        }
        if (name === current) return;
        var result = await fetchJSON('/api/reusable/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ id: id, name: name }),
        });
        if (!result || !result.ok) {
            showToast((result && result.error) || I18n.t('reusable.renameFailed'));
            return;
        }
        showToast(I18n.t('reusable.renamed'));
        await this.refreshReusable();
    },

    async removeTemplate(id) {
        var row = this._templateRow(id);
        var name = (row && String(row.name || '')) || String(id);
        var ok = await showDialog({
            message: I18n.t('reusable.confirmRemoveTemplate', { name: name }),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('reusable.removeTemplate'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/reusable/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ id: id }),
        });
        if (!result || !result.ok) {
            showToast((result && result.error) || I18n.t('reusable.templateRemoveFailed'));
            return;
        }
        showToast(I18n.t('reusable.templateRemoved'));
        await this.refreshReusable();
    },

    async insertTemplate(id) {
        if (typeof ReusableNodes === 'undefined' || !ReusableNodes.insertTemplate) {
            showToast(I18n.t('reusable.insertFailed'));
            return;
        }
        var newId = await ReusableNodes.insertTemplate(id, true);
        if (newId) this.close();
    },

    _snapshotRow(id) {
        var wanted = String(id || '');
        return (this._history || []).find(function (row) { return String(row.id) === wanted; }) || null;
    },

    _snapshotLabel(row) {
        return (row && String(row.label || '')) || I18n.t('wfHistory.untitled');
    },

    _paintCapacity() {
        var el = document.getElementById('workflows-history-capacity');
        if (!el) return;
        var total = (this._history || []).length;
        var max = Number(this._historyMax) || 0;
        el.textContent = max ? I18n.t('wfHistory.capacity', { n: total, max: max }) : '';
    },

    async renameSnapshot(id) {
        var row = this._snapshotRow(id);
        if (!row) return;
        var current = String(row.label || '');
        var answer = await showDialog({
            message: I18n.t('wfHistory.renamePrompt', { label: this._snapshotLabel(row) }),
            input: { value: current, placeholder: I18n.t('wfHistory.renamePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('wfHistory.rename'), primary: true },
            ],
        });
        if (answer === null) return;
        var label = String(answer || '').trim();
        if (label === current) return;
        var result = await fetchJSON('/api/workflow/history/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ id: id, label: label }),
        });
        if (!result || !result.ok) {
            showToast((result && result.error) || I18n.t('wfHistory.renameFailed'));
            return;
        }
        showToast(I18n.t('wfHistory.renamed'));
        await this.refreshHistory();
    },

    async saveSnapshot() {
        /* A manual snapshot is quick on purpose: the name is optional, and a blank one
           is displayed as 未命名快照 + its time rather than baked into the row. */
        var label = await showDialog({
            message: I18n.t('wfHistory.savePrompt'),
            input: { value: '', placeholder: I18n.t('wfHistory.savePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('wfHistory.save'), primary: true },
            ],
        });
        if (label === null) return;
        var result = await fetchJSON('/api/workflow/history/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({
                label: label,
                workflow_name: (typeof workflow !== 'undefined' && workflow.runName) ? workflow.runName() : '',
                workflow: (typeof canvas !== 'undefined' && canvas) ? canvas.toWorkflowJSON({ expandReusable: false }) : null,
            }),
        });
        if (result && result.ok) {
            showToast(I18n.t('wfHistory.saved'));
            this._tab = 'history';
            await this.refresh();
        } else {
            showToast((result && result.error) || I18n.t('wfHistory.saveFailed'));
        }
    },

    /* Restoring replaces the canvas, so the confirmation says what that replacement
       costs before it happens. The comparison is between the snapshot (the target) and
       the file-shaped current canvas, the same two serializations the save used. */
    _diffWorkflow(target, current) {
        var targetNodes = Array.isArray(target && target.nodes) ? target.nodes : [];
        var currentNodes = Array.isArray(current && current.nodes) ? current.nodes : [];
        var byTarget = {};
        var byCurrent = {};
        targetNodes.forEach(function (n) {
            if (n && n.id !== undefined && n.id !== null) byTarget[String(n.id)] = n;
        });
        currentNodes.forEach(function (n) {
            if (n && n.id !== undefined && n.id !== null) byCurrent[String(n.id)] = n;
        });
        var willReturn = targetNodes.filter(function (n) {
            return n && n.id !== undefined && n.id !== null && !Object.prototype.hasOwnProperty.call(byCurrent, String(n.id));
        });
        var willLeave = currentNodes.filter(function (n) {
            return n && n.id !== undefined && n.id !== null && !Object.prototype.hasOwnProperty.call(byTarget, String(n.id));
        });
        var moved = 0;
        targetNodes.forEach(function (n) {
            if (!n || n.id === undefined || n.id === null) return;
            var other = byCurrent[String(n.id)];
            if (!other) return;
            if (Math.round(Number(n.x) || 0) !== Math.round(Number(other.x) || 0) ||
                Math.round(Number(n.y) || 0) !== Math.round(Number(other.y) || 0)) moved += 1;
        });
        var edgeKey = function (c) { return String(c.from) + '\u0000' + String(c.to); };
        var targetEdges = {};
        var currentEdges = {};
        (Array.isArray(target && target.connections) ? target.connections : []).forEach(function (c) {
            if (c) targetEdges[edgeKey(c)] = true;
        });
        (Array.isArray(current && current.connections) ? current.connections : []).forEach(function (c) {
            if (c) currentEdges[edgeKey(c)] = true;
        });
        var addedLinks = Object.keys(targetEdges).filter(function (key) { return !currentEdges[key]; }).length;
        var removedLinks = Object.keys(currentEdges).filter(function (key) { return !targetEdges[key]; }).length;
        return {
            willReturn: willReturn,
            willLeave: willLeave,
            addedNodes: willReturn.length,
            removedNodes: willLeave.length,
            addedLinks: addedLinks,
            removedLinks: removedLinks,
            moved: moved,
            changed: willReturn.length > 0 || willLeave.length > 0 || addedLinks > 0 || removedLinks > 0 || moved > 0,
        };
    },

    _nodeNames(nodes) {
        var names = nodes.slice(0, 6).map(function (n) {
            var title = String((n && n.title) || '').trim();
            if (title) return title;
            var type = String((n && n.type) || '');
            if (type && typeof nodeTypeWord === 'function') return nodeTypeWord(type) || type;
            return type || String((n && n.id) || '');
        });
        var text = names.join(', ');
        if (nodes.length > names.length) text += I18n.t('wfHistory.diffMore', { n: nodes.length - names.length });
        return text;
    },

    _diffMessage(diff) {
        if (!diff.changed) return I18n.t('wfHistory.diffSame');
        var lines = [I18n.t('wfHistory.diffCounts', {
            nodesAdded: diff.addedNodes,
            nodesRemoved: diff.removedNodes,
            linksAdded: diff.addedLinks,
            linksRemoved: diff.removedLinks,
            moved: diff.moved,
        })];
        if (diff.willReturn.length) {
            lines.push(I18n.t('wfHistory.diffWillReturn', { names: this._nodeNames(diff.willReturn) }));
        }
        if (diff.willLeave.length) {
            lines.push(I18n.t('wfHistory.diffWillLeave', { names: this._nodeNames(diff.willLeave) }));
        }
        return lines.join('\n');
    },

    async restoreSnapshot(id) {
        if (refuseWhileRunning()) return;
        var row = this._snapshotRow(id);
        var label = this._snapshotLabel(row);
        var result = await fetchJSON('/api/workflow/history/get?id=' + encodeURIComponent(id));
        if (!result || !result.ok || !result.snapshot) {
            showToast((result && result.error) || I18n.t('wfHistory.restoreFailed'));
            return;
        }
        var target = result.snapshot.workflow || {};
        var current = (typeof canvas !== 'undefined' && canvas && canvas.toWorkflowJSON)
            ? canvas.toWorkflowJSON({ expandReusable: false })
            : { nodes: [], connections: [] };
        var message = I18n.t('wfHistory.restoreConfirm', { label: label }) +
            '\n\n' + this._diffMessage(this._diffWorkflow(target, current));
        var ok = await showDialog({
            message: message,
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('wfHistory.restore'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        /* One undo step: a snapshot restore is one user action, not one step per node. */
        if (!workflow.loadFromJSON(target, { history: 'single' })) return;
        if (typeof LayoutStrategy !== 'undefined') LayoutStrategy.reset();
        showToast(I18n.t('wfHistory.restored'));
    },

    async setBaseline(id) {
        if (typeof LayoutStrategy === 'undefined') return;
        await LayoutStrategy.setBaseline(id);
        if (this._tab === 'history') this.renderHistory();
    },

    async deleteSnapshot(id) {
        var row = this._snapshotRow(id);
        var ok = await showDialog({
            message: I18n.t('wfHistory.confirmRemove').replace('{label}', this._snapshotLabel(row)),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('wfHistory.remove'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/workflow/history/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ id: id }),
        });
        if (!result || !result.ok) {
            showToast((result && result.error) || I18n.t('wfHistory.removeFailed'));
            return;
        }
        var message = I18n.t('wfHistory.removed');
        var cleared = (result.baselines_cleared || []).length;
        if (cleared) message += I18n.t('wfHistory.baselineClearedByDelete').replace('{n}', cleared);
        showToast(message);
        if (typeof LayoutStrategy !== 'undefined') LayoutStrategy.reset();
        await this.refreshHistory();
    },

    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        this.renderTabs();
        if (this._tab === 'history') {
            if (this._history) this.renderHistory();
            else this.refresh();
            return;
        }
        if (this._tab === 'reusable') {
            if (this._templates) this.renderReusable();
            else this.refresh();
            return;
        }
        if (this._last) this.render();
        else this.refresh();
    },

    _when(seconds) {
        var value = Number(seconds) || 0;
        if (!value) return '';
        var d = new Date(value * 1000);
        function pad(n) { return (n < 10 ? '0' : '') + n; }
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
            ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    },

    _quote(value) {
        return attrJsArg(value);
    },

    render() {
        var body = document.getElementById('workflows-mgr-body');
        if (!body) return;
        var rows = this._last || [];
        if (!rows.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfMgr.empty') + '</div>';
            return;
        }
        var self = this;
        var current = (typeof workflow !== 'undefined' && workflow.currentFile) || '';
        var html = rows.map(function (row) {
            var name = String(row.name || '');
            var ops = '';
            if (!row.broken) {
                ops += '<button class="runs-mgr-btn" onclick="wfFiles.open(\'' + self._quote(name) + '\')">' +
                    I18n.t('wfMgr.open') + '</button>';
            }
            ops += '<button class="runs-mgr-btn" onclick="wfFiles.rename(\'' + self._quote(name) + '\')">' +
                I18n.t('wfMgr.rename') + '</button>';
            ops += '<button class="runs-mgr-btn del" onclick="wfFiles.remove(\'' + self._quote(name) + '\')">' +
                I18n.t('wfMgr.remove') + '</button>';
            ops += lockButtonHtml('workflows', name);
            var chip = name === current ? ' <span class="runs-mgr-cur">' + escapeHtml(I18n.t('wfMgr.current')) + '</span>' : '';
            var broken = row.broken ? ' <span class="runs-mgr-cur">' + escapeHtml(I18n.t('wfMgr.broken')) + '</span>' : '';
            return '<tr>' +
                '<td class="runs-mgr-wf">' + escapeHtml(name) + chip + broken + '</td>' +
                '<td>' + (row.nodes || 0) + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(self._when(row.mtime)) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        body.innerHTML =
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('wfMgr.colName') + '</th>' +
            '<th>' + I18n.t('wfMgr.colNodes') + '</th>' +
            '<th>' + I18n.t('wfMgr.colModified') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>';
    },

    async open(name) {
        if (refuseWhileRunning()) return;
        /* Opening replaces the canvas (and its autosave draft) wholesale. Confirm only when
           there is genuinely UNSAVED work to lose — canvas.dirty — rather than on any non-empty
           canvas, so reopening a file you just saved does not nag. */
        if (typeof canvas !== 'undefined' && canvas.dirty) {
            var ok = await showDialog({
                message: I18n.t('wfMgr.confirmOpen').replace('{name}', name),
                buttons: [
                    { label: I18n.t('dialog.cancel'), value: false },
                    { label: I18n.t('wfMgr.open'), value: true, primary: true },
                ],
            });
            if (!ok) return;
        }
        await workflow._loadByName(name);
        this.refresh();
    },

    async rename(name) {
        if (refuseWhileRunning()) return;
        /* No `value:` on the primary button — showDialog answers a button carrying
           one with that value, ignoring the typed input (the dataset rename once
           stored the literal 'ok' this way). */
        var answer = await showDialog({
            message: I18n.t('wfMgr.renamePrompt').replace('{name}', name),
            input: { value: name, placeholder: I18n.t('wfMgr.renamePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('wfMgr.rename'), primary: true },
            ],
        });
        if (!answer || answer === name) return;
        var result = await fetchJSON('/api/workflow/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ name: name, new_name: answer }),
        });
        if (result && result.ok) {
            /* The canvas that was open under the old stem now IS the new file;
               leaving currentFile on the old name would make the next Save
               recreate the just-renamed-away file. */
            if (typeof workflow !== 'undefined' && workflow.currentFile === name) workflow.currentFile = result.name;
            if (typeof workflow !== 'undefined') workflow._persistOpenFile();
            if (typeof LayoutStrategy !== 'undefined') LayoutStrategy.reset();
            showToast(I18n.t('wfMgr.renameDone'));
            this.refresh();
        } else {
            showToast((result && result.error) || I18n.t('wfMgr.renameFailed'));
        }
    },

    async remove(name) {
        if (refuseWhileRunning()) return;
        var ok = await showDialog({
            message: I18n.t('wfMgr.confirmRemove').replace('{name}', name),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('wfMgr.remove'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/workflow/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ name: name }),
        });
        /* A locked workflow is refused with HTTP 409 whose body already carries the
           friendly 「这一项已被锁定…」 reason; surfacing result.error (as rename does)
           tells the user WHY it failed, instead of a bare generic 删除失败 toast. */
        showToast(result && result.ok ? I18n.t('wfMgr.removeDone') : ((result && result.error) || I18n.t('wfMgr.removeFailed')));
        if (typeof LayoutStrategy !== 'undefined') LayoutStrategy.reset();
        if (typeof resumeBar !== 'undefined' && resumeBar.refresh) resumeBar.refresh();
        this.refresh();
    },
};

