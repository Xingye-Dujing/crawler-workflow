/* The export artefacts panel: the read side of data/exports.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-28) byte for byte. Rows arrive with a name the
 * server already resolved once, so the download link and the delete button both send that name back
 * unchanged — the browser never assembles a path, and a hand-edited ``../../etc/passwd`` is answered
 * with a 404 like any other missing file.
 */

/* ─── Export artefacts panel ────────────────────────────────────
   The read side of data/exports. Rows arrive with a name the server already
   resolved once, so the download link and the delete button both send that
   name back unchanged — the browser never assembles a path, and a hand-edited
   `../../etc/passwd` is answered with a 404 like any other missing file. */
function toggleExportsPanel() {
    exportsManager.toggle();
}

var exportsManager = {
    panel() {
        return document.getElementById('exports-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('exports-panel');
        panel.classList.add('open');
        this.refresh();
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        /* The resize handle leaves an inline height behind, and an inline
           height overrides the CSS `height: 0`. */
        panel.style.height = '';
    },

    async refresh() {
        var body = document.getElementById('exports-mgr-body');
        if (!body) return;
        try {
            var resp = await fetch('/api/exports/list?limit=200');
            var result = await resp.json();
            if (!result.ok) throw new Error('list failed');
            this._last = result.exports || [];
            this._totals = { files: result.files || 0, bytes: result.bytes || 0 };
            this.render();
        } catch (e) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('exportsMgr.loadFailed') + '</div>';
        }
    },

    /* Language switch: the table text is JS-built, so an open panel must be
       redrawn from the cached rows rather than refetched. */
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
        var body = document.getElementById('exports-mgr-body');
        if (!body) return;
        var rows = this._last || [];
        if (!rows.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('exportsMgr.empty') + '</div>';
            return;
        }
        var self = this;
        var html = rows.map(function (row) {
            var name = escapeHtml(row.name);
            var ops = '';
            if (row.downloadable) {
                ops += '<button class="runs-mgr-btn" onclick="exportsManager.download(\'' + self._quote(row.name) + '\')">' + I18n.t('exportsMgr.download') + '</button>';
            }
            if (row.kind === 'report') {
                /* No download button on purpose — .html is refused there. A
                   report opens through its own route, script-free. */
                ops += '<button class="runs-mgr-btn" onclick="exportsManager.view(\'' + self._quote(row.name) + '\')">' + I18n.t('exportsMgr.view') + '</button>';
            }
            ops += '<button class="runs-mgr-btn del" onclick="exportsManager.remove(\'' + self._quote(row.name) + '\')">' + I18n.t('exportsMgr.remove') + '</button>';
            if (/\.part\d+\./.test(row.name)) {
                /* A batched crawl leaves ``{stem}.part{NNN}{ext}`` shards. 删除 clears ONE file;
                   this clears the WHOLE batch the clicked shard belongs to — the server keeps the
                   merged ``{stem}.csv``, other stems/extensions and 「固定」pinned files. */
                ops += '<button class="runs-mgr-btn del" onclick="exportsManager.clearPartsByName(\'' + self._quote(row.name) + '\')">' + I18n.t('exportsMgr.clearParts') + '</button>';
            }
            ops += lockButtonHtml('exports', row.name);
            return '<tr>' +
                '<td class="runs-mgr-wf">' + name + '</td>' +
                '<td>' + escapeHtml(row.kind || '') + '</td>' +
                '<td>' + self.size(row.size) + '</td>' +
                '<td class="runs-mgr-time">' + self._when(row.mtime) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        var totals = this._totals || {};
        body.innerHTML =
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('exportsMgr.colName') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colKind') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colSize') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colModified') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>' +
            /* Read as a summary of the list above it, so it goes after the table — the
               totals cover the whole export directory, not the rows on screen, and a
               heading invites reading them as one file's figures. */
            '<div class="exports-summary">' +
            I18n.t('exportsMgr.summary').replace('{files}', totals.files || 0).replace('{size}', this.size(totals.bytes || 0)) +
            '</div>';
    },

    _when(epoch) {
        var stamp = Number(epoch) || 0;
        if (!stamp) return '';
        var d = new Date(stamp * 1000);
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
            ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    },

    /* Filenames carry quotes and backslashes; an inline onclick is built by
       string concatenation, so the value has to survive both the JS literal and
       the HTML attribute — see attrJsArg, which is the one place that knows how. */
    _quote(name) {
        return attrJsArg(name);
    },

    download(name) {
        var frame = document.createElement('iframe');
        frame.style.display = 'none';
        frame.src = '/api/exports/download?name=' + encodeURIComponent(name);
        document.body.appendChild(frame);
        setTimeout(function () { document.body.removeChild(frame); }, 60000);
    },

    view(name) {
        /* The report is text crawled from other people's pages, so it is served
           by a route that sends a Content-Security-Policy with no script in it —
           which is also why this is not the download button. */
        window.open('/api/report/view?name=' + encodeURIComponent(name), '_blank');
    },

    /* One click, one HTML file — with the sections, row cap and Chart-Studio
       pictures chosen on the way. With a run id the tables are read back out of
       the run store, so yesterday's run can be reported on from the 运行记录
       panel; without one the run this page is holding is used, and the canvas
       lends the node titles (the store is not the only thing worth a report). */
    async report(runId, suggestedTitle) {
        var TOG = { charts: 'rpt-sec-charts', tables: 'rpt-sec-tables', facts: 'rpt-sec-facts' };
        var ROWS_FIELD = 'rpt-rows';
        /* The studio's saved pictures already live in the export folder; offer
           each as a toggle so a report can carry a hand-tuned chart the
           auto-drawn ones cannot reproduce. A folder with none still reports —
           the picker is simply empty, never an error. */
        var studioImages = [];
        try {
            var listResp = await fetch('/api/report/studio-images', { headers: { 'X-Lang': I18n.lang || 'zh' } });
            var list = await listResp.json();
            if (list && list.ok) studioImages = list.images || [];
        } catch (e) {
            studioImages = [];
        }
        var toggles = [
            { id: TOG.charts, label: I18n.t('exportsMgr.reportTCharts'), checked: true },
            { id: TOG.tables, label: I18n.t('exportsMgr.reportTTables'), checked: true },
            { id: TOG.facts, label: I18n.t('exportsMgr.reportTFacts'), checked: true },
        ];
        studioImages.forEach(function (img, i) {
            toggles.push({ id: 'rpt-img-' + i, label: img.name, checked: true });
        });
        var answer = await showDialog({
            input: { value: suggestedTitle || '', placeholder: I18n.t('exportsMgr.reportPlaceholder') },
            toggles: toggles,
            fields: [{ id: ROWS_FIELD, label: I18n.t('exportsMgr.reportRows'), type: 'number', value: '20', min: '1', max: '200' }],
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.reportAi'), value: 'ai', collect: true },
                { label: I18n.t('exportsMgr.reportGo'), value: 'go', collect: true, primary: true },
                { label: I18n.t('exportsMgr.reportLatex'), value: 'latex', collect: true },
            ],
        });
        if (!answer || !answer.value) return;
        if (answer.value === 'latex') {
            await this.latexPaper(runId, String(answer.input || '').trim());
            return;
        }
        var t = answer.toggles || {};
        // A switch the answer does not name is left at its default rather than
        // read as "off": an older or partial dialog must still yield a full
        // report, not a document that quietly lost its tables.
        function tog(id, def) {
            return t[id] === undefined ? def : !!t[id];
        }
        var options = {
            show_charts: tog(TOG.charts, true),
            show_tables: tog(TOG.tables, true),
            show_facts: tog(TOG.facts, true),
        };
        var rows = parseInt(answer.fields && answer.fields[ROWS_FIELD], 10);
        if (!isNaN(rows)) options.max_rows = rows;
        if (studioImages.length) {
            options.images = studioImages
                .filter(function (img, i) { return tog('rpt-img-' + i, true); })
                .map(function (img) { return img.name; });
        }
        var payload = {
            title: String(answer.input || '').trim(),
            include_conclusion: answer.value === 'ai',
            lang: I18n.lang || 'zh',
            llm: LLMSettings.payload(),
            options: options,
        };
        if (runId) {
            payload.run_id = runId;
        } else {
            payload.nodes = Object.keys(canvas.nodes || {}).map(function (id) {
                var node = canvas.nodes[id];
                return { id: id, title: node.title || id };
            });
        }
        try {
            var resp = await fetch('/api/report/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify(payload),
            });
            var result = await resp.json();
            if (!result.ok) throw new Error(result.error || 'report failed');
            showToast(I18n.t('exportsMgr.reportDone'));
            this.view(result.name);
            this.refresh();
        } catch (e) {
            showToast(I18n.t('exportsMgr.reportFailed') + ': ' + (e.message || e));
        }
    },

    /* The paper document: the run's OWN filed figures and three-line tables, assembled into one
       article+ctex source and compiled here. The request carries a run id and a title — never LaTeX —
       because the compiler is the user's xelatex and it must only ever read what this app filed.
       It is slow (one or two xelatex passes), so the toast stays up long enough to be seen, and a
       refusal is shown with the server's reason rather than a shrug. */
    async latexPaper(runId, title) {
        if (!runId) {
            showToast(I18n.t('exportsMgr.reportLatexNoRun'));
            return;
        }
        showToast(I18n.t('exportsMgr.reportLatexWorking'), 20000);
        try {
            var resp = await fetch('/api/report/latex', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify({ run_id: runId, title: title || '' }),
            });
            var result = await resp.json();
            if (!result.ok) throw new Error(result.error || 'report failed');
            showToast(I18n.t('exportsMgr.reportLatexDone') + ': ' + result.name, 20000);
            this.refresh();
            window.open('/api/exports/download?name=' + encodeURIComponent(result.name), '_blank');
        } catch (e) {
            showToast(I18n.t('exportsMgr.reportLatexFailed') + ': ' + (e.message || e), 20000);
        }
    },

    async remove(name) {
        var go = await showDialog({
            message: I18n.t('exportsMgr.confirmRemove'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.remove'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        try {
            var resp = await fetch('/api/exports/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify({ name: name }),
            });
            var result = await resp.json();
            showToast(result.ok ? I18n.t('exportsMgr.removeDone') : ((result && result.error) || I18n.t('exportsMgr.removeFailed')));
        } catch (e) {
            showToast(I18n.t('exportsMgr.removeFailed'));
        }
        this.refresh();
    },

    /* 依据名字「清除该批分片」 — the clicked shard's whole batch in one go. Destructive, so it
       asks first and names what survives (the merged file + 固定); the server does the batch
       lookup by name and deletes each through the same per-name resolver as 删除, refuses without
       confirm and while a run is writing here. */
    async clearPartsByName(name) {
        var go = await showDialog({
            message: I18n.t('exportsMgr.confirmClearName').replace('{name}', name),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.clearGo'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        var r = await this._postClear('/api/exports/clear-name', { name: name, confirm: true });
        if (r && r.ok) {
            showToast(I18n.t('exportsMgr.clearNameDone').replace('{removed}', r.removed || 0).replace('{skipped}', r.skipped_locked || 0));
        } else {
            showToast(I18n.t('exportsMgr.clearFailed') + ((r && r.error) ? ': ' + r.error : ''));
        }
        this.refresh();
    },

    /* The server deletes these one name at a time through the same resolver the per-row
       button uses, so the rules that keep a name from reaching outside data/exports cannot
       drift into a second bulk implementation. It also refuses outright while a run is
       live — a streaming node is writing part files into this very directory — and that
       refusal is shown rather than swallowed. */
    async clearAll() {
        var go = await showDialog({
            message: I18n.t('exportsMgr.confirmClearAll'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.clearAll'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        try {
            var resp = await fetch('/api/exports/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify({ confirm: true }),
            });
            var result = await resp.json();
            if (result && result.ok) {
                showToast(I18n.t('exportsMgr.clearAllDone').replace('{n}', result.removed || 0));
            } else {
                showToast(I18n.t('exportsMgr.clearAllFailed') + ((result && result.error) ? ': ' + result.error : ''));
            }
        } catch (e) {
            showToast(I18n.t('exportsMgr.clearAllFailed'));
        }
        this.refresh();
    },

    /* 智能清除 — two scoped, LEDGER-driven bulk deletes. Unlike 清空 (the whole folder), these
       act on the files ONE run wrote, or ONE source node of ONE run left behind as shards — read
       back from the run→files ledger the server keeps, never guessed from a filename. Both keep
       「固定」(pinned) files and are refused while any run is live; the server runs them through
       the same per-name resolver as the single delete, so a ledger row can never become a path
       reaching outside data/exports. */
    async _ledger() {
        try {
            var resp = await fetch('/api/exports/ledger', { headers: { 'X-Lang': I18n.lang || 'zh' } });
            var result = await resp.json();
            if (result && result.ok) return result.ledger || [];
        } catch (e) {
            /* no-op */
        }
        return [];
    },

    _runLabel(entry) {
        var name = entry.workflow_name || I18n.t('exportsMgr.unnamedRun');
        return name + ' · ' + (entry.started_at || '') + ' · ' + (entry.files || []).length;
    },

    _nodeLabel(nid) {
        if (typeof canvas !== 'undefined' && canvas.nodes && canvas.nodes[nid] && canvas.nodes[nid].title) {
            return canvas.nodes[nid].title;
        }
        return nid;
    },

    async smartClearRun() {
        var ledger = await this._ledger();
        if (!ledger.length) {
            showToast(I18n.t('exportsMgr.noLedger'));
            return;
        }
        var answer = await showDialog({
            message: I18n.t('exportsMgr.pickRun'),
            fields: [{ id: 'scr-run', label: I18n.t('exportsMgr.runField'), type: 'select',
                options: ledger.map((r) => ({ value: r.run_id, label: this._runLabel(r) })) }],
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.next'), value: 'go', collect: true, primary: true },
            ],
        });
        if (!answer || !answer.value) return;
        var runId = answer.fields && answer.fields['scr-run'];
        var entry = ledger.filter((r) => r.run_id === runId)[0];
        if (!entry) return;
        var go = await showDialog({
            message: I18n.t('exportsMgr.confirmClearRun').replace('{n}', (entry.files || []).length),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.clearGo'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        var r = await this._postClear('/api/exports/clear-run', { run_id: runId, confirm: true });
        if (r && r.ok) {
            showToast(I18n.t('exportsMgr.clearRunDone').replace('{removed}', r.removed || 0).replace('{skipped}', r.skipped_locked || 0));
        } else {
            showToast(I18n.t('exportsMgr.clearFailed') + ((r && r.error) ? ': ' + r.error : ''));
        }
        this.refresh();
    },

    async smartClearParts() {
        var ledger = await this._ledger();
        if (!ledger.length) {
            showToast(I18n.t('exportsMgr.noLedger'));
            return;
        }
        var answer = await showDialog({
            message: I18n.t('exportsMgr.pickRun'),
            fields: [{ id: 'scp-run', label: I18n.t('exportsMgr.runField'), type: 'select',
                options: ledger.map((r) => ({ value: r.run_id, label: this._runLabel(r) })) }],
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.next'), value: 'go', collect: true, primary: true },
            ],
        });
        if (!answer || !answer.value) return;
        var runId = answer.fields && answer.fields['scp-run'];
        var entry = ledger.filter((r) => r.run_id === runId)[0];
        if (!entry) return;
        // Only nodes that actually LEFT shards (kind 'part') are offered: with 「保留分片」 off the
        // merge already deleted them, so a run with none says so out loud rather than showing a dead
        // list or silently deleting nothing.
        var partNodes = {};
        (entry.files || []).forEach(function (f) {
            if (f.kind === 'part' && f.node_id) partNodes[f.node_id] = (partNodes[f.node_id] || 0) + 1;
        });
        var nodeIds = Object.keys(partNodes);
        if (!nodeIds.length) {
            showToast(I18n.t('exportsMgr.noParts'));
            return;
        }
        var nodeAnswer = await showDialog({
            message: I18n.t('exportsMgr.pickNode'),
            fields: [{ id: 'scp-node', label: I18n.t('exportsMgr.nodeField'), type: 'select',
                options: nodeIds.map((nid) => ({ value: nid, label: this._nodeLabel(nid) + ' · ' + partNodes[nid] })) }],
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.clearGo'), value: 'go', collect: true, primary: true },
            ],
        });
        if (!nodeAnswer || !nodeAnswer.value) return;
        var nodeId = nodeAnswer.fields && nodeAnswer.fields['scp-node'];
        if (!nodeId) return;
        var r = await this._postClear('/api/exports/clear-run-parts', { run_id: runId, node_id: nodeId, confirm: true });
        if (r && r.ok) {
            showToast(I18n.t('exportsMgr.clearPartsDone').replace('{removed}', r.removed || 0).replace('{skipped}', r.skipped_locked || 0));
        } else {
            showToast(I18n.t('exportsMgr.clearFailed') + ((r && r.error) ? ': ' + r.error : ''));
        }
        this.refresh();
    },

    /* POST the bulk delete and hand back the parsed body (or null on a thrown request). The toast
       is built by the CALLER, substituting the {removed}/{skipped} slots against the literal
       `I18n.t('exportsMgr.clear…Done')` on the same line — a missing-argument check (test_i18n)
       pairs a slot fill with that literal call, so it must not be hidden inside a shared helper. */
    async _postClear(url, payload) {
        try {
            var resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify(payload),
            });
            return await resp.json();
        } catch (e) {
            return null;
        }
    },
};

