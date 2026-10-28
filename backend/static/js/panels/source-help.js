/* The export guide: where each bibliographic source is obtained from.
 *
 * The shell is static markup; every sentence inside it is served by GET /api/biblio/sources, because
 * which site exports which file — and which field a real export genuinely lacks — is the parser's
 * knowledge, not the browser's. Group headings are literal keys on purpose: a spliced
 * ``I18n.t('sourceHelp.group.' + g)`` is invisible to the key audits.
 *
 * Split out of ``panels/cookies.js`` (Stage 8, 2026-10-28) byte for byte, where a contiguous carve
 * had carried it along with the Cookie panel. Reached by name from the menu, the upload node and the
 * Escape handler.
 */

/* ─── Export guide (where each bibliographic source comes from) ───────────────────
   The shell is static markup; every sentence inside it is served by GET /api/biblio/sources.
   Which site exports which file — and which field a real export genuinely lacks — is the
   parser's knowledge, so the browser holds no second copy of it and draws nothing until the
   answer lands (the same rule the 采集建议 dialog obeys). Group headings are literal keys on
   purpose: a spliced `I18n.t('sourceHelp.group.' + g)` is invisible to the key audits. */
var GROUP_KEYS = { library: 'sourceHelp.groupLibrary', exchange: 'sourceHelp.groupExchange' };
var GROUP_ORDER = ['library', 'exchange'];

var sourceHelp = {
    sources: [],
    extensions: [],
    error: '',
    loaded: false,
    _backdropBound: false,

    _overlay: function () {
        return document.getElementById('source-help-overlay');
    },

    isOpen: function () {
        var box = this._overlay();
        return !!(box && box.classList && box.classList.contains('open'));
    },

    toggle: function () {
        if (this.isOpen()) this.close();
        else this.open();
    },

    open: function () {
        var box = this._overlay();
        if (!box) return;
        box.classList.add('open');
        if (!this._backdropBound && box.addEventListener) {
            /* A click on the dimmed backdrop closes; a click inside the sheet does not.
               Registered once, lazily, so opening the guide cannot be a boot blocker. */
            var self = this;
            box.addEventListener('click', function (event) {
                if (event.target === box) self.close();
            });
            this._backdropBound = true;
        }
        if (this.loaded) this.render();
        else {
            /* Paint the waiting line first: the static markup is replaced by the first
               innerHTML write, and an empty box reads as a broken panel, not a loading one. */
            this.render();
            this.reload();
        }
    },

    close: function () {
        var box = this._overlay();
        if (box) box.classList.remove('open');
    },

    reload: function () {
        var self = this;
        this._fetch().then(function (answer) {
            if (!answer || answer.ok !== true || !Array.isArray(answer.sources)) {
                self.error = (answer && answer.error) || 'HTTP ?';
                self.render();
                return;
            }
            self.sources = answer.sources;
            self.extensions = Array.isArray(answer.extensions) ? answer.extensions : [];
            self.error = '';
            self.loaded = true;
            self.render();
            self.applyExtensions();
        });
    },

    _fetch: function () {
        return fetchJSON('/api/biblio/sources');
    },

    /* The file picker's `accept` is the registry's answer, not a list this file remembers. */
    applyExtensions: function () {
        var input = document.getElementById('dataset-file-input');
        if (!input || !this.extensions.length) return;
        var wanted = this.extensions.slice();
        /* The picker also takes the ordinary tables the node accepts; those are the route's
           business, so only the bibliographic additions are merged in. */
        (input.getAttribute('accept') || '').split(',').forEach(function (item) {
            var name = item.trim();
            if (name && wanted.indexOf(name) < 0) wanted.push(name);
        });
        input.setAttribute('accept', wanted.join(','));
    },

    _section: function (source) {
        var site = String(source.site || '');
        var head = '<div class="source-help-head">' +
            '<span class="source-help-name">' + escapeHtml(String(source.label || source.id || '')) + '</span>';
        if (site) {
            /* The text is the URL itself, so it can be copied even where a link will not open. */
            head += '<span class="source-help-site"><a href="' + escapeHtml(site) +
                '" target="_blank" rel="noopener noreferrer">' + escapeHtml(site) + '</a></span>';
        }
        var extensions = (source.extensions || []).map(function (item) {
            return escapeHtml(String(item));
        }).join(' ');
        if (extensions) head += '<span class="source-help-ext">' + extensions + '</span>';
        head += '</div>';
        var steps = (source.steps || []).map(function (line) {
            return '<li>' + escapeHtml(String(line)) + '</li>';
        }).join('');
        var missing = (source.missing || []).map(function (line) {
            return '<div>' + escapeHtml(String(line)) + '</div>';
        }).join('');
        return '<div class="source-help-item">' + head +
            '<div class="source-help-purpose">' + escapeHtml(String(source.purpose || '')) + '</div>' +
            (steps ? '<ol class="source-help-steps">' + steps + '</ol>' : '') +
            (missing ? '<div class="source-help-missing">' + missing + '</div>' : '') +
            '</div>';
    },

    render: function () {
        var body = document.getElementById('source-help-body');
        if (!body) return;
        if (this.error) {
            body.innerHTML = '<div class="source-help-loading">' +
                escapeHtml(I18n.t('sourceHelp.unavailable') + ' ' + this.error) + '</div>';
            return;
        }
        if (!this.loaded) {
            body.innerHTML = '<div class="source-help-loading">' + escapeHtml(I18n.t('sourceHelp.loading')) + '</div>';
            return;
        }
        var parts = [];
        GROUP_ORDER.forEach(function (group) {
            var items = sourceHelp.sources.filter(function (source) {
                return source.group === group;
            });
            if (!items.length) return;
            parts.push('<div class="source-help-group">' + escapeHtml(I18n.t(GROUP_KEYS[group])) + '</div>');
            items.forEach(function (source) {
                parts.push(sourceHelp._section(source));
            });
        });
        body.innerHTML = parts.join('');
    },

    onLanguageChange: function () {
        /* Served sentences: a switch has to refetch, which is why the cookie guide reloads too. */
        if (this.isOpen() && this.loaded) this.reload();
    },
};

function toggleSourceHelp() {
    sourceHelp.toggle();
}

function openSourceHelp() {
    sourceHelp.open();
}

function closeSourceHelp() {
    sourceHelp.close();
}

