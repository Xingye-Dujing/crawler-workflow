/* floating-panels.js — panels as windows: drag, resize, console pop-out, dock height, click-away close
 *
 * Split out of `app.js` on 2026-10-29 as its own banner sections, so every name here is still a
 * page global and inline `onclick="…"` handlers keep calling it by name. index.html loads it right
 * after `app.js`; `tests/frontend/splits.json` declares it a companion of that file, so a harness
 * naming one receives both.
 */
/* ── Panel Drag & Resize Utilities ── */

const _DS = {}; // shared drag state

function makeDraggable(el, handleSelector) {
    const handle = typeof handleSelector === 'string'
        ? el.querySelector(handleSelector) : handleSelector;
    if (!handle) return;
    /* Pointer events, not mouse: one code path serves mouse, touch and pen. touch-action:none
       stops the browser claiming a finger drag as a page scroll before we see a pointermove. */
    handle.style.touchAction = 'none';

    handle.addEventListener('pointerdown', (e) => {
        if (e.target.closest('button, select, input, textarea')) return;
        e.preventDefault();

        /* Convert to floating FIRST (while transform is still readable)
           THEN add panel-dragging to freeze inline styles */
        convertToFloating(el);
        el.classList.add('panel-dragging');

        const rect = el.getBoundingClientRect();
        _DS.el = el;
        _DS.offX = e.clientX - rect.left;
        _DS.offY = e.clientY - rect.top;
        _DS.isDragging = true;
        _DS.handle = handle;
        handle.style.cursor = 'grabbing';
    });
}

document.addEventListener('pointermove', (e) => {
    if (!_DS.isDragging || !_DS.el) return;
    _DS.el.style.setProperty('left', (e.clientX - _DS.offX) + 'px', 'important');
    _DS.el.style.setProperty('top', (e.clientY - _DS.offY) + 'px', 'important');
});

document.addEventListener('pointerup', () => {
    if (_DS.isDragging && _DS.el) {
        _DS.el.classList.remove('panel-dragging');
        if (_DS.handle) _DS.handle.style.cursor = '';
    }
    _DS.isDragging = false;
    _DS.el = null;
    _DS.handle = null;
});

function convertToFloating(el) {
    /* Use getComputedStyle to detect positioning from CSS classes
       (el.style only sees inline styles, not class-based rules) */
    const cs = getComputedStyle(el);
    const hasRight = cs.right && cs.right !== 'auto' && parseFloat(cs.right) !== 0;
    const hasTransform = cs.transform && cs.transform !== 'none';

    if (hasRight || hasTransform) {
        const rect = el.getBoundingClientRect();
        el.style.setProperty('left', rect.left + 'px', 'important');
        el.style.setProperty('top', rect.top + 'px', 'important');
        el.style.right = 'auto';
        el.style.setProperty('transform', 'none', 'important');
    }
}

