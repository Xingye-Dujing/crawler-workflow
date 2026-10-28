/* Auto-layout strategy for the Style menu, split out of workflow.js. */

/* ── Auto-layout strategy (Style menu) ──────────────────────────
   The Layout button has two answers: the topological algorithm, or the positions
   from a canvas snapshot the user designated as this workflow's baseline. The
   baseline is per SAVED workflow (its file stem), stored server-side, because "where
   this canvas belongs" is part of the canvas's state — not a global preference.
   Nodes the snapshot does not know keep the algorithm's placement, so a later-added
   node is still laid out instead of staying on top of an old one. */
var LayoutStrategy = {
    _layout: null,
    _snapshot: null,

    current() {
        return this._layout || {};
    },

    reset() {
        this._layout = null;
        this._snapshot = null;
    },

    _workflowName() {
        return (typeof workflow !== 'undefined' && workflow.currentFile) || '';
    },

    async refresh() {
        var name = this._workflowName();
        if (!name) {
            this._layout = { workflow_name: '', strategy: 'algorithm', snapshot: null, baseline_missing: false };
            this._paint();
            return this._layout;
        }
        var result = await fetchJSON('/api/workflow/history/layout?workflow=' + encodeURIComponent(name));
        if (result && result.ok && result.layout) {
            this._layout = result.layout;
        } else if (!this._layout || this._layout.workflow_name !== name) {
            /* A read failure leaves the select on the algorithm, which is the strategy
               that always works. It must not claim a baseline it could not read. */
            this._layout = { workflow_name: name, strategy: 'algorithm', snapshot: null, baseline_missing: false };
        }
        this._paint();
        return this._layout;
    },

    _paint() {
        var layout = this._layout || { workflow_name: '', strategy: 'algorithm', snapshot: null, baseline_missing: false };
        var select = document.getElementById('layout-strategy');
        if (select) select.value = layout.strategy === 'baseline' ? 'baseline' : 'algorithm';
        /* The style menu's select is themed by CustomSelect: setting the native value
           updates the control but not the visible trigger, so the menu would say
           「算法排布」 while the saved strategy is 「按历史基准」. */
        if (typeof CustomSelect !== 'undefined' && CustomSelect.refreshAll) CustomSelect.refreshAll();
        var hint = document.getElementById('layout-baseline-hint');
        if (!hint) return;
        hint.classList.toggle('missing', !!layout.baseline_missing);
        if (layout.baseline_missing) {
            hint.textContent = I18n.t('style.layoutBaselineMissing');
            hint.title = I18n.t('style.layoutBaselineMissing');
        } else if (layout.snapshot) {
            var label = String(layout.snapshot.label || '') || I18n.t('wfHistory.untitled');
            hint.textContent = label + (wfFiles._when(layout.snapshot.created_at) ? ' · ' + wfFiles._when(layout.snapshot.created_at) : '');
            hint.title = label;
        } else {
            hint.textContent = this._workflowName() ? I18n.t('style.layoutBaselineNone') : I18n.t('wfHistory.needSaved');
            hint.title = '';
        }
    },

    async setStrategy(strategy) {
        var name = this._workflowName();
        if (!name) {
            showToast(I18n.t('wfHistory.needSaved'));
            this._paint();
            return;
        }
        var wanted = strategy === 'baseline' ? 'baseline' : 'algorithm';
        var snapshotId = (this._layout && this._layout.snapshot && this._layout.snapshot.id) || '';
        if (wanted === 'baseline' && !snapshotId) {
            showToast(I18n.t('wfHistory.noBaseline'));
            this._paint();
            return;
        }
        var result = await fetchJSON('/api/workflow/history/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ workflow_name: name, strategy: wanted, snapshot_id: snapshotId }),
        });
        if (result && result.ok) {
            this._layout = result.layout;
            this._paint();
            if (wanted === 'baseline') showToast(I18n.t('wfHistory.baselineSet'));
        } else {
            showToast((result && result.error) || I18n.t('wfHistory.baselineFailed'));
            this._paint();
        }
    },

    async setBaseline(snapshotId) {
        var name = this._workflowName();
        if (!name) {
            showToast(I18n.t('wfHistory.needSaved'));
            return;
        }
        var result = await fetchJSON('/api/workflow/history/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ workflow_name: name, strategy: 'baseline', snapshot_id: snapshotId }),
        });
        if (result && result.ok) {
            this._layout = result.layout;
            this._snapshot = null;
            this._paint();
            showToast(I18n.t('wfHistory.baselineSet'));
        } else {
            showToast((result && result.error) || I18n.t('wfHistory.baselineFailed'));
        }
    },

    /* Returns true when this strategy owned the action (arranged, or refused by name);
       false lets the caller run the ordinary algorithm. */
    async layout() {
        var name = this._workflowName();
        if (!name) return false;
        if (!this._layout || this._layout.workflow_name !== name) await this.refresh();
        var layout = this._layout || {};
        if (layout.strategy !== 'baseline') return false;
        if (layout.baseline_missing || !layout.snapshot) {
            showToast(I18n.t(layout.baseline_missing ? 'style.layoutBaselineMissing' : 'wfHistory.noBaseline'));
            return true;
        }
        if (!this._snapshot || this._snapshot.id !== layout.snapshot.id) {
            var result = await fetchJSON('/api/workflow/history/get?id=' + encodeURIComponent(layout.snapshot.id));
            if (!result || !result.ok || !result.snapshot) {
                showToast((result && result.error) || I18n.t('wfHistory.baselineFailed'));
                return true;
            }
            this._snapshot = result.snapshot;
        }
        var saved = {};
        ((this._snapshot.workflow && this._snapshot.workflow.nodes) || []).forEach(function (node) {
            if (node && node.id !== undefined && node.id !== null) saved[String(node.id)] = node;
        });
        canvas.batchHistory(function () {
            /* Algorithm first, so nodes the baseline never saw get a real place; then
               the saved positions replace it for the nodes it knows. */
            canvas.autoLayout({ silent: true });
            Object.keys(canvas.nodes).forEach(function (id) {
                var node = saved[String(id)];
                var el = canvas._nodeEl(id);
                if (!node || !el) return;
                var x = Number(node.x);
                var y = Number(node.y);
                if (!Number.isFinite(x) || !Number.isFinite(y)) return;
                el.style.left = Math.round(x) + 'px';
                el.style.top = Math.round(y) + 'px';
            });
            canvas.scheduleRender();
        });
        canvas.resetView();
        showToast(I18n.t('toast.layoutApplied'));
        return true;
    },
};

