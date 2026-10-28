/* Run results: the resume banner and the loaded-run result drawer.
 * Split out of workflow.js; loaded after it so every global name stays resolvable. */

/* ── Resume banner ─────────────────────────────────────────────
   A run that was interrupted leaves its rows behind, and the only place to say
   so is here: the alternative is a silent re-run that throws away everything
   already paid for. It is refreshed after every run and whenever the canvas
   is rebuilt, because the match depends on the workflow's shape. */
var resumeBar = {
    candidate: null,

    async refresh() {
        const banner = document.getElementById('resume-banner');
        if (!banner) return null;
        /* The guard has to name the binding that exists. `canvas` is a top-level
           `const`, which never becomes a property of `window`, so `window.canvas`
           read as undefined forever and this function hid the banner and returned
           before asking the server — 断点续跑 had no entry point in the UI at all.
           What the check is for is an empty canvas: with nothing on it there is no
           workflow shape to match a stored run against. */
        if (!canvas || !Object.keys(canvas.nodes || {}).length) {
            this.candidate = null;
            banner.classList.add('hidden');
            return null;
        }
        let runs = [];
        try {
            const resp = await fetch('/api/runs/resumable', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workflow: canvas.toWorkflowJSON() }),
            });
            const result = await resp.json();
            runs = (result.ok && result.runs) || [];
        } catch (e) {
            runs = [];
        }
        /* Anything still running belongs to this moment, not to a past attempt. */
        this.candidate = runs[0] || null;
        /* A cold load has no in-memory results, but the last run's upstream rows are durable and
           the render endpoint resolves them by ``workflow_name`` — so open the board once and the
           charts repaint themselves. Guarded so it fires on the load, never mid-session (a run
           opens the board on its own), and only when the canvas actually has chart nodes. */
        if (this.candidate && !this._rehydrated && typeof dashboard !== 'undefined') {
            this._rehydrated = true;
            const hasChart = Object.keys(canvas.nodes || {}).some(function (id) {
                return canvas.nodes[id] && canvas.nodes[id].type === 'visualize';
            });
            if (hasChart) { dashboard.open(); }
        }
        this.render();
        return this.candidate;
    },

    render() {
        const banner = document.getElementById('resume-banner');
        const text = document.getElementById('resume-text');
        if (!banner || !text) return;
        if (!this.candidate) {
            banner.classList.add('hidden');
            return;
        }
        const run = this.candidate;
        const detail = I18n.t('resume.detail')
            .replace('{done}', run.node_done || 0)
            .replace('{total}', run.node_total || 0)
            .replace('{rows}', run.rows_kept || 0);
        text.textContent = I18n.t('resume.interrupted').replace('{at}', run.started_at || run.run_id) + ' — ' + detail;
        banner.classList.remove('hidden');
    },

    continueRun() {
        if (!this.candidate) return;
        workflow.execute({ resumeRunId: this.candidate.run_id });
    },

    async restart() {
        const runId = this.candidate && this.candidate.run_id;
        this.hide();
        if (runId) {
            try {
                /* Dropping the saved run includes its "already crawled" claims,
                   otherwise the fresh run would skip everything it fetched. */
                await fetch('/api/runs/discard', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ run_id: runId }),
                });
            } catch (e) { /* a failed discard still starts the run */ }
            showToast(I18n.t('toast.runDiscarded'));
        }
        workflow.execute();
    },

    dismiss() {
        this.hide();
    },

    hide() {
        this.candidate = null;
        const banner = document.getElementById('resume-banner');
        if (banner) banner.classList.add('hidden');
    },
};

/* ── Loaded run results ──────────────────────────────────────
   The canvas shows ONE run's results at a time. On entry that is the newest
   run filed under this workflow's structure (the default the user asked for);
   运行记录 ▸ 当前工作流 can load any earlier one. The id is pinned into every
   preview/chart/dashboard payload, so the server reads that exact attempt
   instead of independently picking each node's newest rows — which could stitch
   last night's node-1 to this morning's node-2 and call it one table.

   Node verdicts come from the run ledger (`/api/runs/for-workflow` and the live
   `/api/workflow/status`), never from the canvas's own guesses: several nodes
   can be `running` at once in parallel mode, and `done`/`restored` are the only
   two words that mean success. */