function makeResizable(el, opts) {
    opts = opts || {};
    const minW = opts.minW || 250;
    const minH = opts.minH || 120;
    const maxW = opts.maxW || window.innerWidth - 40;
    const maxH = opts.maxH || window.innerHeight - 40;
    const onResize = opts.onResize;

    let handle = el.querySelector('.resize-handle');
    if (!handle) {
        handle = document.createElement('div');
        handle.className = 'resize-handle';
        el.appendChild(handle);
    }

    /* A scrollable panel carries its absolutely-positioned handle away with the content:
       ``bottom: 0`` is the padding box's bottom, so scrolling up by N moves the grip up by N
       and past the frame it disappears. Cancelling the scroll keeps it in the visible corner
       (measured on #node-settings, whose form outgrows the panel). */
    const pinHandle = function () {
        handle.style.transform = 'translate(' + el.scrollLeft + 'px,' + el.scrollTop + 'px)';
    };
    if (!el.dataset._handlePinned) {
        el.dataset._handlePinned = '1';
        el.addEventListener('scroll', pinHandle, { passive: true });
        window.addEventListener('resize', pinHandle);
    }
    pinHandle();

    let rs = {};
    handle.style.touchAction = 'none'; /* a finger drag on the handle is ours, not the page's scroll */
    handle.addEventListener('pointerdown', (e) => {
        e.stopPropagation();
        e.preventDefault();
        convertToFloating(el);
        rs.el = el;
        rs.startX = e.clientX;
        rs.startY = e.clientY;
        rs.startW = el.offsetWidth;
        rs.startH = el.offsetHeight;
        rs.minW = minW; rs.minH = minH; rs.maxW = maxW; rs.maxH = maxH;
        window._rs = rs;
        rs.active = true;
    });

    /* One shared pointermove/pointerup for every resizable — mouse, touch and pen alike. */
    if (!window._resizeInit) {
        window._resizeInit = true;
        document.addEventListener('pointermove', (e) => {
            const r = window._rs;
            if (!r || !r.active) return;
            const newW = Math.max(r.minW, Math.min(r.maxW, r.startW + (e.clientX - r.startX)));
            const newH = Math.max(r.minH, Math.min(r.maxH, r.startH + (e.clientY - r.startY)));
            r.el.style.setProperty('width', newW + 'px', 'important');
            r.el.style.setProperty('height', newH + 'px', 'important');
            if (r.onResize) r.onResize(newW, newH);
        });
        document.addEventListener('pointerup', () => {
            const r = window._rs;
            if (r) r.active = false;
        });
    }
    rs.onResize = onResize;
    window._rs = rs;
}

/* ── Console pop-out / dock ── */

