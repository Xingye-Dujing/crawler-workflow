/* The lexicon panel: the user's stop words and jieba domain terms.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-29) byte for byte. One row per word with an add box
 * above it; the server owns the list, so every action ends in a refresh rather than a local guess.
 */

/* ─── Lexicon manager: the user's stop words and jieba domain terms ────
   Two word lists the analysis pipeline reads but the user could not edit until now.
   Mirrors datasetManager's docked-panel shape (one slot, close clears the inline
   height, every onclick arg escaped by attrJsArg, the add dialog's confirm button
   carries no `value:`). A write re-materialises the jieba dict server-side, so the
   next run picks it up. */
var lexiconManager = {
    _kind: 'stopword',
    _last: [],
    _counts: { stopword: 0, userdict: 0 },
    _filter: '',

    panel() {
        return document.getElementById('lexicon-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('lexicon-panel');
        panel.classList.add('open');
        this.refresh();
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        panel.style.height = '';
    },

    setKind(kind) {
        this._kind = kind;
        this.refresh();
    },

    setFilter(term) {
        this._filter = term || '';
        this.render();
    },

    async refresh() {
        var body = document.getElementById('lexicon-body');
        if (!body) return;
        body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('lexMgr.loading') + '</div>';
        var result = await fetchJSON('/api/lexicon?kind=' + encodeURIComponent(this._kind)).catch(function () { return null; });
        if (!result || !result.ok) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('lexMgr.loadFailed') + '</div>';
            return;
        }
        this._last = result.entries || [];
        this._counts = result.counts || this._counts;
        this.render();
    },

    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        this.render();
    },

    _quote(value) {
        return attrJsArg(value);
    },

    render() {
        var head = document.getElementById('lexicon-body');
        if (!head) return;
        var self = this;
        var kinds = [['stopword', I18n.t('lexMgr.stopwords')], ['userdict', I18n.t('lexMgr.userdict')]];
        var tabs = kinds.map(function (k) {
            var on = self._kind === k[0];
            return '<button class="menu-btn' + (on ? ' toggle-on' : '') + '" onclick="lexiconManager.setKind(\'' + k[0] + '\')">' +
                escapeHtml(k[1]) + ' (' + (self._counts[k[0]] || 0) + ')</button>';
        }).join(' ');
        var toolbar = '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">' + tabs +
            '<input class="settings-input" style="flex:1;min-width:120px;" placeholder="' + escapeHtml(I18n.t('lexMgr.search')) + '" ' +
            'value="' + escapeHtml(this._filter) + '" oninput="lexiconManager.setFilter(this.value)">' +
            '<button class="menu-btn" onclick="lexiconManager.add()">' + escapeHtml(I18n.t('lexMgr.add')) + '</button>' +
            '<button class="menu-btn del" onclick="lexiconManager.clearAll()">' + escapeHtml(I18n.t('lexMgr.clear')) + '</button>' +
            '</div>';
        var term = this._filter.trim().toLowerCase();
        var rows = (this._last || []).filter(function (r) {
            return !term || String(r.term || '').toLowerCase().indexOf(term) >= 0;
        });
        var list;
        if (!rows.length) {
            list = '<div class="runs-mgr-empty">' + escapeHtml(I18n.t(term ? 'lexMgr.noMatch' : 'lexMgr.empty')) + '</div>';
        } else {
            list = '<div class="lexicon-chips">' + rows.map(function (r) {
                var t = String(r.term || '');
                return '<span class="lexicon-chip">' + escapeHtml(t) +
                    '<button class="lexicon-chip-x" title="' + escapeHtml(I18n.t('lexMgr.remove')) + '" ' +
                    'onclick="lexiconManager.removeTerm(\'' + self._quote(t) + '\')">×</button></span>';
            }).join('') + '</div>';
        }
        var hint = '<div class="lexicon-hint">' +
            escapeHtml(this._kind === 'userdict' ? I18n.t('lexMgr.hintUserdict') : I18n.t('lexMgr.hintStopword')) + '</div>';
        head.innerHTML = toolbar + list + hint;
    },

    async add() {
        var answer = await showDialog({
            message: I18n.t('lexMgr.addPrompt'),
            input: { placeholder: I18n.t('lexMgr.addPlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('lexMgr.add'), primary: true },
            ],
        });
        if (!answer || !String(answer).trim()) return;
        var terms = String(answer).replace('，', ',').replace('、', ',').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
        var result = await fetchJSON('/api/lexicon', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ kind: this._kind, terms: terms }),
        });
        if (result && result.ok) {
            showToast(I18n.t('lexMgr.addDone').replace('{n}', result.added || 0));
            this.refresh();
        } else {
            showToast((result && result.error) || I18n.t('lexMgr.addFailed'));
        }
    },

    async removeTerm(term) {
        var result = await fetchJSON('/api/lexicon', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ kind: this._kind, term: term }),
        });
        if (result && result.ok) this.refresh();
        else showToast((result && result.error) || I18n.t('lexMgr.removeFailed'));
    },

    async clearAll() {
        var ok = await showDialog({
            message: I18n.t('lexMgr.confirmClear'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('lexMgr.clear'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/lexicon', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ kind: this._kind, clear: true }),
        });
        if (result && result.ok) showToast(I18n.t('lexMgr.clearDone').replace('{n}', result.removed || 0));
        else showToast((result && result.error) || I18n.t('lexMgr.clearFailed'));
        this.refresh();
    },
};

function toggleLexiconPanel() {
    lexiconManager.toggle();
}


