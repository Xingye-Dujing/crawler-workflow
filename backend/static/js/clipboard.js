/* clipboard.js — the copy-history drawer and the keyboard-shortcut help overlay.

 * Moved out of `canvas.js` on 2026-10-29 (the file's last two top-level names, byte-for-byte):
 * `canvas.js` is the graph object, and this is a persisted side-list of what was copied plus a
 * help box — neither is a canvas method. Every name here is still a page global because
 * `index.html` calls `toggleClipboardDrawer()` / `Clipboard.addText()` from its own markup, and
 * `tests/frontend/splits.json` lists this file as a companion of `canvas.js` so a harness that
 * names the canvas receives the drawer too.
 */
/* ── Clipboard drawer: a persisted, fine-grained history of what was copied ──
   The working slots `canvas._clipboardData`/`canvas._clipboardNodes` stay exactly as
   they were — last copy wins, in memory only, so Ctrl+C/V and the context menu keep
   their behaviour untouched. The drawer is an ADDITIVE second thing: every copy also
   appends one entry to a persisted list under its own localStorage key, and the user
   can paste, rename, pin, delete or clear any single entry. It is deliberately NOT
   part of getState()/the draft: copied content is view state, and mixing it into the
   model would make an unrelated paste an undo step of the graph's saved file.
   Paste funnels through the SAME `canvas._pasteAt` the keyboard/menu already use — a
   second paste implementation is exactly the drift this repo keeps paying for. */
const CLIPBOARD_MAX = 50;

