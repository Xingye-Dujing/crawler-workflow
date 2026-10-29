/* canvas-view.js — 相机与小地图：pan/zoom/适应、捏合缩放、minimap，以及携带相机的 draft 序列化

 * Split out of the `canvas` object in `canvas.js` on 2026-10-29. `canvas` stays ONE global (the
 * page's markup and every panel call `canvas.x()` by name), so this file does not declare a second
 * object: it ASSIGNS its members, which is the only way a later script can add methods to a
 * top-level `const`. The member lines are the original bytes, unchanged and un-reindented, wrapped
 * in an `Object.assign` call whose opener sits alone on its own line. index.html loads this right
 * after `canvas.js`, and `tests/frontend/splits.json` lists it as a companion, so a harness naming
 * the canvas receives the section too.
 */
Object.assign(canvas, {
    /* ---- Transform ---- */
    updateTransform() {
        /* Round the pan to whole device pixels so the canvas never sits on a
           sub-pixel boundary (which would smear text and edges into a blur). */
        const px = Math.round(this.panX);
        const py = Math.round(this.panY);
        this.container.style.transform = 'translate(' + px + 'px, ' + py + 'px) scale(' + this.zoom + ')';
        this.renderMinimap();
    },

    _paintZoomReadout() {
        const el = document.getElementById('status-zoom');
        if (el) el.textContent = Math.round(this.zoom * 100) + '%';
    },

    _prefersReducedMotion() {
        /* Honour the OS "reduce motion" setting: glide only when the user has not asked
           the system to minimise animation. */
        return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    },

    /* Drop the camera glide: cancel the end timer and remove the CSS transition so the
       next transform change is immediate. Called before a manual gesture (wheel / pan /
       pinch / node drag) and whenever a new glide starts, so the surface never lags the
       state that was already committed. */
    _clearViewAnim() {
        if (this._viewAnim) {
            clearTimeout(this._viewAnim);
            this._viewAnim = null;
        }
        if (this._viewAnimating) {
            if (this.container && this.container.style) this.container.style.transition = '';
            this._viewAnimating = false;
        }
    },

    /* Ease the camera to (tx, ty, tz). The final state is committed SYNCHRONOUSLY — the
       model, the coordinate math and the tests all read the target at once — and only the
       rendered transform glides there from what is on screen, via a CSS transition. `ms`
       overrides the default duration; 0 or a reduced-motion preference snaps instantly. */
    _animateViewTo(tx, ty, tz, ms) {
        this._clearViewAnim();
        this.panX = tx;
        this.panY = ty;
        this.zoom = tz;
        this._paintZoomReadout();
        const duration = ms === undefined ? VIEW_ANIM_MS : ms;
        const el = this.container;
        if (duration <= 0 || this._prefersReducedMotion() || !el || !el.style) {
            this.updateTransform();
            this.scheduleViewSave();
            return;
        }
        /* Set the transition BEFORE the transform changes, so the browser interpolates
           from the currently-painted transform to the new one. */
        el.style.transition = 'transform ' + duration + 'ms ' + VIEW_ANIM_EASE;
        this._viewAnimating = true;
        this.updateTransform();
        this._viewAnim = setTimeout(() => this._clearViewAnim(), duration + 60);
        this.scheduleViewSave();
    },

    /* Screen-space pan by (dx, dy). Used by a two-finger trackpad scroll and by the
       axis of a pinch. The canvas is unbounded, so — like a pointer drag — there is no
       clamp: the surface simply follows the gesture. */
    _panBy(dx, dy) {
        if (!dx && !dy) return;
        this.panX += dx;
        this.panY += dy;
        this.updateTransform();
    },

    /* Zoom by `factor` about the workspace point (mx, my) so that point stays put — the
       anchored feel that keeps a pinch or ctrl-wheel from drifting the view. */
    _zoomAt(mx, my, factor) {
        const oldZoom = this.zoom;
        const newZoom = Math.max(0.2, Math.min(3, oldZoom * factor));
        if (newZoom === oldZoom) return;
        const ratio = newZoom / oldZoom;
        this.panX = mx - (mx - this.panX) * ratio;
        this.panY = my - (my - this.panY) * ratio;
        this.zoom = newZoom;
        this.updateTransform();
        const el = document.getElementById('status-zoom');
        if (el) el.textContent = Math.round(this.zoom * 100) + '%';
    },

    /* Two-finger gesture on the background: slide = pan, spread/close = zoom, both
       anchored at the fingers' midpoint so the content between them holds still. The
       first call only records the base; later calls are RELATIVE to that base, so the
       two fingers' own micro-jitter during a pinch never compounds into a drift. */
    _applyPinch() {
        const pts = Object.values(this._panPointers);
        if (pts.length < 2) return;
        const a = pts[0];
        const b = pts[1];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (!dist) return;
        const midX = (a.x + b.x) / 2;
        const midY = (a.y + b.y) / 2;
        /* The base is captured the moment the second finger lands (pointerdown); a move
           with no base is a can't-happen, so bail rather than invent one mid-gesture. */
        if (!this._pinchBase) return;
        const base = this._pinchBase;
        const targetZoom = Math.max(0.2, Math.min(3, base.zoom * (dist / base.dist)));
        const rect = this.workspace.getBoundingClientRect();
        const cmx = midX - rect.left;
        const cmy = midY - rect.top;
        const baseCmx = base.midX - rect.left;
        const baseCmy = base.midY - rect.top;
        /* Resolve pan and zoom TOGETHER, relative to the base, so the canvas point that
           sat under the fingers at pinch-start stays under their midpoint now — a spread
           that also slides across the surface neither drifts nor compounds one frame's
           rounding into the next. */
        this.panX = cmx - targetZoom * ((baseCmx - base.panX) / base.zoom);
        this.panY = cmy - targetZoom * ((baseCmy - base.panY) / base.zoom);
        this.zoom = targetZoom;
        this.updateTransform();
        const el = document.getElementById('status-zoom');
        if (el) el.textContent = Math.round(this.zoom * 100) + '%';
    },

    zoomIn() {
        this.zoom = Math.min(3, this.zoom * 1.2);
        this.updateTransform();
        document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
        this.scheduleViewSave();
    },

    zoomOut() {
        this.zoom = Math.max(0.2, this.zoom / 1.2);
        this.updateTransform();
        document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
        this.scheduleViewSave();
    },

    resetView() {
        /* 适应: fit EVERY node into the VISIBLE box, not just centre the mean. The
           old behaviour pinned zoom to 100%, so a chain that autoLayout spreads
           past the window left nodes off-screen — '适应' hid them instead of
           revealing them. Zoom only ever shrinks here (max 1), so a graph that
           already fits is re-centred at its own size and no node looms larger
           than the user left it. The box is the workspace's own client rect, NOT
           window.innerWidth: the canvas sits inside the app chrome, so the two
           disagree (measured 1344x670 vs 1920x1080) and fitting to the larger
           number leaves the cluster spilling past the real right/bottom edge.
           The TOP of that box is the menu bar, not the workspace: a pinned/hovered
           #top-menu overlays its height, so the top inset is menu height + margin —
           the cluster sits below the bar and there is more air above it, exactly
           when 100% cannot hold it. */
        const ids = Object.keys(this.nodes);
        const vp = this.workspace || {};
        const vw = vp.clientWidth || window.innerWidth;
        const vh = vp.clientHeight || window.innerHeight;
        const menu = document.getElementById('top-menu');
        const topInset = (menu ? menu.offsetHeight : 0) + VIEW_FIT_MARGIN;
        if (ids.length === 0) {
            this._animateViewTo(0, 0, 1);
            return;
        }
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        ids.forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            minX = Math.min(minX, el.offsetLeft);
            minY = Math.min(minY, el.offsetTop);
            maxX = Math.max(maxX, el.offsetLeft + el.offsetWidth);
            maxY = Math.max(maxY, el.offsetTop + el.offsetHeight);
        });
        const contentW = Math.max(1, maxX - minX);
        const contentH = Math.max(1, maxY - minY);
        const availW = Math.max(1, vw - 2 * VIEW_FIT_MARGIN);
        const availH = Math.max(1, vh - topInset - VIEW_FIT_MARGIN);
        const fit = Math.min(availW / contentW, availH / contentH);
        const tZoom = Math.max(0.2, Math.min(1, fit));
        const cx = (minX + maxX) / 2;
        const cy = (minY + maxY) / 2;
        /* Centre inside the band the menu does NOT cover, not inside the whole
           height — so the top margin is (menu + VIEW_FIT_MARGIN), never 0. */
        const bandCentreY = (topInset + (vh - VIEW_FIT_MARGIN)) / 2;
        this._animateViewTo(vw / 2 - cx * tZoom, bandCentreY - cy * tZoom, tZoom);
    },

    /* Bring ONE node to the centre of the visible box and ZOOM IN enough to read it
       with its neighbours — the outline's jump-to-node. Unlike resetView (适应), which
       fits the WHOLE graph and so shrinks every box to a thumbnail once there are many,
       this frames just the target plus a ring around it: the zoom window is 3× the node's
       own size, so the node lands dead centre and one hop of neighbours stays visible. The
       camera MAY zoom in here (past 100%) — that is the whole point — clamped to [0.5, 1.5]
       so an extreme window can neither bury the node nor blow it into a pixel blob. It
       still borrows resetView's viewport facts (workspace client rect, menu-height top inset, VIEW_FIT_MARGIN). */
    centerOnNode(id) {
        const el = this._nodeEl(id);
        if (!el) return;
        const vp = this.workspace || {};
        const vw = vp.clientWidth || window.innerWidth;
        const vh = vp.clientHeight || window.innerHeight;
        const menu = document.getElementById('top-menu');
        const topInset = (menu ? menu.offsetHeight : 0) + VIEW_FIT_MARGIN;
        const nodeW = el.offsetWidth || 240;
        const nodeH = el.offsetHeight || 80;
        const availW = Math.max(1, vw - 2 * VIEW_FIT_MARGIN);
        const availH = Math.max(1, vh - topInset - VIEW_FIT_MARGIN);
        const fit = Math.min(availW / (nodeW * 3), availH / (nodeH * 3));
        const tZoom = Math.max(0.5, Math.min(1.5, fit));
        const cx = el.offsetLeft + nodeW / 2;
        const cy = el.offsetTop + nodeH / 2;
        const bandCentreY = (topInset + (vh - VIEW_FIT_MARGIN)) / 2;
        this._animateViewTo(vw / 2 - cx * tZoom, bandCentreY - cy * tZoom, tZoom);
    },

    /* ── Minimap: an overview of the whole graph in a corner ── */

    /* The world rectangle every node occupies, sized by each box's own DOM size (the
       same facts resetView fits to). null when there is nothing to draw — an empty
       canvas gets no minimap, not a lone point at the origin. */
    _minimapBounds() {
        const ids = Object.keys(this.nodes);
        if (!ids.length) return null;
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        ids.forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            minX = Math.min(minX, el.offsetLeft);
            minY = Math.min(minY, el.offsetTop);
            maxX = Math.max(maxX, el.offsetLeft + (el.offsetWidth || 240));
            maxY = Math.max(maxY, el.offsetTop + (el.offsetHeight || 80));
        });
        if (!isFinite(minX)) return null;
        return { minX: minX, minY: minY, maxX: maxX, maxY: maxY };
    },

    /* Uniform scale (min of the two axes) that fits the world bounds into the box, so the
       minimap never stretches a node sideways. */
    _minimapScale(bounds, size) {
        const contentW = Math.max(1, bounds.maxX - bounds.minX);
        const contentH = Math.max(1, bounds.maxY - bounds.minY);
        const avail = Math.max(1, size - 2 * MINIMAP_PAD);
        return Math.min(avail / contentW, avail / contentH);
    },

    /* A click at minimap pixels → the world point it stands for (inverse of the draw map). */
    _minimapClickToWorld(mx, my, bounds, scale) {
        return { x: bounds.minX + (mx - MINIMAP_PAD) / scale, y: bounds.minY + (my - MINIMAP_PAD) / scale };
    },

    /* Re-centre the camera on a world point at the CURRENT zoom (kept — a minimap click is a
       pan, not a zoom). Same viewport-box + menu-inset convention as resetView, so the point
        lands in the band the top menu does not cover. */
    _centerWorldPoint(wx, wy) {
        const vp = this.workspace || {};
        const vw = vp.clientWidth || window.innerWidth;
        const vh = vp.clientHeight || window.innerHeight;
        const menu = document.getElementById('top-menu');
        const topInset = (menu ? menu.offsetHeight : 0) + VIEW_FIT_MARGIN;
        const bandCentreY = (topInset + (vh - VIEW_FIT_MARGIN)) / 2;
        this._animateViewTo(vw / 2 - wx * this.zoom, bandCentreY - wy * this.zoom, this.zoom);
    },

    onMinimapClick(e) {
        const bounds = this._minimapBounds();
        if (!bounds) return;
        const scale = this._minimapScale(bounds, MINIMAP_SIZE);
        const rect = (e.currentTarget && e.currentTarget.getBoundingClientRect) ? e.currentTarget.getBoundingClientRect() : { left: 0, top: 0 };
        const world = this._minimapClickToWorld(e.clientX - rect.left, e.clientY - rect.top, bounds, scale);
        this._centerWorldPoint(world.x, world.y);
    },

    /* Draws the minimap as positioned boxes in #minimap's innerHTML: one rectangle per node and
       a viewport frame. Kept in one string (the DOM stub stores innerHTML verbatim, and the real
       browser lays it out) so a harness can count node boxes without measuring drawn geometry. */
    renderMinimap() {
        const box = document.getElementById('minimap');
        if (!box) return;
        const bounds = this._minimapBounds();
        if (!bounds) {
            box.innerHTML = '';
            return;
        }
        const scale = this._minimapScale(bounds, MINIMAP_SIZE);
        const ids = Object.keys(this.nodes);
        const states = this.disableStates();
        let html = '';
        ids.forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            const x = MINIMAP_PAD + (el.offsetLeft - bounds.minX) * scale;
            const y = MINIMAP_PAD + (el.offsetTop - bounds.minY) * scale;
            const w = Math.max(2, (el.offsetWidth || 240) * scale);
            const h = Math.max(2, (el.offsetHeight || 80) * scale);
            const off = states[id] !== 'on';
            html += '<i class="minimap-node' + (off ? ' mm-off' : '') + '" style="left:' + x.toFixed(1) + 'px;top:' + y.toFixed(1) + 'px;width:' + w.toFixed(1) + 'px;height:' + h.toFixed(1) + 'px"></i>';
        });
        // The viewport frame: the world rectangle the canvas currently shows, mapped the same way.
        const vw = (this.workspace && this.workspace.clientWidth) || 1200;
        const vh = (this.workspace && this.workspace.clientHeight) || 700;
        const vLeft = (0 - this.panX) / this.zoom;
        const vTop = (0 - this.panY) / this.zoom;
        const vx = MINIMAP_PAD + (vLeft - bounds.minX) * scale;
        const vy = MINIMAP_PAD + (vTop - bounds.minY) * scale;
        const vwid = Math.max(4, (vw / this.zoom) * scale);
        const vhei = Math.max(4, (vh / this.zoom) * scale);
        html += '<i class="minimap-view" style="left:' + vx.toFixed(1) + 'px;top:' + vy.toFixed(1) + 'px;width:' + vwid.toFixed(1) + 'px;height:' + vhei.toFixed(1) + 'px"></i>';
        box.innerHTML = html;
    },

    /* The camera. It is deliberately NOT inside getState(): that dict is also one
       undo step, and rewinding an accidental node deletion must not also jump the
       viewport somewhere the user never undid. The draft carries it beside the
       model, and a saved file carries it in settings — "this is the view the
       workflow was arranged in". */
    _viewState() {
        return { panX: this.panX, panY: this.panY, zoom: this.zoom };
    },

    _applyView(view) {
        if (!view || typeof view !== 'object') return;
        this._clearViewAnim(); /* a restore/load is a placement, not a glide to animate */
        const parts = [
            ['panX', view.panX, -Infinity, Infinity],
            ['panY', view.panY, -Infinity, Infinity],
            ['zoom', view.zoom, 0.2, 3],
        ];
        parts.forEach(([key, raw, min, max]) => {
            const value = Number(raw);
            if (Number.isFinite(value)) this[key] = Math.max(min, Math.min(max, value));
        });
        this.updateTransform();
        document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
    },

    /* Pan/zoom redraw at most once per gesture-trickle: a wheel flick fires dozens
       of events, and each would otherwise pay a synchronous localStorage write. */
    scheduleViewSave() {
        if (this._viewSaveTimer) return;
        this._viewSaveTimer = setTimeout(() => {
            this._viewSaveTimer = null;
            this.saveState();
        }, 400);
    },

    serializeDraft() {
        return Object.assign(this.getState(), { view: this._viewState() });
    },
});
