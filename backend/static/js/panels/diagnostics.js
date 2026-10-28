/* Edit-time diagnostics: what each node emits and reads, before a run is paid for.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-29) byte for byte. The backend answers what each
 * node emits and reads (the schema truth lives beside the executors); this panel decides WHICH nodes
 * to flag and words it in the UI's language. The cost estimate beside it is part of the same panel:
 * its refresh calls ``renderCostSummary``.
 */

/* ─── Edit-time diagnostics ───────────────────────────────────────────
   Before this, a wrong column or a missing config only surfaced when a run was
   already paid for. The backend answers WHAT each node emits and reads (the schema
   truth lives beside the executors); the frontend decides WHICH nodes to flag and
   words it in the UI's language. Config/wiring problems come from the offline
   validateDetailed mirror; missing-column problems are the diff between a node's
   reads and its upstream's known columns — never flagged when the upstream is a
   crawl/comment/resume whose columns the server cannot see without running. */
var Diagnostics = {
    _timer: null,
    _armed: false,
    _columns: {},
    _reads: {},
    _problems: {},

    schedule() {
        // Armed only by the real page boot (app.js), so a workflow-only harness —
        // or any scenario that never dispatches DOMContentLoaded — fires nothing.
        if (!this._armed) return;
        var self = this;
        if (this._timer) clearTimeout(this._timer);
        this._timer = setTimeout(function () {
            self._timer = null;
            try { self.refresh(); } catch (e) { /* a background diagnostic never breaks the page */ }
        }, 500);
    },

    async refresh() {
        /* A canvas-only or workflow-only harness has no `canvas`; and a failed
           diagnostic must never crash the page it decorates — guard the whole body. */
        if (typeof canvas === 'undefined' || !canvas || !canvas.nodes) return;
        try {
            /* Only the serialisable model goes over the wire: a node's `el` is a live DOM
               element (circular), so the whole node object cannot be JSON.stringify'd. */
            var clean = {};
            Object.keys(canvas.nodes).forEach(function (id) {
                var n = canvas.nodes[id];
                clean[id] = { id: id, type: n.type, title: n.title || '', params: n.params || {} };
            });
            var payload = {
                nodes: clean,
                connections: canvas.connections,
                settings: { disabledTypes: (canvas.disabledTypes || []).slice() },
            };
            var result = await fetchJSON('/api/workflow/diagnostics', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }).catch(function () { return null; });
            if (!result || !result.ok) return; /* offline: keep the last known picture */
            this._columns = result.columns || {};
            this._reads = result.reads || {};
            this.recompute();
        } catch (e) { /* diagnostics are decoration; a failure leaves the last picture */ }
    },

    /* The columns a node RECEIVES = union of its direct upstream producers' emitted
       columns; unknown (null) if any upstream is unknown, so a crawl never triggers a
       false "missing column" on everything below it. */
    inputColumns(id) {
        var ups = canvas.connections.filter(function (c) { return String(c.to) === String(id); }).map(function (c) { return c.from; });
        if (!ups.length) return [];
        var cols = [];
        for (var i = 0; i < ups.length; i += 1) {
            var c = this._columns[ups[i]];
            if (c === null || c === undefined) return null;
            c.forEach(function (x) { if (cols.indexOf(x) < 0) cols.push(x); });
        }
        return cols;
    },

    missingColumnProblems() {
        var out = {};
        var self = this;
        var nodes = canvas.nodes;
        Object.keys(this._reads).forEach(function (id) {
            var reads = self._reads[id] || [];
            if (!reads.length) return;
            var input = self.inputColumns(id);
            if (input === null) return; /* unknown upstream: never guess */
            var missing = reads.filter(function (col) { return input.indexOf(col) < 0; });
            if (missing.length) {
                var node = nodes[id];
                var label = (node && node.title) || id;
                out[id] = [I18n.t('diagnostics.missingColumn').replace('{cols}', missing.join(', ')).replace('{node}', label)];
            }
        });
        return out;
    },

    recompute() {
        if (typeof canvas === 'undefined' || !canvas || !canvas.nodes) return;
        var perNode = workflow.validateDetailed().perNode || {};
        var merged = {};
        Object.keys(perNode).forEach(function (id) { merged[id] = perNode[id].slice(); });
        var missing = this.missingColumnProblems();
        Object.keys(missing).forEach(function (id) {
            (merged[id] = merged[id] || []).push.apply(merged[id], missing[id]);
        });
        this._problems = merged;
        if (typeof canvas._applyValidationVisuals === 'function') canvas._applyValidationVisuals(merged);
        renderCostSummary();
    },

    problems(id) { return this._problems[id] || []; },
    outputColumns(id) {
        var c = this._columns[id];
        return (c === undefined) ? null : c;
    },
};

/* Cost estimate: rows are read straight from the crawl matrix's own per-mode defaults
   (target_count etc.), so nothing here re-declares a platform constant; LLM calls are
   one per row for an llm-mode analyzer, and capped at 30 for a topic/cluster label.
   Unbounded cases (a comment crawl with no limit) are reported as such, not as a
   precise number. */
function _matrixField(platform, modeKey, fieldKey) {
    if (typeof Capabilities === 'undefined' || !Capabilities.ready()) return null;
    var mode = Capabilities.mode(platform, modeKey);
    if (!mode || !mode.fields) return null;
    for (var i = 0; i < mode.fields.length; i += 1) {
        if (mode.fields[i].key === fieldKey) return mode.fields[i];
    }
    return null;
}