function toggleConsolePopout() {
    const panel = document.getElementById('console-panel');
    const btn = document.getElementById('btn-console-popout');
    const wasOpen = panel.classList.contains('open');

    if (panel.classList.contains('popout')) {
        /* Dock back */
        panel.classList.remove('popout');
        panel.classList.remove('panel-dragging');
        panel.style.left = '';
        panel.style.top = '';
        panel.style.width = '';
        panel.style.height = '';
        panel.style.transform = '';
        btn.textContent = I18n.t('console.popout');
        /* Restore open state */
        if (wasOpen) panel.classList.add('open');
    } else {
        /* Pop out: ensure open, then switch to floating */
        panel.classList.add('open');
        panel.classList.add('popout');
        /* Remove the docked bottom position, let CSS take over */
        btn.textContent = I18n.t('console.dock');
        /* Make draggable + resizable on first pop */
        if (!panel.dataset._popInit) {
            panel.dataset._popInit = '1';
            makeDraggable(panel, '.console-header');
            makeResizable(panel, { minW: 350, minH: 150, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
        }
        /* Add resize handle if not present */
        if (!panel.querySelector('.resize-handle')) {
            const rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }
    I18n.apply();
}

/* ── Console height resize (dock mode) ── */

(function initConsoleResize() {
    const handle = document.getElementById('console-resize-handle');
    if (!handle) return;
    let cs = {};

    handle.style.touchAction = 'none';
    handle.addEventListener('pointerdown', (e) => {
        const panel = document.getElementById('console-panel');
        if (panel.classList.contains('popout')) return;
        e.preventDefault();
        cs.panel = panel;
        cs.startY = e.clientY;
        cs.startH = panel.offsetHeight;
        cs.active = true;
        handle.classList.add('active');
    });

    document.addEventListener('pointermove', (e) => {
        if (!cs.active) return;
        const newH = Math.max(80, Math.min(window.innerHeight - 100, cs.startH + (cs.startY - e.clientY)));
        cs.panel.style.height = newH + 'px';
        cs.panel.classList.add('open'); /* keep open while resizing */
    });

    document.addEventListener('pointerup', () => {
        if (cs.active) {
            cs.active = false;
            handle.classList.remove('active');
        }
    });
})();

/* ─── Docked panel height resize ────────────────────────────────
   Four panels share this behaviour, so one function drives all of them.
   Measured from mousedown (not from a stored value) because each panel can be
   resized again after a drag, and the second drag has to start from where the
   first left off. */
function initDockResize(handleId, panelId) {
    const handle = document.getElementById(handleId);
    if (!handle) return;
    let cs = {};

    handle.style.touchAction = 'none';
    handle.addEventListener('pointerdown', (e) => {
        const panel = document.getElementById(panelId);
        if (!panel || !panel.classList.contains('open')) return;
        e.preventDefault();
        cs.panel = panel;
        cs.startY = e.clientY;
        cs.startH = panel.offsetHeight;
        cs.active = true;
        handle.classList.add('active');
    });

    document.addEventListener('pointermove', (e) => {
        if (!cs.active) return;
        const newH = Math.max(80, Math.min(window.innerHeight - 100, cs.startH + (cs.startY - e.clientY)));
        cs.panel.style.height = newH + 'px';
        cs.panel.classList.add('open'); /* keep open while resizing */
    });

    document.addEventListener('pointerup', () => {
        if (cs.active) {
            cs.active = false;
            handle.classList.remove('active');
        }
    });
}

initDockResize('runs-resize-handle', 'runs-panel');
initDockResize('exports-resize-handle', 'exports-panel');
initDockResize('dataset-resize-handle', 'dataset-panel');
initDockResize('workflows-resize-handle', 'workflows-panel');
/* The saved-logins dock is a dock like these: same bottom slot, same one-handle-to-resize,
   and ``closeDockedPanels`` already lists it, so opening it shuts the other five. */
initDockResize('cookies-resize-handle', 'cookies-panel');
/* The scheduled-task dock is a dock like these: same bottom slot, same one-handle-to-resize,
   and ``closeDockedPanels`` lists it, so opening it shuts the other six. */
initDockResize('schedules-resize-handle', 'schedules-panel');
/* The lexicon dock carries the same handle markup but was never given a handler, so the bar
   dragged with no effect — the eighth dock wired exactly like the other seven. */
initDockResize('lexicon-resize-handle', 'lexicon-panel');
/* The bibliometrics workspace is the ninth dock in the same slot, with the same handle. */
initDockResize('biblio-resize-handle', 'biblio-panel');

/* ── Cookie dialog: close on outside click ──
   The platform dropdown is a CustomSelect: its menu is rendered into <body>,
   OUTSIDE the dialog's DOM. Clicking a row there must count as an interaction
   with the dialog, not as an outside click — same two guards as the
   node-settings panel below. */

document.addEventListener('mousedown', (e) => {
    const dialog = document.getElementById('cookie-dialog');
    if (!dialog.classList.contains('open')) return;
    if (e.target.closest('#cookie-dialog')) return;
    if (e.target.closest('[data-i18n="btn.cookies"]')) return;
    /* A dropdown row belongs to the dialog's own control — never "outside". */
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    if (window.CustomSelect && CustomSelect.ownsPopup(e.target, dialog)) return;
    closeCookieDialog();
});

/* Close node-settings on outside click.
   Several things must not count as "outside" even though they live outside the
   panel's own DOM — otherwise the editor closes on the user mid-edit:
   · the node this panel edits (header, body, ports);
   · that node's right-click submenu, and the full-screen layers the panel can
     launch (chart studio, data preview);
   · a control's own popup (dropdown rows, suggestion candidates), which
     custom-select renders into <body> rather than into the panel. */
document.addEventListener('mousedown', (e) => {
    const panel = document.getElementById('node-settings');
    if (!panel.classList.contains('open')) return;
    if (e.target.closest('#node-settings')) return;
    if (e.target.closest('.node-action-btn, [data-action="ctxEdit"]')) return;
    /* A dropdown row is always an interaction with a control, never an "outside"
       click. The studio's picker renders its rows into <body>, so the overlay
       test below cannot see them — and without this the panel would close
       underneath while the user ticks sources in the studio. */
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    const nodeId = canvas._settingsNodeId;
    if (nodeId && e.target.closest('#' + nodeId)) return;
    if (nodeId && e.target.closest('#context-menu') && canvas._contextNode === nodeId) return;
    if (e.target.closest('#studio-overlay, #data-preview-panel')) return;
    if (window.CustomSelect && CustomSelect.ownsPopup(e.target, panel)) return;
    closeSettings();
});

/* Close the dashboard (看板) and Execution History (执行历史) popups on an
   outside click. They are floating windows, not modal overlays — while one
   is open the canvas stays usable, so the user expects it to be gone once
   they click back into the workspace. What must NOT count as "outside":
   · either panel itself (headers, drag/resize handles — and working with
     one popup may never discard the other; they are sized to sit side by side);
   · CustomSelect option menus — the panel's own <select>s render their menus
     into <body>, so a click there is an inside choice, not a click-away;
   · the modal dialogs (generic confirm, cookie capture) — the history panel's
     own button can raise one, and discarding the panel underneath while the
     answer is pending would strand the dialog over an empty canvas. */
document.addEventListener('mousedown', (e) => {
    if (!e.target || !e.target.closest) return;
    /* A click inside the board popup itself, the sibling history popup, or any overlay
       the user legitimately stacks on top of the board — the fullscreen chart, the data
       preview panel, the chart studio — must not dismiss the board. Those are top-level
       siblings, not children of #dashboard-panel, so without this list every click in one
       of them read as "outside" and the board vanished. (#node-settings stays OUTSIDE on
       purpose: opening a node's settings is meant to close the board.) */
    if (
        e.target.closest('#dashboard-panel, #history-panel, #chart-fullscreen-panel, #data-preview-panel, #studio-overlay')
    )
        return;
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    if (e.target.closest('#dialog-overlay, #cookie-dialog')) return;
    ['dashboard-panel', 'history-panel'].forEach((id) => {
        const panel = document.getElementById(id);
        if (!panel || !panel.classList.contains('open')) return;
        if (window.CustomSelect && CustomSelect.ownsPopup(e.target, panel)) return;
        panel.classList.remove('open');
    });
});

/* ── Init draggable panels on first open ── */

/* Patch openCookieDialog to init drag+resize on first open */
const _origOpenCookie = window.openCookieDialog;
window.openCookieDialog = function (...args) {
    /* EVERY argument is forwarded, as a list, on purpose. This wrapper exists to hang
       drag/resize off the first open, and it used to declare `function (platform)` and call
       `_origOpenCookie(platform)` — which silently dropped the SECOND argument the day the
       account landed there: the pre-run block and the saved-logins row both ask for
       「this platform, this account」, and in a browser the wrapper is the function they get.
       Measured in real Chrome (tests/integration/test_ui_layout.py): the panel opened on the
       right platform and the account box stayed on whatever the user had typed, so 「打开」
       looked half-dead. Restating the parameter list is exactly how this breaks again, so
       the list is passed through untouched. */
    _origOpenCookie(...args);
    const dialog = document.getElementById('cookie-dialog');
    if (dialog.classList.contains('open') && !dialog.dataset._uiInit) {
        dialog.dataset._uiInit = '1';
        makeDraggable(dialog, '.settings-header');
        /* Viewport-relative bounds, not fixed pixels: this dialog carries six
           platforms' worth of translated guidance plus two textareas, so a
           maxH of 500 clipped it to about a third of its content and the
           remainder could not be reached at any window size. */
        makeResizable(dialog, {
            minW: 320,
            minH: 260,
            maxW: Math.min(760, window.innerWidth - 40),
            maxH: window.innerHeight - 40,
        });
    }
};

/* Patch openSettings to init drag+resize on first open */
const _origOpenSettings = window.openSettings;
window.openSettings = function (nodeId) {
    var panel = document.getElementById('node-settings');
    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.settings-header');
        /* Same reasoning as the cookie dialog: the node panel grows with the node
           (a source node in comments mode, an analysis op with five fields), and a
           fixed 800px ceiling left fields unreachable on a tall window. */
        makeResizable(panel, {
            minW: 300,
            minH: 240,
            maxW: Math.min(680, window.innerWidth - 40),
            maxH: window.innerHeight - 40,
        });
    }
    _origOpenSettings(nodeId);
};

/* Init processes panel drag+resize */
(function initProcessesPanel() {
    const origToggle = window.toggleProcessesPanel;
    window.toggleProcessesPanel = function () {
        origToggle();
        var panel = document.getElementById('processes-panel');
        if (panel.classList.contains('open') && !panel.dataset._uiInit) {
            panel.dataset._uiInit = '1';
            makeDraggable(panel, '.console-header');
            makeResizable(panel, { minW: 300, minH: 150, maxW: 800, maxH: 500 });
        }
    };
})();
