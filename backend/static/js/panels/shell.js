/* Shell: the outline sidebar, language switch, toasts, process list, dialogs and fetchJSON.
 * Split out of workflow.js; loaded after it so every global name stays resolvable. */

/* ── Outline sidebar (right) ────────────────────────────────────────── */
/* A flat map of every node on the canvas: click a row and the camera jumps to it at a
   readable size. The list is rebuilt from the model inside canvas.saveState() (canvas.js),
   which is the single chokepoint every structural change passes through — so it can never
   drift from the graph, and this object owns only the DOM and the jump. Rows are built with
   createElement + textContent (never an innerHTML string keyed by the node id), because a
   workflow file can author any id and an inline handler would have to re-escape it. */
const Outline = {
    /* The active filter query (lower-cased); the finder input writes it via setFilter.
       It lives on the object, not the DOM, so render() stays the single source of what
       shows and a language switch repaint can re-apply it to the new labels. */
    _query: '',

    /* The rows as data (no DOM). `off` = outside the effective graph (disabled, starved,
       or its type switched off): still listed — the outline is a complete map, not a run
       preview — but dimmed so it does not read as live. */
    _collect() {
        var live = canvas.effectiveIds();
        return Object.keys(canvas.nodes).map(function (id) {
            var n = canvas.nodes[id];
            return {
                id: id,
                type: n.type,
                label: n.title || I18n.t('node.' + n.type),
                off: live.indexOf(id) < 0,
            };
        });
    },

    _tag(type) {
        var m = {
            name: 'NAM', source: 'SRC', upload: 'UPL', resume: 'RSM', process: 'PRC',
            analysis: 'ANL', tokenize: 'TKN', visualize: 'VIZ', compile: 'CMP', output: 'OUT', comment: 'CMT',
        };
        return m[type] || String(type).slice(0, 3).toUpperCase();
    },

    /* Filter the list to rows whose label, node type or tag contain the query (matching the
       type too lets "src"/"SRC" find sources whatever language the label is in). */
    setFilter(query) {
        this._query = String(query == null ? '' : query).toLowerCase();
        this.render();
    },

    /* Ctrl/Cmd+F: reveal the finder — expand the sidebar if collapsed and focus its filter
       box — so the user is typing to find a node, not folding the selected one. */
    revealFilter() {
        var panel = document.getElementById('outline-panel');
        if (panel && panel.classList.contains('collapsed')) this.toggle();
        var box = document.getElementById('outline-filter');
        if (box) {
            box.focus();
            if (box.select) box.select();
        }
    },

    render() {
        var list = document.getElementById('outline-list');
        if (!list) return;
        var rows = this._collect();
        if (this._query) {
            var q = this._query;
            var outline = this;
            rows = rows.filter(function (r) {
                return (r.label + ' ' + r.type + ' ' + outline._tag(r.type)).toLowerCase().indexOf(q) >= 0;
            });
        }
        list.textContent = '';
        if (rows.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'outline-empty';
            empty.textContent = this._query ? I18n.t('outline.noMatch') : I18n.t('outline.noNodes');
            list.appendChild(empty);
            return;
        }
        var self = this;
        rows.forEach(function (r) {
            var row = document.createElement('div');
            row.className = 'outline-row' + (r.off ? ' outline-off' : '');
            row.dataset.node = r.id;
            row.title = r.label;
            var chip = document.createElement('span');
            chip.className = 'outline-type';
            chip.textContent = self._tag(r.type);
            var name = document.createElement('span');
            name.className = 'outline-name';
            name.textContent = r.label;
            row.appendChild(chip);
            row.appendChild(name);
            row.addEventListener('click', function () { self.focus(r.id); });
            list.appendChild(row);
        });
        this._markActive();
    },

    focus(id) {
        if (!canvas.nodes[id]) return;
        canvas.selectNode(id);
        canvas.centerOnNode(id);
        this._markActive();
    },

    _markActive() {
        var list = document.getElementById('outline-list');
        if (!list) return;
        /* The outline mirrors the GRAPH's selection, and the graph can hold a whole group
           (shift-click / marquee). Reading only the anchor lit just the last-clicked row while
           every selected box on the canvas was highlighted — the sidebar disagreed with the
           graph about what was selected. Highlight every member; fall back to the single anchor
           so a caller that sets selectedNode without a group still lights its row. */
        var group = canvas.selectedNodes && canvas.selectedNodes.length ? canvas.selectedNodes : [canvas.selectedNode];
        var active = {};
        group.forEach(function (id) {
            if (id != null) active[id] = true;
        });
        list.querySelectorAll('.outline-row').forEach(function (row) {
            row.classList.toggle('outline-active', active[row.dataset.node] === true);
        });
    },

    toggle() {
        var panel = document.getElementById('outline-panel');
        if (!panel) return;
        var btn = panel.querySelector('.outline-toggle');
        var collapsed = panel.classList.toggle('collapsed');
        if (btn) {
            btn.textContent = collapsed ? '+' : '−';
            btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            btn.title = I18n.t(collapsed ? 'outline.expand' : 'outline.collapse');
        }
        /* Kept beside the camera in the draft, not in getState(): a collapse is a view
           preference, never an undo step. Its own key so toggling cannot churn a model save. */
        try {
            localStorage.setItem('crawler_outline_collapsed', collapsed ? '1' : '');
        } catch (e) { /* a blocked store is not worth losing the sidebar over */ }
    },

    init() {
        var panel = document.getElementById('outline-panel');
        if (!panel) return;
        var collapsed = false;
        try {
            collapsed = localStorage.getItem('crawler_outline_collapsed') === '1';
        } catch (e) { collapsed = false; }
        if (collapsed) panel.classList.add('collapsed');
        var btn = panel.querySelector('.outline-toggle');
        if (btn) {
            btn.textContent = collapsed ? '+' : '−';
            btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            btn.title = I18n.t(collapsed ? 'outline.expand' : 'outline.collapse');
        }
        var box = document.getElementById('outline-filter');
        if (box) {
            box.placeholder = I18n.t('outline.filterPlaceholder');
            var outline = this;
            box.addEventListener('input', function (e) {
                outline.setFilter(e && e.target ? e.target.value : box.value);
            });
        }
        this.render();
    },
};

