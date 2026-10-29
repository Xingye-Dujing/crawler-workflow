/* canvas-auto-layout.js — 自动排布：autoLayout 的拓扑分层与 runAutoLayout 的策略分派

 * Split out of the `canvas` object in `canvas.js` on 2026-10-29. `canvas` stays ONE global (the
 * page's markup and every panel call `canvas.x()` by name), so this file does not declare a second
 * object: it ASSIGNS its members, which is the only way a later script can add methods to a
 * top-level `const`. The member lines are the original bytes, unchanged and un-reindented, wrapped
 * in an `Object.assign` call whose opener sits alone on its own line. index.html loads this right
 * after `canvas.js`, and `tests/frontend/splits.json` lists it as a companion, so a harness naming
 * the canvas receives the section too.
 */
Object.assign(canvas, {
    /* ── Auto-layout: topological ranks sized by the REAL boxes ── */
    autoLayout(options) {
        /* `silent` is for the baseline strategy: it wants the algorithm's placement
           as the fallback for nodes the baseline does not know, then applies the
           saved positions itself and fits the camera ONCE. Suppressing the toast and
           the camera here keeps that one user action from reporting twice. */
        const silent = !!(options && options.silent);
        /* The old fixed 280×120 lattice laid nodes out as if every box were that size.
           .node grows to max-width 340 with content, and .node-content wraps a link list
           into ever more height — so wide/tall nodes bled into the next rank and the one
           below, and the equal-TOPS rule put port centres (each at its own half-height)
           on different lines, which is what bowed the wires. Everything below advances by
           the measured offsetWidth/offsetHeight of the rendered box, and a rank of one
           node sits CENTRED on the shared local line so a plain chain draws flat.
           A folded node measures 32 tall, so fold-awareness comes for free. */
        const SP_X = 120;   // edge-to-edge between neighbouring ranks (a GAP, not a stride)
        const SP_Y = 60;    // gap between stacked nodes inside one rank

        /* Step 1: find connected components (undirected) */
        const nodeIds = Object.keys(this.nodes);
        if (nodeIds.length === 0) return;
        const uadj = {};
        nodeIds.forEach(function (nid) { uadj[nid] = new Set(); });
        this.connections.forEach(function (c) {
            if (uadj[c.from]) uadj[c.from].add(c.to);
            if (uadj[c.to]) uadj[c.to].add(c.from);
        });
        const visited = new Set();
        const components = [];
        nodeIds.forEach(function (nid) {
            if (visited.has(nid)) return;
            const comp = [];
            const queue = [nid];
            visited.add(nid);
            while (queue.length) {
                const cur = queue.shift();
                comp.push(cur);
                uadj[cur].forEach(function (nb) {
                    if (!visited.has(nb)) { visited.add(nb); queue.push(nb); }
                });
            }
            components.push(comp);
        });

        /* Step 2: layout each component independently (stacked vertically).
           The stack ORDER is the user's, not creation order: sort by the component's
           排布顺序 (the smallest integer found on any of its name nodes). Numbered
           components rise to the top, ascending — a LOWER number sits HIGHER, the same
           convention as 阶段序号. A component whose name node left 排布顺序 blank has no
           preference, so it drops below every numbered one and keeps its creation
           order relative to the other blanks: Array.prototype.sort is stable (ES2019),
           so an untouched canvas — nobody ever set the field — lays out byte-identically. */
        const layoutOrderOf = (comp) => {
            let key = null;
            comp.forEach((nid) => {
                const n = this.nodes[nid];
                if (n && n.type === 'name' && n.params) {
                    const raw = n.params.layout_order;
                    if (raw !== '' && raw !== null && raw !== undefined) {
                        const v = parseInt(raw, 10);
                        if (Number.isFinite(v) && (key === null || v < key)) key = v;
                    }
                }
            });
            return key;
        };
        const ordered = components.slice().sort((a, b) => {
            const ka = layoutOrderOf(a);
            const kb = layoutOrderOf(b);
            if (ka === null && kb === null) return 0;
            if (ka === null) return 1;
            if (kb === null) return -1;
            return ka - kb;
        });
        const allPositions = [];
        const compGap = 40;
        let cursorY = 0;

        ordered.forEach(function (comp) {
            const compSet = new Set(comp);
            const compConns = this.connections.filter(function (c) {
                return compSet.has(c.from) && compSet.has(c.to);
            });
            /* Build topology for this component */
            const inDeg = {};
            const adj = {};
            comp.forEach(function (nid) {
                if (!(nid in inDeg)) inDeg[nid] = 0;
                adj[nid] = [];
            });
            compConns.forEach(function (c) {
                adj[c.from] = adj[c.from] || [];
                adj[c.from].push(c.to);
                if (!(c.to in inDeg)) inDeg[c.to] = 0;
                inDeg[c.to]++;
            });
            comp.forEach(function (nid) {
                if (!(nid in inDeg)) inDeg[nid] = 0;
            });
            const levels = [];
            let remaining = new Set(comp);
            while (remaining.size > 0) {
                const current = [];
                remaining.forEach(function (nid) {
                    if (inDeg[nid] === 0) current.push(nid);
                });
                if (current.length === 0) break;
                levels.push(current);
                current.forEach(function (nid) {
                    (adj[nid] || []).forEach(function (nb) { inDeg[nb]--; });
                    remaining.delete(nid);
                });
            }
            if (remaining.size > 0) levels.push(Array.from(remaining));

            /* Measure the boxes once; a node not on screen reports 0 and falls back
               to a mid-size box rather than collapsing the rank against its neighbour. */
            const size = {};
            comp.forEach(function (nid) {
                const el = this._nodeEl(nid);
                size[nid] = { w: (el && el.offsetWidth) || 240, h: (el && el.offsetHeight) || 80 };
            }, this);

            /* Compute node positions for this component: each rank advances by its WIDEST
               measured box, and each rank's stacked block is centred on the shared local
               line 0 (a single-node rank sits exactly on it — equal CENTRES, not tops). */
            const positions = [];
            let rankX = 0;
            levels.forEach(function (level) {
                let blockH = 0;
                level.forEach(function (nid) { blockH += size[nid].h + SP_Y; });
                blockH -= SP_Y;
                let y = -blockH / 2;
                let maxW = 0;
                level.forEach(function (nid) {
                    positions.push({ id: nid, x: rankX, y: y });
                    y += size[nid].h + SP_Y;
                    if (size[nid].w > maxW) maxW = size[nid].w;
                });
                rankX += maxW + SP_X;
            });

            /* Find component's actual top and bottom edges in local coords */
            let compTop = Infinity, compBottom = -Infinity;
            positions.forEach((p) => {
                const el = this._nodeEl(p.id);
                const h = (el && el.offsetHeight) || 80;
                if (p.y < compTop) compTop = p.y;
                if (p.y + h > compBottom) compBottom = p.y + h;
            });

            /* Shift so the top edge aligns with cursorY */
            const shift = cursorY - compTop;

            positions.forEach((p) => {
                const el = this._nodeEl(p.id);
                if (!el) return;
                allPositions.push({ id: p.id, x: p.x, y: p.y + shift });
            });

            cursorY = compBottom + shift + compGap;
        }, this);

        allPositions.forEach((p) => {
            const el = this._nodeEl(p.id);
            if (el) {
                /* Positions land in rank-local coordinates rounded to whole pixels;
                   the camera fit below reads these boxes and pans/zooms so the whole
                   relayout is on screen at once. */
                el.style.left = Math.round(p.x) + 'px';
                el.style.top = Math.round(p.y) + 'px';
            }
        });
        this.scheduleRender();
        this.saveState();
        /* autoLayout is 重新排布 + 适应: after moving the nodes it hands the camera to
           resetView, the same rule the 适应 button uses (measured workspace box, a
           shrink-only zoom, top clearance for the menu bar). Keeping one fit routine
           means a relayout and a 适应 press can never disagree about "everything visible". */
        if (!silent) {
            this.resetView();
            showToast(I18n.t('toast.layoutApplied'));
        }
    },

    /* The 排布 entry point: the chosen strategy decides whether the algorithm or a
       saved layout baseline arranges the canvas. `autoLayout` itself stays the pure
       algorithm (callers and tests of that contract are unchanged). */
    async runAutoLayout() {
        if (typeof LayoutStrategy !== 'undefined' && LayoutStrategy && LayoutStrategy.layout) {
            const handled = await LayoutStrategy.layout();
            if (handled) return;
        }
        this.autoLayout();
    },
});
