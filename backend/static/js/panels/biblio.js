/* The bibliometrics workspace: one dock panel for every recorded run of a biblio node.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-28) byte for byte. It reads a run's node table over
 * ``/api/biblio/table`` (paged), lists that run's artefacts, locates the node on the canvas, and
 * captures/compares snapshots of the same project. Nothing here computes: the server decides shape,
 * page and diff, and the panel paints what it was told.
 */

/* ─── Bibliometrics workspace ─────────────────────────────────────────────
   Reads a finished run's bibliometrics node: which runs hold one, what its stored
   table looks like, and which files it wrote. Every fact on this panel is the
   server's — the browser does not decide what counts as a bibliometric run, what
   shape a stored table has, or how many rows it holds. A run record survives a
   restart and a rewired canvas, which is the whole point of reading the ledger
   instead of the live canvas state. */
function toggleBiblioPanel() {
    biblioWorkspace.toggle();
}

/* The header word for a stored column name. Computed key, so a column this build has no word
   for keeps the name it has on disk — the table is a view of durable rows, and inventing a
   heading (or printing 「biblio.col.节点」) would describe a column that does not exist. */
function biblioColumnWord(column) {
    var name = String(column === null || column === undefined ? '' : column);
    var key = 'biblio.col.' + name;
    var word = I18n.t(key);
    return word === key ? name : word;
}