function toggleOutline() {
    Outline.toggle();
}

/* Apply a canvas background. Called from the background swatches inside the
   View group of the flat bar, so the swatch that is current gets `.active`. */
function setBg(bg, el) {
    var body = document.body;
    body.className = body.className.replace(/bg-\S+/g, '').trim();
    body.classList.add(bg);
    document.querySelectorAll('.bar-bg-dot').forEach(function (o) { o.classList.remove('active'); });
    if (el) el.classList.add('active');
    Settings.save();
}

function setLang(nextLang) {
    var body = document.body;
    body.dataset.lang = nextLang;
    I18n.apply();
    Settings.save();
    showToast(I18n.t('toast.languageChanged').replace('{lang}', nextLang === 'zh' ? '中文' : 'English'));
    /* Refresh dynamically rendered content */
    Object.keys(canvas.nodes).forEach(function (id) {
        canvas.updateNodeDisplay(id);
    });
    /* The 已禁用/无输入 badge is worded by ``applyDisabledVisuals``, which per-node
       ``updateNodeDisplay`` never touches — so a language switch re-stamped the title, the
       summary and the tooltips and left 「DISABLED」 sitting on the corner of a node that
       had just turned Chinese. One call, because the state is computed for the whole canvas
       at once and asking per node would recompute the same answer N times. */
    canvas.applyDisabledVisuals();
    /* Run verdicts carry a localized status word in their tooltip; the badge holds
       no state of its own, so repainting from the loaded map is the whole update. */
    if (typeof runResults !== 'undefined') canvas.applyRunStatuses(runResults.statuses);
    if (canvas._settingsNodeId) openSettings(canvas._settingsNodeId);
    /* Keep the flat bar's active-language marker truthful. */
    if (window.TopMenu) TopMenu.refresh();
    /* Chart Studio: its mirrored nav chips and its source list (whose rows
       carry localised reasons) are built by JS, so I18n.apply() never reaches
       them — rebuild both. */
    if (window.chartStudio) {
        chartStudio.refreshMenus();
        chartStudio.refreshSources();
    }
    if (window.CustomSelect) CustomSelect.refreshAll();
    /* The run-records table is JS-rendered, so I18n.apply() never reaches it —
       if the panel is open, redraw it in the new language right away instead
       of only after the next open. */
    if (window.runsManager) runsManager.onLanguageChange();
    if (window.exportsManager) exportsManager.onLanguageChange();
    /* The saved-logins dock is JS-rendered like those two, and so are the lines the Cookie
       dialog paints under the account box — same bug class, same one-call fix. The dialog's
       own repaint is cheap (cached rows, no request) and it is the panel a user is most
       likely to be looking at when he switches language to read a platform's steps. */
    if (typeof cookiesManager !== 'undefined') cookiesManager.onLanguageChange();
    if (typeof renderCookieAccountStatus === 'function' && document.getElementById('cookie-account-status')) {
        renderCookieAccountStatus();
        renderCookieGuide();
    }
    /* The export guide's sentences are served per language, so an open guide has to refetch —
       the same reason the cookie guide does. */
    if (typeof sourceHelp !== 'undefined') sourceHelp.onLanguageChange();
    /* Both of these had the method and never got the call, so their tables kept the
       old language while the rest of the page re-stamped around them. `datasetManager`
       is a top-level `var`, which does make it a window property — but the guard is
       written against the binding for the same reason the resume bar once wasn't. */
    if (typeof datasetManager !== 'undefined') datasetManager.onLanguageChange();
    if (typeof lexiconManager !== 'undefined') lexiconManager.onLanguageChange();
    if (typeof historyPanel !== 'undefined') historyPanel.onLanguageChange();
    if (typeof wfFiles !== 'undefined') wfFiles.onLanguageChange();
    /* The Style menu's baseline hint is painted by JS from the last layout read, so a
       language switch must re-stamp it rather than leave one English line in a Chinese menu. */
    if (typeof LayoutStrategy !== 'undefined') LayoutStrategy._paint();
    /* The scheduled-task dock is JS-rendered like those, and its table says 「下次运行」 in the
       task's own zone — a row left in the old language would be the one word in the panel that
       did not switch. */
    if (typeof schedulesManager !== 'undefined') schedulesManager.onLanguageChange();
    /* The bibliometrics dock prints its run/node pickers, the shape of the stored table and the
       paging line from here, so nothing `I18n.apply()` re-stamps reaches them. */
    if (typeof biblioWorkspace !== 'undefined') biblioWorkspace.onLanguageChange();
    /* A reusable node's inside preview is JS-painted (title, meta, slot labels,
       statuses), so an open preview would otherwise keep the old language. */
    if (typeof ReusableNodes !== 'undefined' && ReusableNodes.repaintPreview) ReusableNodes.repaintPreview();
}

