/* The dataset manager: every uploaded or pasted table that outlives a run.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-29) byte for byte. A re-upload of the same table is
 * one copy (identity is content), so this panel answers "what is stored, what shape is it, and which
 * saved workflow still points at it" — and refuses the delete the backend would refuse.
 */

/* ─── Dataset manager ───────────────────────────────────────────
   Uploaded/pasted files outlive a run, and until now the only way to see them
   was the Upload node's own picker. A user who re-uploads the same table twice
   gets one copy (identity is content), so the practical questions are "what is
   stored, which workflow reads it, what is it called, and may I delete it".
   The delete button refuses a file a saved workflow still points at: dropping it
   would turn that workflow into an empty Upload node on its next open, and the
   user would only find out when a run returned 0 rows. */
var datasetManager = {
    panel() {
        return document.getElementById('dataset-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('dataset-panel');
        panel.classList.add('open');
        this.refresh();
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        panel.style.height = '';
    },

    async refresh() {
        var body = document.getElementById('dataset-mgr-body');
        if (!body) return;
        body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('datasetMgr.loading') + '</div>';
        var result = await fetchJSON('/api/data/datasets?limit=200').catch(function () { return null; });
        if (!result || !result.ok) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('datasetMgr.loadFailed') + '</div>';
            return;
        }
        this._last = result.datasets || [];
        this.render();
    },

    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        if (this._last) this.render();
        else this.refresh();
    },

    size(bytes) {
        var value = Number(bytes) || 0;
        if (value < 1024) return value + ' B';
        if (value < 1024 * 1024) return (value / 1024).toFixed(1) + ' KB';
        return (value / (1024 * 1024)).toFixed(1) + ' MB';
    },

    render() {
        var body = document.getElementById('dataset-mgr-body');
        if (!body) return;
        this._compare = this._compare || [];
        this._merge = this._merge || [];
        var rows = this._last || [];
        // A deleted or re-hashed file can no longer be a compare/merge source; drop stale picks.
        var alive = {};
        rows.forEach(function (r) { alive[String(r.dataset_id || '')] = true; });
        this._compare = this._compare.filter(function (id) { return alive[id]; });
        this._merge = this._merge.filter(function (id) { return alive[id]; });
        if (!rows.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('datasetMgr.empty') + '</div>';
            return;
        }
        var self = this;
        var html = rows.map(function (row) {
            var id = String(row.dataset_id || '');
            /* A file a saved workflow reads is not the user's to delete quietly —
               the reference list is shown and the button refuses server-side too. */
            var refs = row.workflows || [];
            var picked = self._compare.indexOf(id) >= 0;
            var mergePicked = self._merge.indexOf(id) >= 0;
            var lineage = row.lineage && row.lineage.name
                ? '<span class="wf-snap-baseline">' + escapeHtml(I18n.t('datasetMgr.lineageVersion', {
                    version: row.lineage.version,
                })) + '</span>'
                : '';
            var ops = '';
            if (row.lineage && row.lineage.name) {
                ops += '<button class="runs-mgr-btn" onclick="datasetManager.resetLineage(\'' +
                    self._quote(row.lineage.name) + '\')">' + I18n.t('datasetMgr.lineageReset') + '</button>';
            }
            ops += '<button class="runs-mgr-btn" onclick="datasetManager.toggleCompare(\'' + self._quote(id) +
                '\')">' + I18n.t(picked ? 'datasetMgr.compareOn' : 'datasetMgr.compare') + '</button>';
            ops += '<button class="runs-mgr-btn" onclick="datasetManager.toggleMerge(\'' + self._quote(id) +
                '\')">' + I18n.t(mergePicked ? 'datasetMgr.mergeOn' : 'datasetMgr.merge') + '</button>';
            ops += '<button class="runs-mgr-btn" onclick="datasetManager.rename(\'' + self._quote(id) + '\', \'' +
                self._quote(row.name || '') + '\')">' + I18n.t('datasetMgr.rename') + '</button>';
            ops += '<button class="runs-mgr-btn del" onclick="datasetManager.remove(\'' + self._quote(id) +
                '\', \'' + self._quote(row.name || '') + '\', ' + (refs.length ? 'true' : 'false') + ')">' +
                I18n.t('datasetMgr.remove') + '</button>';
            return '<tr>' +
                '<td class="runs-mgr-wf">' + escapeHtml(row.name || I18n.t('name.unnamed')) + lineage + '</td>' +
                '<td>' + escapeHtml(self._sourceLabel(row.source)) + '</td>' +
                '<td>' + (row.row_count || 0) + '</td>' +
                '<td>' + self.size(row.byte_size) + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(id.slice(0, 12)) + '</td>' +
                '<td>' + escapeHtml(refs.join(', ')) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        var bar = '<div class="dataset-compare-bar">' +
            '<button class="runs-mgr-btn" onclick="datasetManager.compareSelected()">' +
            I18n.t('datasetMgr.compareRun') + ' (' + this._compare.length + '/2)</button>' +
            (this._compare.length ? '<button class="runs-mgr-btn" onclick="datasetManager.clearCompare()">' +
                I18n.t('datasetMgr.compareClear') + '</button>' : '') +
            '<button class="runs-mgr-btn" onclick="datasetManager.mergeSelected()">' +
            I18n.t('datasetMgr.mergeSelected') + ' (' + this._merge.length + ')</button>' +
            (this._merge.length ? '<button class="runs-mgr-btn" onclick="datasetManager.clearMerge()">' +
                I18n.t('datasetMgr.mergeClear') + '</button>' : '') +
            '</div>';
        body.innerHTML = bar +
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('datasetMgr.colName') + '</th>' +
            '<th>' + I18n.t('datasetMgr.colSource') + '</th>' +
            '<th>' + I18n.t('datasetMgr.colRows') + '</th>' +
            '<th>' + I18n.t('datasetMgr.colSize') + '</th>' +
            '<th>id</th>' +
            '<th>' + I18n.t('datasetMgr.colUsedBy') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>';
    },

    toggleCompare(id) {
        var i = this._compare.indexOf(id);
        if (i >= 0) this._compare.splice(i, 1);
        else if (this._compare.length < 2) this._compare.push(id);
        else {
            showToast(I18n.t('datasetMgr.compareMaxTwo'));
            return;
        }
        this.render();
    },

    clearCompare() {
        this._compare = [];
        this.render();
    },

    async compareSelected() {
        if (!this._compare || this._compare.length !== 2) {
            showToast(I18n.t('datasetMgr.compareNeedTwo'));
            return;
        }
        var a = this._compare[0];
        var b = this._compare[1];
        var result = await fetchJSON('/api/data/diff', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ a: { dataset_id: a }, b: { dataset_id: b } }),
        }).catch(function () { return null; });
        if (!result || !result.ok) {
            showToast(I18n.t('datasetMgr.diffFailed'));
            return;
        }
        var d = result.diff || {};
        var lines = [];
        lines.push(I18n.t('datasetMgr.diffAdded') + ': ' + (d.added_count || 0));
        lines.push(I18n.t('datasetMgr.diffRemoved') + ': ' + (d.removed_count || 0));
        lines.push(I18n.t('datasetMgr.diffRows') + ': ' + (d.row_count_a || 0) + ' → ' + (d.row_count_b || 0));
        if ((d.columns_added || []).length) lines.push(I18n.t('datasetMgr.diffColAdded') + ': ' + d.columns_added.join(', '));
        if ((d.columns_removed || []).length) lines.push(I18n.t('datasetMgr.diffColRemoved') + ': ' + d.columns_removed.join(', '));
        await showDialog({
            message: lines.join('\n'),
            buttons: [{ label: I18n.t('dialog.confirm'), value: null, primary: true }],
        });
    },

    toggleMerge(id) {
        var i = this._merge.indexOf(id);
        if (i >= 0) this._merge.splice(i, 1);
        else if (this._merge.length < 20) this._merge.push(id);
        else {
            showToast(I18n.t('datasetMgr.mergeMax'));
            return;
        }
        this.render();
    },

    clearMerge() {
        this._merge = [];
        this.render();
    },

    async resetLineage(name) {
        var clean = String(name || '').trim();
        if (!clean) return;
        var ok = await showDialog({
            message: I18n.t('datasetMgr.lineageResetConfirm', { name: clean }),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('datasetMgr.lineageReset'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/data/lineages/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ name: clean }),
        }).catch(function () { return null; });
        if (!result || !result.ok) {
            showToast((result && result.error) || I18n.t('datasetMgr.lineageResetFailed'));
            return;
        }
        showToast(I18n.t('datasetMgr.lineageResetDone', { name: clean }));
        await this.refresh();
    },

    async mergeSelected() {
        if (!this._merge || this._merge.length < 2) {
            showToast(I18n.t('datasetMgr.mergeNeedTwo'));
            return;
        }
        var answer = await showDialog({
            message: I18n.t('datasetMgr.mergePrompt'),
            input: { value: I18n.t('datasetMgr.mergeDefaultName'), placeholder: I18n.t('datasetMgr.mergePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('datasetMgr.merge'), primary: true },
            ],
        });
        if (answer === null) return;
        var name = String(answer || '').trim();
        if (!name) {
            showToast(I18n.t('datasetMgr.mergeNameRequired'));
            return;
        }
        var result = await fetchJSON('/api/data/merge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ dataset_ids: this._merge.slice(), name: name }),
        }).catch(function () { return null; });
        if (!result || !result.ok) {
            showToast((result && result.error) || I18n.t('datasetMgr.mergeFailed'));
            return;
        }
        showToast(
            I18n.t('datasetMgr.mergeDone', {
                n: result.rows || 0,
                name: (result.dataset && result.dataset.name) || name,
            })
        );
        this._merge = [];
        await this.refresh();
    },

    _sourceLabel(source) {
        /* The stored value is a code, not display text. Map each known code to its label;
           an unknown code shows as itself rather than a fabricated translation. */
        var keys = {
            upload: 'datasetMgr.sourceUpload',
            paste: 'datasetMgr.sourcePaste',
            analysis: 'datasetMgr.sourceAnalysis',
            import: 'datasetMgr.sourceImport',
            merge: 'datasetMgr.sourceMerge',
            cumulative: 'datasetMgr.sourceCumulative',
        };
        var key = keys[source];
        return key ? I18n.t(key) : (source || '');
    },

    _quote(value) {
        return attrJsArg(value);
    },

    async rename(id, current) {
        /* No `value:` on the confirm button: showDialog answers a button with its own
           value when it has one, and only falls back to the input otherwise — so
           naming it 'ok' stored the literal string as the dataset's new label. The
           user read 「已重命名」 and saw the row say `ok`; the id is a content hash, so
           the file survived, the name did not. */
        var answer = await showDialog({
            message: I18n.t('datasetMgr.renamePrompt'),
            input: { value: current, placeholder: I18n.t('datasetMgr.renamePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('datasetMgr.rename'), primary: true },
            ],
        });
        if (!answer) return;
        var result = await fetchJSON('/api/data/datasets/' + encodeURIComponent(id) + '/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ name: answer }),
        });
        if (result && result.ok) {
            showToast(I18n.t('datasetMgr.renameDone'));
            this.refresh();
        } else {
            showToast((result && result.error) || I18n.t('datasetMgr.renameFailed'));
        }
    },

    async remove(id, name, referenced) {
        if (referenced) {
            /* Same answer as the server's: a workflow would keep pointing at a
               file that is gone. */
            showToast(I18n.t('datasetMgr.stillUsed'));
            return;
        }
        var ok = await showDialog({
            message: I18n.t('datasetMgr.confirmRemove').replace('{name}', name || id),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('datasetMgr.remove'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/data/datasets/' + encodeURIComponent(id), { method: 'DELETE' });
        showToast(result && result.ok ? I18n.t('datasetMgr.removeDone') : ((result && result.error) || I18n.t('datasetMgr.removeFailed')));
        this.refresh();
    },

    /* The per-row button refuses a file a saved workflow points at; a wipe has no such
       guard, because "start from nothing" is exactly the case where the user wants those
       gone too. That difference is the whole content of this dialog: an Upload node whose
       file is deleted here does not break loudly, it just reads as an empty table later. */
    async clearAll() {
        var ok = await showDialog({
            message: I18n.t('datasetMgr.confirmClearAll'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('datasetMgr.clearAll'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/data/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ all: true, confirm: true }),
        });
        if (result && result.ok) {
            showToast(I18n.t('datasetMgr.clearAllDone').replace('{n}', result.removed || 0));
        } else {
            showToast(I18n.t('datasetMgr.clearAllFailed') + ((result && result.error) ? ': ' + result.error : ''));
        }
        this.refresh();
    },
};

