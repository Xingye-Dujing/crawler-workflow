/* canvas-visuals.js — 派生状态的绘制：启用/禁用级联、运行徽标、校验描红与节点折叠

 * Split out of the `canvas` object in `canvas.js` on 2026-10-29. `canvas` stays ONE global (the
 * page's markup and every panel call `canvas.x()` by name), so this file does not declare a second
 * object: it ASSIGNS its members, which is the only way a later script can add methods to a
 * top-level `const`. The member lines are the original bytes, unchanged and un-reindented, wrapped
 * in an `Object.assign` call whose opener sits alone on its own line. index.html loads this right
 * after `canvas.js`, and `tests/frontend/splits.json` lists it as a companion, so a harness naming
 * the canvas receives the section too.
 */
Object.assign(canvas, {
    /* ── Enable / disable ── */
    /* A canvas-local mirror of the backend's effective graph, used ONLY for grey-out and for
       naming the run; it must agree with engine.workflow.effective_workflow, because the record
       the browser looks up is keyed by that same effective name. A node is OFF if its own switch
       or its type is switched off; it is STARVED if it is on but has at least one upstream and
       none of those upstreams are alive. Starvation cascades, so switching off a workflow's head
       node greys the whole chain — which is exactly why there is no separate "disable workflow"
       control: it is just disabling the first box. */
    _nodeDirectlyOn(id) {
        const n = this.nodes[id];
        if (!n) return false;
        return (n.params || {}).enabled !== false;
    },

    _typeOn(type) {
        return (this.disabledTypes || []).indexOf(type) < 0;
    },

    /* { id: 'on' | 'off' | 'starved' } for every node on the canvas. */
    disableStates() {
        const ids = Object.keys(this.nodes);
        const upstream = {};
        ids.forEach((id) => { upstream[id] = []; });
        this.connections.forEach((c) => {
            if (this.nodes[c.from] && this.nodes[c.to] && upstream[c.to]) upstream[c.to].push(c.from);
        });
        const alive = {};
        ids.forEach((id) => { alive[id] = this._nodeDirectlyOn(id) && this._typeOn(this.nodes[id].type); });
        let changed = true;
        while (changed) {
            changed = false;
            ids.forEach((id) => {
                if (!alive[id]) return;
                const parents = upstream[id];
                if (parents.length && !parents.some((p) => alive[p])) { alive[id] = false; changed = true; }
            });
        }
        const states = {};
        ids.forEach((id) => {
            if (!alive[id]) {
                states[id] = this._nodeDirectlyOn(id) && this._typeOn(this.nodes[id].type) ? 'starved' : 'off';
            } else {
                states[id] = 'on';
            }
        });
        return states;
    },

    /* The ids that take part in a run — the same set the backend computes. */
    effectiveIds() {
        const states = this.disableStates();
        return Object.keys(states).filter((id) => states[id] === 'on');
    },

    toggleEnabled(id) {
        const n = this.nodes[id];
        if (!n) return;
        n.params = n.params || {};
        n.params.enabled = n.params.enabled === false;
        this.saveState();
        this.scheduleRender();
        if (this._settingsNodeId === id) openSettings(id);
    },

    /* Switch a whole node type off (and back on). Off = every box of this kind is out of the run
       and the type cannot be added again from the new-node menu; on = each node returns to its OWN
       switch, because the type toggle never edits params.enabled. */
    toggleTypeDisabled(type) {
        const list = this.disabledTypes || (this.disabledTypes = []);
        const i = list.indexOf(type);
        if (i >= 0) list.splice(i, 1);
        else list.push(type);
        this.saveState();
        this.scheduleRender();
    },

    applyDisabledVisuals() {
        const states = this.disableStates();
        Object.keys(this.nodes).forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            const state = states[id];
            el.classList.toggle('node-off', state === 'off');
            el.classList.toggle('node-starved', state === 'starved');
            const btn = el.querySelector('.node-power-btn');
            if (btn) {
                const on = state === 'on';
                btn.classList.toggle('power-off', !on);
                btn.title = I18n.t(on ? 'ctx.disableNode' : 'ctx.enableNode');
            }
            const badge = el.querySelector('.node-state-badge');
            if (badge) {
                badge.textContent = state === 'off'
                    ? I18n.t('node.badgeDisabled')
                    : state === 'starved'
                        ? I18n.t('node.badgeNoInput')
                        : '';
                badge.style.display = state === 'on' ? 'none' : '';
            }
        });
    },

    /* Paint the loaded run's per-node verdicts on the boxes themselves.

       The three shapes are one vocabulary, not three separate ornaments: a green
       check means the run really finished with rows in hand (``done`` and
       ``restored`` are both settled), a yellow spinner means THIS node is running
       right now, and a red X means it did not finish successfully (failed, partial,
       skipped, or a status this build does not know — never paint an unknown word
       green). The map comes from the run ledger, keyed by node id, so parallel
       execution just means several entries say ``running`` at once.

       A node absent from the map carries no badge: "never reached in this run" is
       not the same claim as "failed", and a grey mark on every untouched chart
       would read as one. */
    _paintRunBadge(badge, status, rows) {
        if (!badge) return;
        if (!status) {
            badge.className = 'node-run-badge';
            badge.innerHTML = '';
            badge.style.display = 'none';
            badge.title = '';
            badge.setAttribute('aria-label', '');
            badge.dataset.status = '';
            badge.dataset.signature = '';
            return;
        }
        const settled = status === 'done' || status === 'restored';
        const running = status === 'running';
        const kind = settled ? 'run-done' : running ? 'run-running' : 'run-failed';
        /* The status poll runs once a second; an unchanged node must not rewrite
           its SVG every tick. The signature includes the localized title, so a
           language switch (same status) still repaints the tooltip. */
        const known = ['pending', 'running', 'done', 'partial', 'failed', 'skipped', 'restored'];
        const word = known.indexOf(status) >= 0 ? I18n.t('runsMgr.node.' + status) : status;
        const title = I18n.t('runsMgr.runStatus').replace('{status}', word) +
            (rows > 0 ? ' · ' + rows + ' ' + I18n.t('runsMgr.colRows') : '');
        const signature = kind + '|' + status + '|' + rows + '|' + title;
        if (badge.dataset.signature === signature) {
            badge.style.display = 'flex';
            return;
        }
        badge.className = 'node-run-badge ' + kind;
        badge.dataset.status = status;
        badge.dataset.signature = signature;
        if (running) {
            badge.innerHTML = '<span class="node-run-spinner"></span>';
        } else if (settled) {
            badge.innerHTML =
                '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 8.4l3.1 3.1 6.5-7"/></svg>';
        } else {
            badge.innerHTML =
                '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.2 4.2l7.6 7.6M11.8 4.2l-7.6 7.6"/></svg>';
        }
        /* The status word is the record's, localized; an unrecognised one shows
           itself (the i18n reader echoes an unknown key) rather than borrowing
           a friendlier verdict. Rows are only appended when the record has them. */
        badge.title = title;
        badge.setAttribute('aria-label', title);
        badge.style.display = 'flex';
    },

    applyRunStatuses(statuses) {
        const map = statuses || {};
        Object.keys(this.nodes).forEach((id) => {
            const el = this._nodeEl(id);
            const badge = el && el.querySelector('.node-run-badge');
            if (!badge) return;
            const info = map[id];
            this._paintRunBadge(badge, String((info && info.status) || ''), Number((info && info.row_count) || 0));
        });
        /* A reusable node has no row of its own in the run graph: its internals run
           under expanded ids, and the group badge is their aggregate. One hook keeps
           the collapsed verdict and the expanded inside view in step with the poll. */
        if (typeof ReusableNodes !== 'undefined' && ReusableNodes.paintStatuses) {
            try {
                ReusableNodes.paintStatuses(map);
            } catch (e) {
                console.error('reusable status paint failed', e);
            }
        }
    },

    /* Paint the edit-time diagnostics: a count badge + a red frame on every node that
       has a problem, its `title` listing the reasons, and a click that selects and
       scrolls to the node (so a badge on an off-screen box is actionable). Fed by
       Diagnostics.recompute — the canvas holds no opinion about what is wrong, it only
       draws what it is told. */
    _applyValidationVisuals(perNode) {
        const map = perNode || {};
        Object.keys(this.nodes).forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            const problems = map[id] || [];
            const invalid = problems.length > 0;
            el.classList.toggle('node-invalid', invalid);
            const badge = el.querySelector('.node-validate-badge');
            if (!badge) return;
            badge.style.display = invalid ? '' : 'none';
            badge.textContent = invalid ? String(problems.length) : '';
            badge.title = invalid ? problems.join('\n') : '';
            badge.onclick = (function (self, nid) {
                return function (ev) {
                    if (ev) ev.stopPropagation();
                    self.selectNode(nid);
                    self._ensureNodeVisible(nid);
                };
            })(this, id);
        });
    },

    /* ── Node fold / unfold ── */
    /* Shared with restoreState: a fold is two style writes plus a class, and a
       second copy would drift the moment one of the three changed. */
    _setFolded(id, folded) {
        const el = this._nodeEl(id);
        if (!el) return false;
        el.classList.toggle('node-folded', !!folded);
        const content = el.querySelector('.node-content');
        const actions = el.querySelector('.node-actions');
        if (content) content.style.display = folded ? 'none' : '';
        if (actions) actions.style.display = folded ? 'none' : '';
        return true;
    },

    toggleFold(id) {
        const el = this._nodeEl(id);
        if (!el) return;
        const folded = !el.classList.contains('node-folded');
        if (!this._setFolded(id, folded)) return;
        this.scheduleRender();
        this.saveState();
    },
});
