/* The durable run-log viewer: a whole run's console, long after it ended.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-28) byte for byte. The live console ships only its
 * last 200 lines and is wiped when the next run starts; this reads ONLY the persisted ``run_log``
 * table over ``/api/runs/<id>/log``, so it can never disturb the live console or the page-refresh
 * reattach. Filtering (level / workflow / search) is applied server-side and the 「下载 .txt」 link
 * sends the SAME parameters, so what you download is what you see.
 */

/* ── Durable run-log viewer ───────────────────────────────────────────────
   The live console only ships the last 200 lines and is wiped when the next run
   starts; the per-run console is also persisted to run_log, so a run's WHOLE output is
   readable long afterwards. This reads ONLY that durable table over /api/runs/<id>/log —
   it never touches execution_state, so it cannot disturb the live console or the
   page-refresh reattach. Filtering (level / workflow / search) is applied server-side and
   the 「下载 .txt」 link sends the SAME parameters, so what you download is what you see. */
var runLogViewer = {
    PAGE: 500,
    _runId: '',
    _rows: [],          // ascending (oldest→newest) rows currently shown
    _oldestSeq: null,   // smallest seq loaded — the 「加载更早」 cursor
    _hasMore: false,
    _levels: ['', 'info', 'warning', 'error'],
    _workflows: {},     // wf_idx -> wf_name, discovered from loaded rows (so the tab list grows as lines load)

    open: function (runId) {
        if (!runId) return;
        this._runId = String(runId);
        this._rows = [];
        this._oldestSeq = null;
        this._hasMore = false;
        this._workflows = {};
        this._ensureDom();
        this._title();
        this._dom.overlay.classList.add('open');
        this.load();
    },

    close: function () {
        if (this._dom) this._dom.overlay.classList.remove('open');
    },

    _qs: function () {
        var p = [];
        var level = this._dom && this._dom.level ? this._dom.level.value : '';
        var wf = this._dom && this._dom.wf ? this._dom.wf.value : '';
        var q = this._dom && this._dom.search ? this._dom.search.value.trim() : '';
        if (level) p.push('level=' + encodeURIComponent(level));
        if (wf !== '') p.push('wf=' + encodeURIComponent(wf));
        if (q) p.push('q=' + encodeURIComponent(q));
        return p;
    },

    load: async function () {
        var params = this._qs();
        params.push('limit=' + this.PAGE);
        this._setStatus(this._t('runLog.loading'));
        try {
            var resp = await fetch('/api/runs/' + encodeURIComponent(this._runId) + '/log?' + params.join('&'));
            if (!resp.ok) throw new Error('http ' + resp.status);
            var data = await resp.json();
            this._rows = data.rows || [];
            this._oldestSeq = data.min_seq;
            this._hasMore = !!data.has_more;
            this._noteWorkflows(this._rows);
            this.render();
        } catch (e) {
            this._setStatus(this._t('runLog.loadFailed'));
        }
    },

    loadOlder: async function () {
        if (!this._hasMore || this._oldestSeq === null) return;
        var params = this._qs();
        params.push('before=' + this._oldestSeq, 'limit=' + this.PAGE);
        this._setStatus(this._t('runLog.loading'));
        try {
            var resp = await fetch('/api/runs/' + encodeURIComponent(this._runId) + '/log?' + params.join('&'));
            if (!resp.ok) throw new Error('http ' + resp.status);
            var data = await resp.json();
            var older = data.rows || [];
            this._rows = older.concat(this._rows);
            if (data.min_seq !== null && data.min_seq !== undefined) this._oldestSeq = data.min_seq;
            this._hasMore = !!data.has_more;
            this._noteWorkflows(older);
            this.render();
        } catch (e) {
            this._setStatus(this._t('runLog.loadFailed'));
        }
    },

    reload: function () {
        this._rows = [];
        this._oldestSeq = null;
        this._hasMore = false;
        this.load();
    },

    download: function () {
        var params = this._qs();
        window.location.href = '/api/runs/' + encodeURIComponent(this._runId) + '/log.txt?' + params.join('&');
    },

    _noteWorkflows: function (rows) {
        rows.forEach(function (r) {
            if (r.wf_idx !== null && r.wf_idx !== undefined) this._workflows[r.wf_idx] = r.wf_name || '';
        }, this);
        if (this._dom) this._rebuildWfOptions();
    },

    _t: function (key, params) {
        var s = (typeof I18n !== 'undefined' && I18n.t) ? I18n.t(key) : key;
        if (params) Object.keys(params).forEach(function (k) { s = s.replace('{' + k + '}', params[k]); });
        return s;
    },

    _title: function () {
        /* The name must belong to THIS run, not the canvas currently loaded: a person
           opens a historical record precisely when it is a different workflow than what
           is on screen, and titling it with `#workflow-name` (the live canvas) labelled a
           run with the wrong name. The row we were launched from already carries the run's
           own stored name as a (HTML-escaped) data attribute — read that, else the id. */
        var name = '';
        var rows = document.querySelectorAll('tr[data-run-id]') || [];
        for (var i = 0; i < rows.length; i += 1) {
            if (rows[i].dataset && rows[i].dataset.runId === this._runId) {
                name = rows[i].dataset.runName || '';
                break;
            }
        }
        name = String(name || '').trim() || this._runId;
        this._dom.title.textContent = this._t('runLog.title', { name: name });
    },

    _rebuildWfOptions: function () {
        var sel = this._dom.wf;
        var keep = sel.value;
        sel.innerHTML = '';
        var all = document.createElement('option');
        all.value = '';
        all.textContent = this._t('console.all');
        sel.appendChild(all);
        Object.keys(this._workflows).sort(function (a, b) { return Number(a) - Number(b); }).forEach(function (idx) {
            var o = document.createElement('option');
            o.value = idx;
            o.textContent = this._workflows[idx] || ('#' + (Number(idx) + 1));
            sel.appendChild(o);
        }, this);
        sel.value = keep;
    },

    _setStatus: function (text) {
        if (this._dom && this._dom.status) this._dom.status.textContent = text;
    },

    render: function () {
        var self = this;
        var html = this._rows.map(function (r) {
            var cls = 'console-line run-log-line lvl-' + escapeHtml(r.level || 'info');
            return '<div class="' + cls + '">' + escapeHtml(r.line || '') + '</div>';
        }).join('');
        if (!this._rows.length) {
            html = '<div class="run-log-empty">' + escapeHtml(this._t('runLog.empty')) + '</div>';
        }
        this._dom.body.innerHTML = html;
        // Newest run output is what people came to read — land at the bottom, live-console style.
        this._dom.body.scrollTop = this._dom.body.scrollHeight;
        this._dom.older.style.display = this._hasMore ? '' : 'none';
        this._dom.older.textContent = this._t('runLog.loadOlder');
    },

    _ensureDom: function () {
        if (this._dom) return;
        var overlay = document.createElement('div');
        overlay.id = 'run-log-overlay';
        overlay.className = 'run-log-overlay';
        overlay.innerHTML =
            '<div class="run-log-panel" role="dialog" aria-modal="true">' +
            '<div class="run-log-head">' +
            '<span class="run-log-title" id="run-log-title"></span>' +
            '<span class="run-log-spacer"></span>' +
            '<button class="menu-btn" id="run-log-download">' + this._t('runLog.download') + '</button>' +
            '<button class="menu-btn" id="run-log-close">' + this._t('runLog.close') + '</button>' +
            '</div>' +
            '<div class="run-log-filters">' +
            '<select id="run-log-level" class="settings-select"></select>' +
            '<select id="run-log-wf" class="settings-select"></select>' +
            '<input id="run-log-search" class="settings-input" type="text" placeholder="' + escapeHtml(this._t('runLog.search')) + '" />' +
            '</div>' +
            '<pre class="run-log-body" id="run-log-body"></pre>' +
            '<div class="run-log-foot"><button class="menu-btn" id="run-log-older"></button><span class="run-log-status" id="run-log-status"></span></div>' +
            '</div>';
        document.body.appendChild(overlay);
        this._dom = {
            overlay: overlay,
            title: overlay.querySelector('#run-log-title'),
            level: overlay.querySelector('#run-log-level'),
            wf: overlay.querySelector('#run-log-wf'),
            search: overlay.querySelector('#run-log-search'),
            body: overlay.querySelector('#run-log-body'),
            older: overlay.querySelector('#run-log-older'),
            status: overlay.querySelector('#run-log-status'),
        };
        // Level options.
        var self = this;
        [['', this._t('runLog.allLevels')], ['info', this._t('runLog.levelInfo')], ['warning', this._t('runLog.levelWarn')], ['error', this._t('runLog.levelError')]]
            .forEach(function (pair) {
                var o = document.createElement('option');
                o.value = pair[0];
                o.textContent = pair[1];
                self._dom.level.appendChild(o);
            });
        overlay.querySelector('#run-log-close').addEventListener('click', function () { self.close(); });
        overlay.querySelector('#run-log-download').addEventListener('click', function () { self.download(); });
        this._dom.older.addEventListener('click', function () { self.loadOlder(); });
        this._dom.level.addEventListener('change', function () { self.reload(); });
        this._dom.wf.addEventListener('change', function () { self.reload(); });
        // Enter in the search box is the filter action, like every other search field.
        this._dom.search.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') self.reload(); });
        // Click the backdrop (not the panel) and Escape both dismiss — the dialog contract.
        overlay.addEventListener('click', function (ev) { if (ev.target === overlay) self.close(); });
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && overlay.classList.contains('open')) self.close();
        });
    },
};