var biblioWorkspace = {
    LIMIT: 200,
    _runs: [],
    _runId: '',
    _nodeId: '',
    _table: null,
    _offset: 0,
    _term: '',
    _error: '',
    _projects: [],
    _projectId: '',
    _label: '',
    _baseline: '',
    _diff: null,

    panel() {
        return document.getElementById('biblio-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('biblio-panel');
        panel.classList.add('open');
        if (this._runs.length || this._error) this.render();
        else this.refresh();
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        /* The resize handle leaves an inline height behind, and an inline height
           beats the CSS `height: 0` — Close looks dead after a resize. */
        panel.style.height = '';
    },

    async refresh() {
        var answer = await fetchJSON('/api/biblio/runs');
        if (!answer || !answer.ok) {
            this._error = (answer && answer.error) || I18n.t('biblioWs.unreachable');
            this._runs = [];
            this.render();
            return;
        }
        this._error = '';
        this._runs = answer.runs || [];
        this._keepSelection();
        this.render();
        await this.refreshProjects();
        /* Awaited, not fired-and-forgotten: the panel's Refresh means "the table I am
           looking at is the one the server just answered with", and a caller that cannot
           await it has to guess at how many microtask turns the table needs to land. */
        if (this._runId && this._nodeId && !this._table) return this.load();
        return undefined;
    },

    /* A refresh must not throw away what the user was reading: after a rerun the same
       node is still there, and jumping to the newest run would silently repage them
       onto different numbers. */
    _keepSelection() {
        var run = this._run();
        if (!run) {
            this._runId = this._runs.length ? String(this._runs[0].run_id) : '';
            var firstRun = this._run();
            this._nodeId = firstRun && firstRun.nodes.length ? String(firstRun.nodes[0].node_id) : '';
            this._offset = 0;
            this._table = null;
            return;
        }
        if (!this._node()) {
            this._nodeId = run.nodes.length ? String(run.nodes[0].node_id) : '';
            this._offset = 0;
            this._table = null;
        }
    },

    _run() {
        var self = this;
        return this._runs.filter(function (r) {
            return String(r.run_id) === self._runId;
        })[0] || null;
    },

    _node() {
        var run = this._run();
        if (!run) return null;
        var self = this;
        return (run.nodes || []).filter(function (n) {
            return String(n.node_id) === self._nodeId;
        })[0] || null;
    },

    /* ── projects, captures and the diff ─────────────────────────────
       A run record says what happened; a capture says what the researcher decided to keep.
       The list, the labels of a diff and its totals all come back from the server — this
       panel only prints them. */
    async refreshProjects() {
        var answer = await fetchJSON('/api/biblio/projects');
        this._projects = answer && answer.ok ? answer.projects || [] : [];
        var kept = this._project();
        if (!kept) this._projectId = this._projects.length ? String(this._projects[0].project_id) : '';
        this.render();
    },

    pickProject(value) {
        this._projectId = String(value || '');
        this._baseline = '';
        this._diff = null;
        this.render();
    },

    labelChanged(value) {
        this._label = String(value || '');
    },

    async createProject() {
        /* The name is read HERE, off the live element, rather than threaded through
           `onclick="…('…')"`: that attribute spans two grammars, and a missing closing quote
           once turned the whole rest of the bar into text — which only a real browser showed,
           because the node stub never parses that deeply. */
        var field = document.getElementById('biblio-new-project');
        var name = String((field && field.value) || '').trim();
        if (!name) {
            showToast(I18n.t('biblioWs.project_needs_name'));
            return undefined;
        }
        var answer = await fetchJSON('/api/biblio/project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name }),
        });
        if (!answer || !answer.ok) {
            showToast((answer && answer.error) || I18n.t('biblioWs.unreachable'));
            return undefined;
        }
        this._projectId = String(answer.project.project_id);
        await this.refreshProjects();
        return undefined;
    },

    _project() {
        var self = this;
        return this._projects.filter(function (p) {
            return String(p.project_id) === self._projectId;
        })[0] || null;
    },

    /* Capture is refused HERE before it is sent, because the button has to say why it is
       dead: no run/node selected, or no project. A silently inert button reads as a broken
       panel, which is the complaint this dock exists to answer. */
    captureBlocker() {
        if (!this._runId || !this._nodeId) return I18n.t('biblioWs.captureNeedsNode');
        if (!this._projectId) return I18n.t('biblioWs.captureNeedsProject');
        return '';
    },

    async capture() {
        var blocker = this.captureBlocker();
        if (blocker) {
            showToast(blocker);
            return undefined;
        }
        var answer = await fetchJSON('/api/biblio/snapshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: this._projectId,
                run_id: this._runId,
                node_id: this._nodeId,
                label: this._label.trim(),
            }),
        });
        if (!answer || !answer.ok) {
            showToast((answer && answer.error) || I18n.t('biblioWs.unreachable'));
            return undefined;
        }
        showToast(I18n.t('biblioWs.captureDone', { label: answer.snapshot.label }));
        this._label = '';
        await this.refreshProjects();
        return undefined;
    },

    async removeSnapshot(id) {
        var answer = await fetchJSON('/api/biblio/snapshot/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ snapshot_id: id }),
        });
        if (!answer || !answer.ok) {
            showToast((answer && answer.error) || I18n.t('biblioWs.unreachable'));
        }
        if (this._baseline === String(id)) {
            this._baseline = '';
            this._diff = null;
        }
        await this.refreshProjects();
        return undefined;
    },

    setBaseline(id) {
        this._baseline = String(id || '');
        this._diff = null;
        this.render();
    },

    async compareWith(id) {
        if (!this._baseline) {
            showToast(I18n.t('biblioWs.needBaseline'));
            return undefined;
        }
        var answer = await fetchJSON(
            '/api/biblio/compare?a=' + encodeURIComponent(this._baseline) + '&b=' + encodeURIComponent(id)
        );
        if (!answer || !answer.ok) {
            this._diff = null;
            showToast((answer && answer.error) || I18n.t('biblioWs.unreachable'));
        } else {
            this._diff = answer.diff;
        }
        this.render();
        return undefined;
    },

    clearDiff() {
        this._diff = null;
        this.render();
    },

    pickRun(value) {
        var id = String(value || '');
        if (id === this._runId) return undefined;
        this._runId = id;
        var run = this._run();
        this._nodeId = run && run.nodes.length ? String(run.nodes[0].node_id) : '';
        return this._reset();
    },

    pickNode(value) {
        var id = String(value || '');
        if (id === this._nodeId) return undefined;
        this._nodeId = id;
        return this._reset();
    },

    _reset() {
        this._offset = 0;
        this._table = null;
        this.render();
        if (this._runId && this._nodeId) return this.load();
        return undefined;
    },

    async load() {
        if (!this._runId || !this._nodeId) return;
        var url = '/api/biblio/table?run_id=' + encodeURIComponent(this._runId) +
            '&node_id=' + encodeURIComponent(this._nodeId) +
            '&offset=' + encodeURIComponent(String(this._offset)) +
            '&limit=' + encodeURIComponent(String(this.LIMIT));
        var answer = await fetchJSON(url);
        if (!answer) {
            this._error = I18n.t('biblioWs.unreachable');
            this._table = null;
        } else if (!answer.ok) {
            this._error = String(answer.error || '');
            this._table = null;
        } else {
            this._error = '';
            this._table = answer;
        }
        this.render();
    },

    page(delta) {
        var table = this._table;
        if (!table) return undefined;
        var total = Number(table.total) || 0;
        /* A page starts on a multiple of the page size. Clamping to `total - 1` instead let a
           164-row table — one page of 200 — jump to offset 163 and show its last row alone,
           which is what a real browser measured on the dual-map node. */
        var lastStart = Math.max(0, Math.floor((total - 1) / this.LIMIT) * this.LIMIT);
        var next = Math.max(0, Math.min(lastStart, Number(this._offset) + delta * this.LIMIT));
        if (next === this._offset) return undefined;
        this._offset = next;
        return this.load();
    },

    filter(term) {
        this._term = String(term || '');
        this.render();
    },

    /* The panel reads a run record; the canvas may or may not still hold that node.
       Saying nothing when it does not is how a jump button reads as broken. */
    locate() {
        if (!this._nodeId) return;
        if (!canvas.nodes[this._nodeId]) {
            showToast(I18n.t('biblioWs.locateMissing', { nid: this._nodeId }));
            return;
        }
        canvas.selectNode(this._nodeId);
        canvas.centerOnNode(this._nodeId);
    },

    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        this.render();
    },

    _shapeWord(shape) {
        // Read off the one list the panel and the settings select already share — a second
        // literal copy is how a shipped shape ends up labelled 「输出形态未知」.
        var s = String(shape || '');
        return BIBLIO_OUTPUT_SHAPES.indexOf(s) >= 0 ? I18n.t('biblioWs.shape.' + s) : I18n.t('biblioWs.shapeUnknown');
    },

    _rows() {
        var table = this._table;
        var rows = table && Array.isArray(table.rows) ? table.rows : [];
        var term = this._term.trim().toLowerCase();
        if (!term) return { rows: rows, shown: rows.length };
        var kept = rows.filter(function (row) {
            return Object.keys(row).some(function (key) {
                return String(row[key] === null || row[key] === undefined ? '' : row[key]).toLowerCase().indexOf(term) >= 0;
            });
        });
        return { rows: kept, shown: kept.length };
    },

    render() {
        var body = document.getElementById('biblio-mgr-body');
        if (!body) return;
        /* Every keystroke in the panel's own fields repaints the whole body, and a repaint
           destroys the element the caret was in: the user types one character, the box loses
           focus, and the next character needs another click (measured in Chrome 2026-10-24).
           Ask which field had focus and where its caret sat BEFORE the markup goes away. */
        var keep = this._focusedField(body);
        var self = this;
        var runs = this._runs || [];
        var parts = [];

        if (this._error) parts.push('<div class="biblio-note">' + escapeHtml(this._error) + '</div>');
        if (!runs.length && !this._error) {
            parts.push('<div class="runs-mgr-empty">' + escapeHtml(I18n.t('biblioWs.noRuns')) + '</div>');
            body.innerHTML = parts.join('');
            return;
        }

        var runOptions = runs.map(function (r) {
            var label = (r.workflow_name || I18n.t('name.unnamed')) + ' · ' + (r.started_at || '') + ' · ' + r.run_id;
            return '<option value="' + escapeHtml(r.run_id) + '"' +
                (String(r.run_id) === self._runId ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('');
        var run = this._run();
        var nodes = (run && run.nodes) || [];
        var nodeOptions = nodes.map(function (n) {
            var info = runsManager.nodeStatusInfo(n.status);
            var label = (n.title || n.node_id) + ' · ' + I18n.t(info.key) + ' · ' + (n.row_count || 0);
            return '<option value="' + escapeHtml(n.node_id) + '"' +
                (String(n.node_id) === self._nodeId ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('');

        parts.push(
            '<div class="biblio-bar">',
            '<label>' + escapeHtml(I18n.t('biblioWs.run')) +
                '<select onchange="biblioWorkspace.pickRun(this.value)"><option value="">' +
                escapeHtml(I18n.t('biblioWs.chooseRun')) + '</option>' + runOptions + '</select></label>',
            '<label>' + escapeHtml(I18n.t('biblioWs.node')) +
                '<select onchange="biblioWorkspace.pickNode(this.value)"><option value="">' +
                escapeHtml(I18n.t('biblioWs.chooseNode')) + '</option>' + nodeOptions + '</select></label>',
            '<input type="search" data-biblio-keep="search" value="' + escapeHtml(this._term) + '" placeholder="' +
                escapeHtml(I18n.t('biblioWs.search')) + '" oninput="biblioWorkspace.filter(this.value)">',
            '</div>'
        );

        var node = this._node();
        if (node) {
            parts.push(
                '<div class="biblio-files">',
                (node.files && node.files.length)
                    ? node.files.map(function (f) {
                        return '<a href="/api/exports/download?name=' + encodeURIComponent(f.name) + '">' +
                            escapeHtml(f.name) + '</a>';
                    }).join('')
                    : '<span class="biblio-note">' + escapeHtml(I18n.t('biblioWs.noFiles')) + '</span>',
                '</div>'
            );
        }

        var table = this._table;
        if (table) {
            var view = this._rows();
            var total = Number(table.total) || 0;
            var from = total ? this._offset + 1 : 0;
            var to = Math.min(total, this._offset + this.LIMIT);
            parts.push(
                '<div class="biblio-bar">',
                '<span class="biblio-shape">' + escapeHtml(this._shapeWord(table.shape)) + '</span>',
                '<span>' + escapeHtml(I18n.t('biblioWs.page', { from: from, to: to, total: total })) + '</span>',
                this._term
                    ? '<span>' + escapeHtml(I18n.t('biblioWs.filtered', { shown: view.shown })) + '</span>'
                    : '',
                '<button class="runs-mgr-btn" type="button" onclick="biblioWorkspace.page(-1)"' +
                    (this._offset <= 0 ? ' disabled' : '') + '>' + escapeHtml(I18n.t('biblioWs.prev')) + '</button>',
                '<button class="runs-mgr-btn" type="button" onclick="biblioWorkspace.page(1)"' +
                    (to >= total ? ' disabled' : '') + '>' + escapeHtml(I18n.t('biblioWs.next')) + '</button>',
                '</div>'
            );
            if (table.note) parts.push('<div class="biblio-note">' + escapeHtml(table.note) + '</div>');
            if (view.rows.length) {
                var columns = table.columns || [];
                parts.push(
                    '<table class="data-preview-table runs-mgr-table"><thead><tr>',
                    /* The word, with the STORED name kept as the tooltip: the header is interface
                       text, the name on disk is what the exported CSV/GraphML column is called,
                       and a translation that hides the second one cannot be matched back to it. */
                    columns.map(function (c) {
                        return '<th title="' + escapeHtml(c) + '">' + escapeHtml(biblioColumnWord(c)) + '</th>';
                    }).join(''),
                    '</tr></thead><tbody>',
                    view.rows.map(function (row) {
                        return '<tr>' + columns.map(function (c) {
                            var value = row[c];
                            return '<td>' + escapeHtml(value === null || value === undefined ? '' : String(value)) + '</td>';
                        }).join('') + '</tr>';
                    }).join(''),
                    '</tbody></table>'
                );
            }
        }
        parts.push(this._captureParts());
        parts.push(this._diffParts());
        body.innerHTML = parts.join('');
        /* The three pickers are rebuilt with the body, so they arrive as plain native
           controls — OS-drawn popup, white in a dark panel. The body-level observer would get
           round to them on the next animation frame, which is a frame in which the panel shows
           an un-themed control, and a panel that repaints on every keystroke never lets that
           frame arrive. `scan` also prunes the wrappers of the selects that just died. */
        if (window.CustomSelect) CustomSelect.scan(body);
        this._restoreFocus(body, keep);
    },

    /* Which of the panel's own typing fields held the caret, and where in it. Only the two
       fields marked `data-biblio-keep` matter: a select that loses focus mid-repaint is the
       picker firing its own change, and the pickers are rebuilt with the same value. */
    _focusedField(body) {
        var el = document.activeElement;
        if (!el || !el.getAttribute || !body.contains(el)) return '';
        var name = el.getAttribute('data-biblio-keep');
        if (!name) return '';
        return { name: name, start: el.selectionStart, end: el.selectionEnd };
    },

    _restoreFocus(body, keep) {
        if (!keep) return;
        var el = body.querySelector('[data-biblio-keep="' + keep.name + '"]');
        if (!el || !el.focus) return;
        el.focus();
        if (el.setSelectionRange && keep.start !== undefined && keep.start !== null) {
            el.setSelectionRange(keep.start, keep.end);
        }
    },

    /* The project picker, the capture button and the list of what this project has kept.
       A capture button that would be refused is rendered DISABLED with the reason beside it,
       so "why can't I save this?" is answered on the panel rather than by a toast after a
       click that does nothing. */
    _captureParts() {
        var self = this;
        var projects = this._projects || [];
        var options = projects.map(function (p) {
            var label = (p.name || I18n.t('name.unnamed')) + ' · ' + ((p.snapshots || []).length);
            return '<option value="' + escapeHtml(p.project_id) + '"' +
                (String(p.project_id) === self._projectId ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('');
        var project = this._project();
        var blocker = this.captureBlocker();
        var parts = [
            '<div class="biblio-bar">',
            '<label>' + escapeHtml(I18n.t('biblioWs.project')) +
                '<select onchange="biblioWorkspace.pickProject(this.value)"><option value="">' +
                escapeHtml(I18n.t('biblioWs.chooseProject')) + '</option>' + options + '</select></label>',
            '<input type="text" data-biblio-keep="label" value="' + escapeHtml(this._label) + '" placeholder="' +
                escapeHtml(I18n.t('biblioWs.snapshotLabel')) + '" oninput="biblioWorkspace.labelChanged(this.value)">',
            '<button class="runs-mgr-btn" type="button" onclick="biblioWorkspace.capture()"' +
                (blocker ? ' disabled' : '') + '>' + escapeHtml(I18n.t('biblioWs.capture')) + '</button>',
            blocker ? '<span class="biblio-note">' + escapeHtml(blocker) + '</span>' : '',
            '<input type="text" id="biblio-new-project" placeholder="' +
                escapeHtml(I18n.t('biblioWs.newProject')) + '">',
            '<button class="runs-mgr-btn" type="button" onclick="biblioWorkspace.createProject()">' +
                escapeHtml(I18n.t('biblioWs.createProject')) + '</button>',
            '</div>'
        ];
        var snapshots = (project && project.snapshots) || [];
        if (!snapshots.length) {
            parts.push('<div class="runs-mgr-empty">' + escapeHtml(I18n.t('biblioWs.noSnapshots')) + '</div>');
            return parts.join('');
        }
        parts.push(
            '<table class="data-preview-table runs-mgr-table"><thead><tr>',
            '<th>' + escapeHtml(I18n.t('biblioWs.colLabel')) + '</th>',
            '<th>' + escapeHtml(I18n.t('biblioWs.colWhen')) + '</th>',
            '<th>' + escapeHtml(I18n.t('biblioWs.colShape')) + '</th>',
            '<th>' + escapeHtml(I18n.t('biblioWs.colNodes')) + '</th>',
            '<th>' + escapeHtml(I18n.t('biblioWs.colEdges')) + '</th>',
            '<th>' + escapeHtml(I18n.t('biblioWs.colParams')) + '</th>',
            '<th>' + escapeHtml(I18n.t('biblioWs.colOps')) + '</th>',
            '</tr></thead><tbody>'
        );
        snapshots.forEach(function (snap) {
            var isBaseline = String(snap.snapshot_id) === self._baseline;
            parts.push(
                '<tr>',
                '<td>' + escapeHtml(snap.label || snap.node_id) + (isBaseline ? ' ★' : '') + '</td>',
                '<td>' + escapeHtml(snap.created_at || '') + '</td>',
                '<td>' + escapeHtml(self._shapeWord(snap.shape)) + '</td>',
                '<td>' + escapeHtml(String(snap.node_count || 0)) + '</td>',
                '<td>' + escapeHtml(String(snap.edge_count || 0)) + '</td>',
                '<td>' + escapeHtml(
                    I18n.t(snap.params_verified ? 'biblioWs.paramsVerified' : 'biblioWs.paramsUnverified')
                ) + '</td>',
                '<td>',
                '<button class="runs-mgr-btn" type="button" onclick="biblioWorkspace.setBaseline(\'' +
                    attrJsArg(snap.snapshot_id) + '\')">' + escapeHtml(I18n.t('biblioWs.setBaseline')) + '</button>',
                '<button class="runs-mgr-btn" type="button" onclick="biblioWorkspace.compareWith(\'' +
                    attrJsArg(snap.snapshot_id) + '\')"' + (self._baseline && !isBaseline ? '' : ' disabled') + '>' +
                    escapeHtml(I18n.t('biblioWs.compareWith')) + '</button>',
                '<button class="runs-mgr-btn del" type="button" onclick="biblioWorkspace.removeSnapshot(\'' +
                    attrJsArg(snap.snapshot_id) + '\')">' + escapeHtml(I18n.t('biblioWs.delete')) + '</button>',
                '</td></tr>'
            );
        });
        parts.push('</tbody></table>');
        return parts.join('');
    },

    /* The diff is the server's answer, printed line by line. A capped line says both the head
       it shows and the total it cut, because a truncated diff shown as a complete one is a
       wrong diff. The labels are literal catalogue keys (never `'biblioWs.' + section + '.' +
       field`): a key assembled at runtime is a key no reachability scan can see, and a dead
       word on this panel would look like a live one. */
    _diffParts() {
        var diff = this._diff;
        if (!diff) return '';
        var parts = ['<div class="biblio-bar">'];
        parts.push(
            '<span class="biblio-shape">' + escapeHtml(I18n.t('biblioWs.diffTitle', {
                a: (diff.a && diff.a.label) || '', b: (diff.b && diff.b.label) || '',
            })) + '</span>',
            diff.same_shape ? '' : '<span class="biblio-note">' + escapeHtml(I18n.t('biblioWs.shapeDiffers')) + '</span>',
            diff.same_project ? '' : '<span class="biblio-note">' + escapeHtml(I18n.t('biblioWs.projectDiffers')) + '</span>',
            '<button class="runs-mgr-btn" type="button" onclick="biblioWorkspace.clearDiff()">' +
                escapeHtml(I18n.t('biblioWs.clearDiff')) + '</button>',
            '</div>'
        );
        var quiet = true;
        BIBLIO_DIFF_LINES.forEach(function (line) {
            var section = diff[line.section];
            // `params_differ` IS the capped list; the other sections hold one per field.
            var payload = line.field ? (section && section[line.field]) : section;
            if (!payload || typeof payload !== 'object' || !payload.total) return;
            quiet = false;
            parts.push(
                '<div class="sched-status">' + escapeHtml(I18n.t(line.title)) + '</div>',
                '<div>' + escapeHtml(I18n.t(line.label, { total: payload.total })) +
                    ': ' + escapeHtml(payload.items.map(_diffItem).join('、')) + '</div>'
            );
            if (payload.total > payload.items.length) {
                parts.push(
                    '<div class="biblio-note">' +
                        escapeHtml(I18n.t('biblioWs.capped', { shown: payload.items.length, total: payload.total })) +
                    '</div>'
                );
            }
        });
        if (quiet) parts.push('<div class="runs-mgr-empty">' + escapeHtml(I18n.t('biblioWs.diffNone')) + '</div>');
        return parts.join('');
    },
};

/* Which diff sections exist and what each line is called. Field names are the server's
   (`compare_snapshots` builds them); the labels are catalogue literals. */
var BIBLIO_DIFF_LINES = [
    { section: 'params_differ', field: '', title: 'biblioWs.diffParams', label: 'biblioWs.line.params' },
    { section: 'nodes', field: 'added', title: 'biblioWs.diffNodes', label: 'biblioWs.line.nodesAdded' },
    { section: 'nodes', field: 'removed', title: 'biblioWs.diffNodes', label: 'biblioWs.line.nodesRemoved' },
    { section: 'nodes', field: 'changed', title: 'biblioWs.diffNodes', label: 'biblioWs.line.nodesChanged' },
    { section: 'edges', field: 'added', title: 'biblioWs.diffEdges', label: 'biblioWs.line.edgesAdded' },
    { section: 'edges', field: 'removed', title: 'biblioWs.diffEdges', label: 'biblioWs.line.edgesRemoved' },
    { section: 'edges', field: 'weight_changed', title: 'biblioWs.diffEdges', label: 'biblioWs.line.edgesWeight' },
    { section: 'clusters', field: 'added', title: 'biblioWs.diffClusters', label: 'biblioWs.line.clusterAdded' },
    { section: 'clusters', field: 'removed', title: 'biblioWs.diffClusters', label: 'biblioWs.line.clusterRemoved' },
    { section: 'clusters', field: 'relabeled', title: 'biblioWs.diffClusters', label: 'biblioWs.line.clusterRelabeled' },
    { section: 'clusters', field: 'size_changed', title: 'biblioWs.diffClusters', label: 'biblioWs.line.clusterSize' },
    { section: 'bursts', field: 'added', title: 'biblioWs.diffBursts', label: 'biblioWs.line.burstAdded' },
    { section: 'bursts', field: 'removed', title: 'biblioWs.diffBursts', label: 'biblioWs.line.burstRemoved' },
    { section: 'bursts', field: 'strength_changed', title: 'biblioWs.diffBursts', label: 'biblioWs.line.burstStrength' },
];

/* One diff entry as a line of text: a bare name, or a pair of numbers that moved. */
function _diffItem(item) {
    if (item === null || typeof item !== 'object') return String(item);
    if ('source' in item && 'target' in item) {
        return 'a' in item
            ? item.source + ' ↔ ' + item.target + ': ' + item.a + ' → ' + item.b
            : item.source + ' ↔ ' + item.target;
    }
    if ('columns' in item) {
        return item.name + ' (' + Object.keys(item.columns).map(function (column) {
            return column + ': ' + item.columns[column].a + ' → ' + item.columns[column].b;
        }).join('; ') + ')';
    }
    if ('name' in item && 'a' in item) return item.name + ': ' + item.a + ' → ' + item.b;
    if ('cluster' in item) return '#' + item.cluster + ': ' + item.a + ' → ' + item.b;
    return JSON.stringify(item);
}