var runResults = {
    runId: '',
    runIds: [],
    run: null,
    runs: [],
    statuses: {},
    followLive: false,
    workflowFingerprint: '',
    _seq: 0,
    _lastApplied: '',

    isLoaded(runId) {
        var id = String(runId || '');
        return !!id && (id === this.runId || this.runIds.indexOf(id) >= 0);
    },

    /* The record that actually holds a node's verdict. In a split serial canvas one
       attempt owns several run rows, and a node belongs to exactly one of them. */
    runIdFor(nodeId) {
        var info = this.statuses && this.statuses[nodeId];
        return String((info && info.run_id) || this.runId || '');
    },

    async refresh(selectRunId) {
        /* A canvas with nothing on it has no structure to match — and the server
           must not be asked to fingerprint an empty workflow. */
        if (typeof canvas === 'undefined' || !canvas || !Object.keys(canvas.nodes || {}).length) {
            this.clear();
            return null;
        }
        var seq = ++this._seq;
        var result;
        try {
            var resp = await fetch('/api/runs/for-workflow', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workflow: canvas.toWorkflowJSON(), limit: 50 }),
            });
            result = await resp.json();
        } catch (e) {
            return null;
        }
        /* A second refresh started while this one was in flight (a run finishing
           during boot, a quick tab switch). The newer answer is the truth. */
        if (seq !== this._seq) return null;
        if (!result || !result.ok) return null;
        this.runs = result.runs || [];
        this.workflowFingerprint = result.workflow_fingerprint || '';
        var wanted = String(selectRunId || this.runId || '');
        var run =
            this.runs.filter(function (r) {
                return r.run_id === wanted;
            })[0] ||
            this.runs[0] ||
            null;
        if (!run) {
            this.clear();
            return null;
        }
        this._apply(run, { live: run.status === 'running' });
        return run;
    },

    /* One run's node statuses → the canvas badges. The map is replaced, not merged:
       loading another run must not leave a green check from the previous one. */
    _apply(run, opts) {
        var live = !!(opts && opts.live);
        this.run = run;
        this.runId = String(run.run_id || '');
        this.runIds = this.runId ? [this.runId] : [];
        this.followLive = live;
        var map = {};
        (run.nodes || []).forEach(function (n) {
            var nid = String(n.node_id || '');
            if (!nid) return;
            map[nid] = {
                status: String(n.status || ''),
                row_count: Number(n.row_count || 0),
                error: String(n.error || ''),
                run_id: String(run.run_id || ''),
            };
        });
        this.statuses = map;
        if (typeof canvas !== 'undefined' && canvas && canvas.applyRunStatuses) canvas.applyRunStatuses(map);
        if (this._lastApplied !== this.runId) {
            this._lastApplied = this.runId;
            this._repaint();
        }
    },

    /* Load an arbitrary record from 运行记录. The list the panel already holds
       carries the node map, so the common path costs no request; a run that has
       since been deleted falls back to one detail read and says so when that
       fails too. */
    async load(runId) {
        var id = String(runId || '').trim();
        if (!id) return null;
        /* A selection is newer than any read already in flight: without this a
           boot-time refresh could land afterwards and put today's latest run back. */
        this._seq += 1;
        var found = (this.runs || []).filter(function (r) {
            return r.run_id === id;
        })[0];
        if (!found) {
            try {
                var resp = await fetch('/api/runs/' + encodeURIComponent(id));
                var result = await resp.json();
                if (result && result.ok && result.run) found = result.run;
            } catch (e) {
                found = null;
            }
        }
        if (!found) {
            showToast(I18n.t('runsMgr.loadFailed').replace('{rid}', id));
            return null;
        }
        /* Reloading the same record is a real request to repaint (its rows may
           have changed, or a cell failed last time). */
        this._lastApplied = '';
        this._apply(found, { live: found.status === 'running' });
        if (window.runsManager) runsManager.refreshIfOpen();
        var when = found.started_at || found.run_id || id;
        showToast(I18n.t('runsMgr.loadedToast').replace('{when}', when));
        return found;
    },

    /* A run just started (Run or 从此节点重跑). Old verdicts go away immediately;
       the first status tick paints the nodes the worker has reached. */
    beginLive(runId) {
        /* The new attempt outranks any read that started before it. */
        this._seq += 1;
        this.runId = String(runId || '');
        this.runIds = this.runId ? [this.runId] : [];
        this.run = null;
        this.statuses = {};
        this.followLive = true;
        this._lastApplied = this.runId;
        if (typeof canvas !== 'undefined' && canvas && canvas.applyRunStatuses) canvas.applyRunStatuses({});
    },

    /* Live status map from /api/workflow/status. Ignored when the user has
       deliberately loaded an older run mid-flight — following the worker would
       yank their choice out from under them. */
    applyLive(states, runIds) {
        if (!this.followLive) return;
        if (Array.isArray(runIds) && runIds.length) {
            this.runIds = runIds.map(String);
            if (!this.runId || this.runIds.indexOf(this.runId) < 0) this.runId = this.runIds[0] || '';
        }
        var map = Object.assign({}, this.statuses || {});
        Object.keys(states || {}).forEach(function (nid) {
            var s = states[nid];
            if (!s) return;
            map[nid] = {
                status: String(s.status || ''),
                row_count: Number(s.row_count || 0),
                error: String(s.error || ''),
                run_id: String(s.run_id || ''),
            };
        });
        this.statuses = map;
        if (typeof canvas !== 'undefined' && canvas && canvas.applyRunStatuses) canvas.applyRunStatuses(map);
    },

    /* The worker wrote its verdict. Re-read the record so the panel's marker and
       the node map agree with what was persisted, and stop following its stream. */
    finishLive() {
        if (!this.followLive) return;
        this.followLive = false;
        /* A split serial attempt owns several run records, one per workflow. The
           live map already covers every component's nodes; re-reading just one id
           would drop the other components' badges. The panel still refreshes, and
           a single-record run is re-read so its final row counts are authoritative. */
        if (this.runIds.length > 1) {
            if (window.runsManager) runsManager.refreshIfOpen();
            return;
        }
        /* The record now holds the final rows, even though the id did not change;
           clearing the applied marker makes the refresh repaint open panels. */
        this._lastApplied = '';
        this.refresh(this.runId);
        if (window.runsManager) runsManager.refreshIfOpen();
    },

    canRerun(nodeId) {
        var info = this.statuses && this.statuses[nodeId];
        if (!info || !this.runIdFor(nodeId)) return false;
        return (info.status === 'done' || info.status === 'restored') && Number(info.row_count || 0) > 0;
    },

    rerunFrom(nodeId) {
        if (!this.canRerun(nodeId)) {
            showToast(I18n.t('toast.rerunNoResult'));
            return;
        }
        var runId = this.runIdFor(nodeId);
        if (typeof workflow === 'undefined' || !workflow.rerunNode) return;
        workflow.rerunNode(nodeId, runId);
    },

    /* Every preview of a node's rows carries the loaded run, so one screen never
       mixes two attempts. */
    payload(payload) {
        if (this.runId) payload.run_id = this.runId;
        return payload;
    },

    /* Panels already on screen follow the newly loaded run instead of continuing to
       show the previous one's picture. Closed panels are left closed: loading a
       run is not a request to open a chart. */
    _repaint() {
        if (typeof document === 'undefined' || !document.getElementById) return;
        var chartPanel = document.getElementById('chart-preview-panel');
        if (chartPanel && chartPanel.classList.contains('open') && _chartPreviewNodeId) {
            dataNodes.previewVisualize(_chartPreviewNodeId);
        }
        var dash = document.getElementById('dashboard-panel');
        if (dash && dash.classList.contains('open') && typeof dashboard !== 'undefined') {
            dashboard.open();
        }
        var preview = document.getElementById('data-preview-panel');
        if (preview && preview.classList.contains('open') && dataPreview._payload && dataPreview._payload.node_id) {
            dataPreview._payload.run_id = this.runId || undefined;
            if (!dataPreview._payload.run_id) delete dataPreview._payload.run_id;
            dataPreview._offset = 0;
            dataPreview._fetch();
        }
    },

    clear() {
        this._seq += 1;
        this.runId = '';
        this.runIds = [];
        this.run = null;
        this.runs = [];
        this.statuses = {};
        this.followLive = false;
        this.workflowFingerprint = '';
        this._lastApplied = '';
        if (typeof canvas !== 'undefined' && canvas && canvas.applyRunStatuses) canvas.applyRunStatuses({});
    },
};