function _splitUrls(value) {
    return String(value || '').split(/[\r\n]+/).map(function (s) { return s.trim(); }).filter(Boolean);
}

function _sourceRows(node) {
    var p = node.params || {};
    if (node.type === 'comment') {
        var n = _splitUrls(p.urls).length;
        var lim = parseInt(p.comment_limit, 10) || 0;
        return lim > 0 ? { rows: n * lim, unbounded: false } : { rows: n, unbounded: n > 0 };
    }
    if (node.type === 'upload') {
        return { rows: parseInt(p.row_count, 10) || 0, unbounded: false };
    }
    var f = _matrixField(p.platform, p.collect || p.mode || '', 'target_count');
    var val = parseInt(p.target_count, 10);
    if (isNaN(val)) val = f && f.default != null ? f.default : 50;
    if (f && f.minimum != null) val = Math.max(val, f.minimum);
    return { rows: val, unbounded: false };
}

function _rowsAt(id, memo, stack) {
    memo = memo || {};
    stack = stack || {};
    if (memo[id] !== undefined) return memo[id];
    if (stack[id]) return { rows: 0, unbounded: false };
    stack[id] = true;
    var node = canvas.nodes[id];
    var r;
    if (!node) {
        r = { rows: 0, unbounded: false };
    } else if (node.type === 'source' || node.type === 'comment' || node.type === 'upload') {
        r = _sourceRows(node);
    } else {
        var ups = canvas.connections.filter(function (c) { return String(c.to) === String(id); }).map(function (c) { return c.from; });
        var total = 0;
        var unb = false;
        ups.forEach(function (u) { var x = _rowsAt(u, memo, stack); total += x.rows; unb = unb || x.unbounded; });
        r = { rows: total, unbounded: unb };
    }
    delete stack[id];
    memo[id] = r;
    return r;
}

function _processLlm(op, p) {
    var llmOps = ['clean', 'emotion', 'tendency', 'sentiment', 'ner', 'aggression'];
    if (llmOps.indexOf(op) < 0) return false;
    var mode = String(p.mode || p.method || '');
    return mode === 'llm';
}

/* A label step asks the LLM once per row it summarises, and the node caps how many rows
   it will label (topic_label -> label_max_topics, cluster_label -> cluster_max_groups).
   The row-flow model OVER-counts a label node: _rowsAt hands back the whole upstream
   table, not the handful of topic/cluster rows the node actually reads, so the cap — not
   the row sum — is what bounds the real spend. Defaults match the node renderers. */
function _isLabelOp(op) {
    return op === 'topic_label' || op === 'cluster_label' || op === 'cluster_review';
}

function _labelCallCap(op, src) {
    var s = src || {};
    if (op === 'topic_label') {
        var t = parseInt(s.label_max_topics, 10);
        return isNaN(t) ? 30 : t;
    }
    if (op === 'cluster_label') {
        var g = parseInt(s.cluster_max_groups, 10);
        return isNaN(g) ? 60 : g;
    }
    if (op === 'cluster_review') {
        var rv = parseInt(s.review_max_groups, 10);
        return isNaN(rv) ? 60 : rv;
    }
    return 0;
}

function estimateCost() {
    var memo = {};
    var crawlRows = 0;
    var llmCalls = 0;
    var unbounded = false;
    Object.keys(canvas.nodes).forEach(function (id) {
        var node = canvas.nodes[id];
        var p = node.params || {};
        if (node.type === 'source' || node.type === 'comment' || node.type === 'upload') {
            var s = _sourceRows(node);
            crawlRows += s.rows;
            unbounded = unbounded || s.unbounded;
        }
        var here = _rowsAt(id, memo);
        if (node.type === 'process' && _processLlm(node.operation || p.operation, p)) {
            llmCalls += here.rows;
            unbounded = unbounded || here.unbounded;
        } else if (node.type === 'analysis') {
            /* A label op is either the analysis node's OWN operation (the shape the canvas
               saves — this was the miss, contributing 0) or one of its p.steps. Both count. */
            var ownOp = String(node.operation || p.operation || '');
            if (_isLabelOp(ownOp)) {
                llmCalls += Math.min(here.rows, _labelCallCap(ownOp, p));
            }
            (p.steps || []).forEach(function (st) {
                if (st && _isLabelOp(st.op)) {
                    llmCalls += Math.min(here.rows, _labelCallCap(st.op, st));
                }
            });
        }
    });
    return { crawlRows: crawlRows, llmCalls: llmCalls, unbounded: unbounded };
}

function renderCostSummary() {
    var el = document.getElementById('cost-summary');
    if (!el) return;
    var c = estimateCost();
    if (!Object.keys(canvas.nodes).length) { el.textContent = ''; el.style.display = 'none'; return; }
    var rows = c.unbounded ? I18n.t('diagnostics.costUnbounded') : ('≈' + c.crawlRows);
    el.style.display = '';
    el.textContent = I18n.t('diagnostics.costRows') + ' ' + rows + ' · ' +
        I18n.t('diagnostics.costLlm') + ' ≈' + c.llmCalls;
    el.title = I18n.t('diagnostics.costHint');
}