function showToast(msg, ms) {
    var toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.classList.add('show');
    /* A longer message has to be readable, not merely present: the fixed 2.5 s was
       written for one short sentence and the multi-problem toast below carries a
       line per problem. */
    setTimeout(function () { toast.classList.remove('show'); }, ms || 2500);
}

/* Console Panel */
/* Workflow tab switching for parallel mode */
var _wfActiveTab = 'all';
function switchWfTab(wfId) {
    _wfActiveTab = wfId;
    /* Repainted from the view's own history rather than emptied: the server holds
       only the tail of the whole run, so a blank box here read as "switching tabs
       deletes the console". The cursor stays put, so the next poll appends only
       what is genuinely new to this view. */
    repaintConsoleView(document.getElementById('console-output'), wfId);
    /* Update active tab styling */
    document.querySelectorAll('#console-tabs .console-tab').forEach(function (tab) {
        tab.classList.toggle('active', String(tab.dataset.wf) === String(wfId));
    });
}

/* Kill a process by calling the API */
function killProcess(btn) {
    var ident = parseInt(btn.dataset.ident);
    if (!ident) return;
    fetch('/api/workflow/processes/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ident: ident }),
    })
        .then(function (r) { return r.json(); })
        .then(function (result) {
            if (result.ok) {
                showToast(result.message);
            } else {
                showToast(I18n.t('toast.killFailed') + ': ' + (result.error || ''));
            }
        })
        .catch(function (err) {
            showToast(I18n.t('toast.killFailed') + ': ' + err.message);
        });
}

/* Processes Monitor Panel */
function toggleProcessesPanel() {
    var panel = document.getElementById('processes-panel');
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) {
        /* It lives in the same bottom slot as the other docks: opening it must shut them, and it
           is listed in DOCKED_PANELS so opening any of THEM shuts this one. */
        closeDockedPanels('processes-panel');
        processesPoll();
    }
}