const Clipboard = {
    items: [],
    _seq: 0,
    _query: '',

    /* localStorage keys are separate from the canvas draft on purpose: an item the
       user copied must survive a reload yet never leak into the workflow file. */
    load() {
        this.items = [];
        let raw = null;
        try {
            raw = localStorage.getItem('crawler_clipboard');
        } catch (e) {
            return;
        }
        if (!raw) return;
        try {
            const parsed = JSON.parse(raw);
            if (parsed && Array.isArray(parsed.items)) {
                this.items = parsed.items.filter((it) => it && typeof it === 'object' && it.kind);
            }
        } catch (e) { /* a corrupt clipboard is an empty clipboard, not a crash on load */ }
    },

    save() {
        try {
            localStorage.setItem('crawler_clipboard', JSON.stringify({ items: this.items }));
        } catch (e) { /* quota/serialization can never take down a copy */ }
    },

    reset() {
        this.items = [];
        this._seq = 0;
        this._query = '';
    },

    /* Another tab wrote the same key; this tab's in-memory items are now stale. A storage
       event fires only in the OTHER tabs (never the one that called setItem), so reloading
       from localStorage here is exactly the cross-tab pull — no echo, no loop. */
    onStorageEvent(e) {
        if (!e || e.key !== 'crawler_clipboard') return;
        this.load();
        this.render();
    },

    /* A copy is a silent add: the node/nodes path already fires its own toast, so a
       second one would overwrite the copy toast every existing test asserts. */
    add(entry) {
        const rec = {
            id: 'clip-' + Date.now().toString(36) + '-' + (this._seq++),
            kind: entry.kind,
            payload: JSON.parse(JSON.stringify(entry.payload)),
            label: entry.label || this._defaultLabel(entry.kind, entry.payload),
            pinned: false,
            ts: Date.now(),
        };
        this.items.push(rec);
        if (this.items.length > CLIPBOARD_MAX) this._evict();
        this.save();
        this.render();
        return rec.id;
    },

    /* Drop the single oldest UNPINNED entry; a board of only pinned entries is allowed
       to sit one over the cap rather than silently evict something the user kept. */
    _evict() {
        let oldest = -1;
        for (let i = 0; i < this.items.length; i++) {
            if (!this.items[i].pinned && (oldest < 0 || this.items[i].ts < this.items[oldest].ts)) oldest = i;
        }
        if (oldest >= 0) this.items.splice(oldest, 1);
    },

    _defaultLabel(kind, payload) {
        if (kind === 'node') return String((payload && (payload.title || payload.type)) || 'node');
        if (kind === 'nodes') return I18n.t('clipboard.kindNodes', { n: payload ? payload.length : 0 });
        const first = String(payload || '').split('\n')[0].trim();
        return first.length > 40 ? first.slice(0, 40) + '…' : first;
    },

    get(id) {
        for (let i = 0; i < this.items.length; i++) if (this.items[i].id === id) return this.items[i];
        return null;
    },

    remove(id) {
        this.items = this.items.filter((it) => it.id !== id);
        this.save();
        this.render();
    },

    clearAll() {
        /* An explicit "清空" wins over pins (a pin only protects against cap-eviction). */
        this.items = [];
        this.save();
        this.render();
        if (typeof showToast === 'function') showToast(I18n.t('toast.clipboardCleared'));
    },

    togglePin(id) {
        const it = this.get(id);
        if (!it) return;
        it.pinned = !it.pinned;
        this.save();
        this.render();
    },

    rename(id) {
        const it = this.get(id);
        if (!it) return Promise.resolve(false);
        return Promise.resolve(showDialog({
            message: I18n.t('clipboard.rename'),
            input: { value: it.label || '' },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('dialog.confirm'), primary: true },
            ],
        })).then((answer) => {
            if (answer === null || answer === undefined) return false;
            const text = String(answer).trim();
            if (text) it.label = text;
            this.save();
            this.render();
            return true;
        });
    },

    /* Add a free-text entry from the drawer's own "add text" button — the ONLY text
       source, so we never call navigator.clipboard.readText (unavailable over plain
       http, and the repo consistently refuses to guess at a hidden clipboard). */
    addText() {
        return Promise.resolve(showDialog({
            message: I18n.t('clipboard.addPrompt'),
            input: { placeholder: I18n.t('clipboard.addPrompt'), value: '' },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('dialog.confirm'), primary: true },
            ],
        })).then((answer) => {
            if (answer === null || answer === undefined) return null;
            const text = String(answer);
            if (!text.trim()) return null;
            const id = this.add({ kind: 'text', payload: text });
            if (typeof showToast === 'function') showToast(I18n.t('toast.clipboardAdded'));
            return id;
        });
    },

    /* nodeRecordFromText mirrors importNodeFromJson's validation exactly: a known type
       and a params object, nothing else mints a node. */
    nodeRecordFromText(text) {
        let parsed;
        try {
            parsed = JSON.parse(String(text).trim());
        } catch (e) {
            return null;
        }
        if (!parsed || typeof parsed !== 'object'
            || canvas.validNodeTypes().indexOf(parsed.type) < 0
            || typeof parsed.params !== 'object' || parsed.params === null) {
            return null;
        }
        return { type: parsed.type, title: String(parsed.title || ''), params: parsed.params };
    },

    /* Paste loads the chosen entry into the working slot and runs the shared funnel, so
       a drawer paste can never differ from a Ctrl+V paste of the same record. */
    paste(id, pos) {
        const it = this.get(id);
        if (!it || (it.kind !== 'node' && it.kind !== 'nodes')) return null;
        const copy = JSON.parse(JSON.stringify(it.payload));
        if (it.kind === 'node') {
            canvas._clipboardNodes = null;
            canvas._clipboardData = copy;
            return canvas._pasteAt(pos || null);
        }
        canvas._clipboardData = null;
        canvas._clipboardNodes = copy;
        return canvas._pasteAt(pos || null);
    },

    /* A text entry whose content is a node JSON becomes a node; otherwise refuse BY
       NAME with the same toast import uses — never silently mint a broken box. */
    insertText(id, pos) {
        const it = this.get(id);
        if (!it || it.kind !== 'text') return null;
        const rec = this.nodeRecordFromText(it.payload);
        if (!rec) {
            if (typeof showToast === 'function') showToast(I18n.t('toast.nodeJsonInvalid'));
            return null;
        }
        canvas._clipboardNodes = null;
        canvas._clipboardData = rec;
        return canvas._pasteAt(pos || null);
    },

    /* Text → the OS clipboard, reusing the secure-context-or-dialog fallback shape the
       node JSON copy already established (a failed write shows the text, never a lie). */
    copyText(id) {
        const it = this.get(id);
        if (!it || it.kind !== 'text') return Promise.resolve(false);
        const text = String(it.payload);
        const notify = () => {
            if (typeof showToast === 'function') showToast(I18n.t('toast.clipboardTextCopied'));
            return true;
        };
        if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text).then(notify, () => this._showTextFallback(text));
        }
        return this._showTextFallback(text);
    },

    _showTextFallback(text) {
        return Promise.resolve(showDialog({
            message: I18n.t('clipboard.copy'),
            input: { value: text },
            buttons: [{ label: I18n.t('dialog.confirm'), primary: true }],
        })).then(() => true);
    },

    _filtered() {
        const q = this._query.trim().toLowerCase();
        const list = this.items.slice();
        list.sort((a, b) => (b.pinned - a.pinned) || (b.ts - a.ts));
        if (!q) return list;
        return list.filter((it) => (String(it.label).toLowerCase().indexOf(q) >= 0) || (it.kind.indexOf(q) >= 0));
    },

    _esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    render() {
        const box = document.getElementById('clipboard-list');
        if (!box) return;
        const list = this._filtered();
        if (!list.length) {
            box.innerHTML = '<div class="clip-empty">' + this._esc(I18n.t('clipboard.empty')) + '</div>';
            return;
        }
        let html = '';
        list.forEach((it) => {
            const badge = it.kind === 'node'
                ? I18n.t('clipboard.kindNode')
                : it.kind === 'nodes'
                    ? I18n.t('clipboard.kindNodes', { n: (it.payload || []).length })
                    : I18n.t('clipboard.kindText');
            const label = this._esc(it.label || '');
            let actions = '<button class="clip-btn" type="button" data-clip-action="pin" data-clip-id="'
                + it.id + '" title="' + this._esc(I18n.t(it.pinned ? 'clipboard.unpin' : 'clipboard.pin')) + '">'
                + (it.pinned ? '★' : '☆') + '</button>';
            if (it.kind === 'node' || it.kind === 'nodes') {
                actions += '<button class="clip-btn" type="button" data-clip-action="paste" data-clip-id="'
                    + it.id + '">' + this._esc(I18n.t('clipboard.paste')) + '</button>';
            }
            if (it.kind === 'text') {
                actions += '<button class="clip-btn" type="button" data-clip-action="copy" data-clip-id="'
                    + it.id + '">' + this._esc(I18n.t('clipboard.copy')) + '</button>';
                actions += '<button class="clip-btn" type="button" data-clip-action="insert" data-clip-id="'
                    + it.id + '">' + this._esc(I18n.t('clipboard.insert')) + '</button>';
            }
            actions += '<button class="clip-btn" type="button" data-clip-action="rename" data-clip-id="'
                + it.id + '">' + this._esc(I18n.t('clipboard.rename')) + '</button>';
            actions += '<button class="clip-btn clip-danger" type="button" data-clip-action="delete" data-clip-id="'
                + it.id + '">' + this._esc(I18n.t('clipboard.delete')) + '</button>';
            const isNode = (it.kind === 'node' || it.kind === 'nodes');
            const dragAttrs = isNode
                ? ' draggable="true" title="' + this._esc(I18n.t('clipboard.dragHint')) + '"'
                : '';
            html += '<div class="clip-row' + (it.pinned ? ' clip-pinned' : '') + '"' + dragAttrs + ' data-clip-id="' + it.id + '">'
                + '<span class="clip-badge">' + this._esc(badge) + '</span>'
                + '<span class="clip-label" title="' + label + '">' + label + '</span>'
                + '<span class="clip-actions">' + actions + '</span>'
                + '</div>';
        });
        box.innerHTML = html;
    },

    onAction(e) {
        const btn = e.target && e.target.closest ? e.target.closest('[data-clip-action]') : null;
        if (!btn) return;
        const action = btn.getAttribute('data-clip-action');
        const id = btn.getAttribute('data-clip-id');
        if (action === 'paste') this.paste(id, null);
        else if (action === 'insert') this.insertText(id, null);
        else if (action === 'copy') this.copyText(id);
        else if (action === 'rename') this.rename(id);
        else if (action === 'pin') this.togglePin(id);
        else if (action === 'delete') this.remove(id);
    },

    setQuery(v) {
        this._query = String(v || '');
        this.render();
    },

    requestClearAll() {
        return Promise.resolve(showDialog({
            message: I18n.t('clipboard.clearConfirm'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('clipboard.clear'), value: 'clear', primary: true },
            ],
        })).then((answer) => {
            if (answer === 'clear') {
                this.clearAll();
                return true;
            }
            return false;
        });
    },
};

/* The drawer is a right-side slide-in; opening re-renders so a board that filled while
   closed (e.g. by an earlier copy) is current the moment the user sees it. */
function toggleClipboardDrawer() {
    const drawer = document.getElementById('clipboard-drawer');
    if (!drawer) return;
    if (drawer.classList.contains('open')) {
        drawer.classList.remove('open');
    } else {
        drawer.classList.add('open');
        Clipboard.render();
    }
}

/* The keyboard-shortcut cheat sheet: an overlay opened from the View menu, `?` or F1 and
   closed by its button, Escape, or a click on the backdrop. It paints a static list of the
   shortcuts the canvas ACTUALLY binds (see the keydown handler) — never a guessed table. */
function openShortcutsHelp() {
    const box = document.getElementById('help-overlay');
    if (box) box.classList.add('open');
}

function closeShortcutsHelp() {
    const box = document.getElementById('help-overlay');
    if (box) box.classList.remove('open');
}

function toggleShortcutsHelp() {
    const box = document.getElementById('help-overlay');
    if (!box) return;
    if (box.classList.contains('open')) closeShortcutsHelp();
    else openShortcutsHelp();
}