var _procInterval = null;

function processesPoll() {
    if (_procInterval) clearInterval(_procInterval);
    var panel = document.getElementById('processes-panel');
    if (!panel.classList.contains('open')) return;

    fetch('/api/workflow/processes')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!panel.classList.contains('open')) return;
            var out = document.getElementById('processes-output');
            var html = '';

            /* Summary line */
            var runningText = data.running
                ? '<span class="proc-ok">\u25cf ' + I18n.t('processes.running') + '</span>'
                : '<span class="proc-err">\u25cf ' + I18n.t('processes.stopped') + '</span>';
            html += '<div class="proc-summary">' + runningText +
                '<span>' + I18n.t('processes.threads') + ': <b>' + data.threads.length + '</b></span>' +
                '<span>' + I18n.t('processes.crawlers') + ': <b>' + data.active_crawlers + '</b></span>' +
                '<span>' + I18n.t('processes.pool') + ': <b>' + (data.executor_pool_alive ? I18n.t('processes.yes') : I18n.t('processes.no')) + '</b></span>' +
                '</div>';

            /* Thread table */
            html += '<table class="proc-table"><tr>' +
                '<th>' + I18n.t('processes.name') + '</th>' +
                '<th>' + I18n.t('processes.type') + '</th>' +
                '<th>' + I18n.t('processes.status') + '</th>' +
                '<th>' + I18n.t('processes.kill') + '</th>' +
                '</tr>';
            data.threads.forEach(function (t) {
                var typeClass = '';
                var typeLabel = '';
                if (t.name === 'MainThread') { typeLabel = 'main'; }
                else if (t.name.startsWith('ThreadPoolExecutor')) { typeLabel = '<span class="proc-tag proc-tag-pool">pool</span>'; }
                else if (t.name === 'run') { typeLabel = '<span class="proc-tag proc-tag-run">run</span>'; }
                else { typeLabel = t.daemon ? '<span class="proc-tag proc-tag-daemon">daemon</span>' : ''; }
                var canKill = t.name !== 'MainThread' && t.name !== 'run' && t.alive;
                html += '<tr>' +
                    '<td>' + escapeHtml(t.name) + '</td>' +
                    '<td>' + typeLabel + '</td>' +
                    '<td>' + (t.alive ? '<span class="proc-ok">alive</span>' : '<span class="proc-err">dead</span>') + '</td>' +
                    '<td>' + (canKill ? '<button class="proc-kill-btn" data-ident="' + escapeHtml(t.ident) + '" onclick="killProcess(this)">' + I18n.t('processes.kill') + '</button>' : '') + '</td>' +
                    '</tr>';
            });
            html += '</table>';
            out.innerHTML = html;
        })
        .catch(function () {
            if (document.getElementById('processes-panel').classList.contains('open')) {
                document.getElementById('processes-output').innerHTML =
                    '<div class="proc-line proc-err">' + I18n.t('processes.fetchFailed') + '</div>';
            }
        });

    /* Poll every 1s while open */
    _procInterval = setInterval(function () {
        if (!document.getElementById('processes-panel').classList.contains('open')) {
            clearInterval(_procInterval);
            _procInterval = null;
            return;
        }
        fetch('/api/workflow/processes')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!document.getElementById('processes-panel').classList.contains('open')) return;
                var out = document.getElementById('processes-output');
                var html = '';
                var runningText = data.running
                    ? '<span class="proc-ok">\u25cf ' + I18n.t('processes.running') + '</span>'
                    : '<span class="proc-err">\u25cf ' + I18n.t('processes.stopped') + '</span>';
                html += '<div class="proc-summary">' + runningText +
                    '<span>' + I18n.t('processes.threads') + ': <b>' + data.threads.length + '</b></span>' +
                    '<span>' + I18n.t('processes.crawlers') + ': <b>' + data.active_crawlers + '</b></span>' +
                    '<span>' + I18n.t('processes.pool') + ': <b>' + (data.executor_pool_alive ? I18n.t('processes.yes') : I18n.t('processes.no')) + '</b></span>' +
                    '</div>';
                html += '<table class="proc-table"><tr>' +
                    '<th>' + I18n.t('processes.name') + '</th>' +
                    '<th>' + I18n.t('processes.type') + '</th>' +
                    '<th>' + I18n.t('processes.status') + '</th>' +
                    '<th>' + I18n.t('processes.kill') + '</th>' +
                    '</tr>';
                data.threads.forEach(function (t) {
                    var typeLabel = '';
                    if (t.name === 'MainThread') { typeLabel = 'main'; }
                    else if (t.name.startsWith('ThreadPoolExecutor')) { typeLabel = '<span class="proc-tag proc-tag-pool">pool</span>'; }
                    else if (t.name === 'run') { typeLabel = '<span class="proc-tag proc-tag-run">run</span>'; }
                    else { typeLabel = t.daemon ? '<span class="proc-tag proc-tag-daemon">daemon</span>' : ''; }
                    var canKill = t.name !== 'MainThread' && t.name !== 'run' && t.alive;
                    html += '<tr>' +
                        '<td>' + escapeHtml(t.name) + '</td>' +
                        '<td>' + typeLabel + '</td>' +
                        '<td>' + (t.alive ? '<span class="proc-ok">alive</span>' : '<span class="proc-err">dead</span>') + '</td>' +
                        '<td>' + (canKill ? '<button class="proc-kill-btn" data-ident="' + escapeHtml(t.ident) + '" onclick="killProcess(this)">' + I18n.t('processes.kill') + '</button>' : '') + '</td>' +
                        '</tr>';
                });
                html += '</table>';
                out.innerHTML = html;
            }).catch(function () { });
    }, 1000);
}

/* Custom Dialog - replaces browser prompt() */
function showDialog(opts) {
    return new Promise(function (_resolve) {
        var overlay = document.getElementById('dialog-overlay');
        var msgEl = document.getElementById('dialog-message');
        var inputArea = document.getElementById('dialog-input-area');
        var inputEl = document.getElementById('dialog-input');
        var listArea = document.getElementById('dialog-list-area');
        var actionsEl = document.getElementById('dialog-actions');

        /* The dialog is dismissable like a modal: a drawn close (X), a click on the
           backdrop, and Esc all resolve the "no answer" value. The cancel result
           defaults to null so a caller that awaits a typed string or a chosen value
           sees a clean non-answer (never a stray false that a `=== 'x'` check might
           treat as a pick). A dialog may opt out with `dismissable: false`. While a
           login browser is in flight (cookieJob.active) dismissal is refused — those
           Done/Cancel buttons are the only safe exit, or the login window orphans. */
        var dismissable = opts.dismissable !== false;
        // The drawn close (X) can be hidden independently of backdrop/Esc: an
        // information dialog (采集建议) or one that already has its own buttons
        // (the Profile-clash prompt) reads cleaner without a corner X, yet stays
        // dismissable by clicking outside or Esc.
        // The corner X is opt-in: only an information dialog with no buttons of its
        // own (采集建议) needs it. Every other dialog already carries its own action
        // buttons, so it stays X-free; backdrop/Esc still dismiss any dialog.
        var showClose = opts.showClose === true && dismissable;
        var cancelValue = opts.cancelValue !== undefined ? opts.cancelValue : null;
        var dismissed = false;
        var closeBtn = null;
        var trap = null;
        function onBackdrop(e) {
            if (e.target === overlay && !cookieJob.active) {
                // Do not let this click reach the top-menu outside-click handler,
                // which would also collapse the submenu the dialog was opened from.
                e.stopPropagation();
                resolve(cancelValue);
            }
        }
        function onEsc(e) { if (e.key === 'Escape' && !cookieJob.active) resolve(cancelValue); }
        function resolve(value) {
            if (dismissed) return;
            dismissed = true;
            overlay.classList.remove('open');
            overlay.removeEventListener('click', onBackdrop);
            document.removeEventListener('keydown', onEsc);
            if (trap) document.removeEventListener('keydown', trap);
            if (closeBtn && closeBtn.parentNode) closeBtn.parentNode.removeChild(closeBtn);
            _resolve(value);
        }

        msgEl.textContent = opts.message || '';
        actionsEl.innerHTML = '';
        inputArea.style.display = 'none';
        listArea.style.display = 'none';
        listArea.innerHTML = '';

        if (opts.input) {
            inputArea.style.display = 'block';
            inputEl.value = opts.input.value || '';
            inputEl.placeholder = opts.input.placeholder || '';
        }

        if (opts.list) {
            listArea.style.display = 'block';
            opts.list.forEach(function (item) {
                var btn = document.createElement('button');
                btn.className = 'dialog-list-item';
                btn.textContent = item;
                btn.addEventListener('click', function () {
                    overlay.classList.remove('open');
                    resolve(item);
                });
                listArea.appendChild(btn);
            });
        }

        /* A small form — checkboxes and one field or two — rendered into the
           dialog instead of a bare button set (the report dialog is its only
           user). Each control is read back by its own id, never by querying the
           container, so a caller or a test can drive one switch on its own. A
           toggle is a boolean the user chose; "which sections" and "how many
           rows" therefore do not have to be enumerated as button combinations. */
        var toggleIds = (opts.toggles || []).map(function (t) { return t.id; });
        var fieldIds = (opts.fields || []).map(function (f) { return f.id; });
        if (toggleIds.length) {
            listArea.style.display = 'block';
            opts.toggles.forEach(function (t) {
                var label = document.createElement('label');
                label.className = 'dialog-toggle';
                var box = document.createElement('input');
                box.type = 'checkbox';
                box.id = t.id;
                box.checked = t.checked !== false;
                label.appendChild(box);
                label.appendChild(document.createTextNode(' ' + t.label));
                listArea.appendChild(label);
            });
        }
        if (fieldIds.length) {
            listArea.style.display = 'block';
            var fieldRows = {};
            opts.fields.forEach(function (f) {
                var row = document.createElement('label');
                row.className = 'dialog-field';
                row.appendChild(document.createTextNode(f.label));
                var box;
                if (f.type === 'select') {
                    /* A dropdown field: the smart-clear run/node pickers. ``collectForm`` reads
                       every field by ``.value``, which a <select> answers with its chosen option,
                       so the collection path is shared with the number/text fields unchanged. */
                    box = document.createElement('select');
                    box.className = 'settings-input';
                    box.id = f.id;
                    (f.options || []).forEach(function (opt) {
                        var o = document.createElement('option');
                        o.value = opt.value;
                        o.textContent = opt.label;
                        box.appendChild(o);
                    });
                    if (f.value !== undefined) box.value = f.value;
                } else {
                    box = document.createElement('input');
                    /* The report dialog's 行数 box is a number input; without the house class it
                       rendered as OS chrome (a bevelled white box) beside a text input that already
                       wears .settings-input, so one form had two skins. Same class, same border,
                       same focus ring, transparent ground — the number spinners are already stripped
                       by the global ``input[type=number]`` rule. */
                    box.className = 'settings-input';
                    box.type = f.type || 'number';
                    box.id = f.id;
                    if (f.value !== undefined) box.value = f.value;
                    if (f.min !== undefined) box.min = f.min;
                    if (f.max !== undefined) box.max = f.max;
                }
                row.appendChild(box);
                listArea.appendChild(row);
                fieldRows[f.id] = row;
            });
            /* A field may declare which values of ANOTHER field it belongs to (the schedule
               editor: a time only means something for daily/weekly, a cron expression only for
               cron). Without this every trigger kind showed every box, and the ones that did not
               apply were silently ignored on save — a form asking for four answers to one
               question. The rule is read from the live select, so switching 触发方式 re-filters. */
            var dependent = (opts.fields || []).filter(function (f) {
                return f.onlyWhen && f.onlyWhen.field;
            });
            function applyFieldVisibility() {
                dependent.forEach(function (f) {
                    var row = fieldRows[f.id];
                    var source = document.getElementById(f.onlyWhen.field);
                    if (!row || !source) return;
                    var wanted = f.onlyWhen.values || [];
                    row.style.display = wanted.indexOf(source.value) >= 0 ? '' : 'none';
                });
            }
            dependent.forEach(function (f) {
                var source = document.getElementById(f.onlyWhen.field);
                if (source && !source.dataset._onlyWhenBound) {
                    source.dataset._onlyWhenBound = '1';
                    source.addEventListener('change', applyFieldVisibility);
                }
            });
            applyFieldVisibility();
        }
        function collectForm() {
            var toggles = {};
            toggleIds.forEach(function (id) {
                var el = document.getElementById(id);
                toggles[id] = !!(el && el.checked);
            });
            var fields = {};
            fieldIds.forEach(function (id) {
                var el = document.getElementById(id);
                fields[id] = el ? el.value : '';
            });
            return { toggles: toggles, fields: fields };
        }

        if (opts.buttons) {
            opts.buttons.forEach(function (b) {
                var btn = document.createElement('button');
                btn.className = 'menu-btn' + (b.primary ? ' toggle-on' : '');
                btn.textContent = b.label;
                btn.addEventListener('click', function () {
                    overlay.classList.remove('open');
                    /* A dialog that asks for a text AND offers two ways to use it
                       (the report: plain, or with an AI conclusion) would
                       otherwise lose one of them — resolving a declared `value`
                       throws the typed text away, and resolving the text loses
                       which button was pressed. `withInput` returns both, and
                       `collect` returns the checkbox / field states on top. */
                    if (b.collect) {
                        var got = collectForm();
                        resolve({
                            value: b.value,
                            input: opts.input ? inputEl.value : undefined,
                            toggles: got.toggles,
                            fields: got.fields,
                        });
                        return;
                    }
                    if (b.withInput && opts.input) {
                        resolve({ value: b.value, input: inputEl.value });
                        return;
                    }
                    resolve(b.value !== undefined ? b.value : (opts.input ? inputEl.value : true));
                });
                actionsEl.appendChild(btn);
            });
        }

        var box = document.getElementById('dialog-box');
        if (box) {
            var stale = box.querySelector('.dialog-close');
            if (stale) stale.parentNode.removeChild(stale);
        }
        if (showClose && box) {
            closeBtn = document.createElement('button');
            closeBtn.className = 'dialog-close';
            closeBtn.type = 'button';
            closeBtn.setAttribute('data-i18n-title', 'settings.close');
            closeBtn.setAttribute('aria-label', 'Close');
            closeBtn.innerHTML =
                '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">' +
                '<path d="M6 6l12 12M18 6L6 18"/></svg>';
            closeBtn.addEventListener('click', function (e) {
                if (e) e.stopPropagation();
                if (cookieJob.active) return;
                resolve(cancelValue);
            });
            // Insert first so DOM order matches the visual corner position too,
            // not just the absolute CSS placement.
            box.insertBefore(closeBtn, box.firstChild);
        }
        if (dismissable) {
            overlay.addEventListener('click', onBackdrop);
            document.addEventListener('keydown', onEsc);
        }
        /* Modal accessibility: role/aria-modal/aria-labelledby mark the box as a real modal so a
           screen reader announces it and not the background, and a Tab trap keeps the caret among
           the dialog's own controls while it is open. The initial focus moves INTO the dialog so a
           keyboard user is not left behind on the page body (an input dialog is focused below). */
        if (box) {
            box.setAttribute('role', 'dialog');
            box.setAttribute('aria-modal', 'true');
            if (msgEl && msgEl.id) box.setAttribute('aria-labelledby', msgEl.id);
        }
        function dialogFocusables() {
            if (!box) return [];
            return box.querySelectorAll('button, [href], input, select, textarea, [tabindex]');
        }
        function onDialogTab(e) {
            if (e.key !== 'Tab') return;
            var items = dialogFocusables();
            if (!items.length) return;
            var first = items[0];
            var last = items[items.length - 1];
            if (e.shiftKey && e.target === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && e.target === last) { e.preventDefault(); first.focus(); }
        }
        document.addEventListener('keydown', onDialogTab);
        trap = onDialogTab;
        if (!opts.input) {
            var _first = dialogFocusables();
            if (_first.length) _first[0].focus();
        }
        overlay.classList.add('open');
        if (opts.input) setTimeout(function () { inputEl.focus(); inputEl.select(); }, 100);
    });
}

/* Every cookie-panel call shares one guard: a refused connection (the debug
   server restarting) or an HTML error page used to surface as
   'Uncaught (in promise) TypeError: Failed to fetch' in the console and
   nothing on screen. This always resolves to a plain {ok, error} object —
   callers only render. */
function fetchJSON(url, options) {
    return fetch(url, options)
        .then(function (r) {
            return r.text().then(function (txt) {
                var body = null;
                try { body = txt ? JSON.parse(txt) : null; } catch (e) { body = null; }
                if (body && typeof body === 'object') return body;
                return { ok: false, error: 'HTTP ' + r.status };
            });
        })
        .catch(function (e) {
            return { ok: false, error: (e && e.message) || String(e), unreachable: true };
        });
}

