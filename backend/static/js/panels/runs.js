/* The run console and the run records: what the server streamed, and what it kept.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-29) byte for byte, in four pieces that were
 * interleaved with the canvas code. The console keeps its own history per view because the server
 * can only give back the last 200 lines of the whole run; the records panel lists every recorded
 * run, including the orphans the resume banner can no longer match.
 */

/* How far the browser has read in the run console, and what each view has shown.
 *
 * The status endpoint ships the last 200 lines plus the true total, and "which
 * lines are new" is derived from that pair. Two things can strand the console: a
 * run that passes 200 lines (the total solves it), and the server restarting its
 * buffer when the NEXT run begins — the total then drops BELOW the index already
 * consumed, and a plain slice returns nothing for the rest of the run, which is
 * how the console used to freeze after a second Run. `takeLines` is the single
 * place that reads both cases.
 *
 * The second half of this state is the reason a tab switch stopped emptying the
 * box: the server holds only the tail of the *whole* run, so a view cannot be
 * rebuilt from a later response. Each view therefore keeps the lines it has
 * already shown, which is what lets 切换工作流标签页 repaint the tab it enters
 * instead of showing nothing until the next line arrives. */
var CONSOLE_VIEW_CAP = 500;
var consoleViews = { all: { seen: 0, lines: [] }, wf: {} };
function consoleViewFor(key) {
    if (key === 'all') return consoleViews.all;
    if (!consoleViews.wf[key]) consoleViews.wf[key] = { seen: 0, lines: [] };
    return consoleViews.wf[key];
}

function takeLines(lines, total, seen) {
    var held = lines || [];
    var count = total === undefined || total === null ? held.length : total;
    var seenAt = count < seen ? 0 : seen;
    var dropped = Math.max(0, count - held.length);
    return held.slice(Math.max(0, seenAt - dropped));
}

/** Advance one view over the answer it just received.
 *
 * Returns the lines that are new to this view and whether its history had to be
 * trimmed. Every view is fed on every poll — including the tab nobody is looking
 * at — because a tab that is only read when it becomes visible has nothing to
 * show the moment the user clicks it. */
function feedConsoleView(view, lines, total) {
    var fresh = takeLines(lines, total, view.seen);
    var held = lines || [];
    view.seen = total === undefined || total === null ? held.length : total;
    if (!fresh.length) return { fresh: fresh, trimmed: false };
    view.lines = view.lines.concat(fresh);
    var trimmed = false;
    if (view.lines.length > CONSOLE_VIEW_CAP) {
        view.lines = view.lines.slice(view.lines.length - CONSOLE_VIEW_CAP);
        trimmed = true;
    }
    return { fresh: fresh, trimmed: trimmed };
}

function appendConsoleLines(out, lines) {
    (lines || []).forEach(function (log) {
        var line = document.createElement('div');
        line.className = 'console-line';
        line.textContent = log;
        out.appendChild(line);
    });
}

/** Rebuild the box from the view's own history (a tab switch, or a trim).
 *
 *  ``stick`` is why the trim is not automatically a scroll: a view at its cap trims on EVERY
 *  later line, so rebuilding it with the caret pinned to the bottom yanked a user who had
 *  scrolled up to read the crawl back down once per second — and wiped whatever they had
 *  selected. The caller decides; a tab switch keeps its own meaning of "show me this now". */
function repaintConsoleView(out, key, stick) {
    out.textContent = '';
    appendConsoleLines(out, consoleViewFor(key).lines);
    if (stick !== false) {
        out.scrollTop = out.scrollHeight;
    }
}

/* What a refreshed page asks the server for on its first read. The buffer behind
 * `?tail=` is LOG_KEEP lines (backend `app.py`); the browser then keeps what its own
 * view keeps (CONSOLE_VIEW_CAP) — the ask is "give me back what I lost", the cap is a
 * DOM-size decision, and the two are different questions. */
var CONSOLE_REPLAY_LIMIT = 5000;

/** Load one view from a replay, and mark EVERY line the server has ever produced as seen.
 *
 * A fresh page starts at `seen: 0` while the run it is reconnecting to may be at line
 * four thousand. Filling `lines` from the replay is only half of it: the cursor has to
 * land on the reported total as well, or the very next poll — which ships the last 200 —
 * would hand back lines this view has just painted and print them a second time.
 * `takeLines` reads the pair, so the pair must be right. */
function replayConsoleView(view, lines, total) {
    var held = lines || [];
    var count = total === undefined || total === null ? held.length : total;
    view.seen = count;
    view.lines = held.length > CONSOLE_VIEW_CAP ? held.slice(held.length - CONSOLE_VIEW_CAP) : held.slice();
    return view.lines;
}

/* The console's workflow tabs, built in one place. A page that reconnects mid-run has to
 * rebuild them from a status read rather than from a poll it never started, and a copy of
 * this markup in the reconnect path is a bar that drifts from the one the user looks at. */
function consoleTabsHtml(result, activeTab) {
    var html = '<div class="console-tab' + (activeTab === 'all' ? ' active' : '') +
        '" data-wf="all" onclick="switchWfTab(\'all\')">\u25a0 ' + I18n.t('console.all') + '</div>';
    (result.workflows || []).forEach(function (wf) {
        var dotClass = 'tab-dot-idle';
        if (result.running) dotClass = 'tab-dot-run';
        else dotClass = 'tab-dot-done';
        html += '<div class="console-tab' + (activeTab === wf.id ? ' active' : '') + '" data-wf="' + wf.id +
            '" onclick="switchWfTab(' + wf.id + ')">' +
            '<span class="tab-dot ' + dotClass + '"></span>' + escapeHtml(wf.name || ('#' + (wf.id + 1))) + '</div>';
    });
    return html;
}

function consoleHasMultipleWf(result) {
    return !!(result.workflows && result.workflows.length > 1 && result.mode === 'parallel');
}
function toggleConsole() {
    var panel = document.getElementById('console-panel');
    if (!panel.classList.contains('open')) {
        /* Opening the console from the button must clear the other two docked
           panels; only run-records was cleared before, so 导出产物 stayed open
           underneath and the two overlapped. */
        closeDockedPanels('console-panel');
    }
    if (panel.classList.contains('popout')) {
        toggleConsolePopout(); /* Dock first, then close */
        panel.classList.remove('open');
    } else {
        panel.classList.toggle('open');
        if (!panel.classList.contains('open')) {
            /* Dropping .open only shrinks the panel if nothing overrides the
               CSS `height: 0` — the dock resize handle writes an inline
               height, and that inline value survives the class toggle. Clear
               it, or Close looks dead after the user resized the panel. */
            panel.style.height = '';
        }
    }
    /* The two panels share the same bottom slot; opening one closes the other. */
    if (panel.classList.contains('open') && window.runsManager) runsManager.close();
}

function toggleRunsPanel() {
    runsManager.toggle();
}

function clearConsole() {
    document.getElementById('console-output').innerHTML = '';
    /* Every view's history goes with it, and no cursor moves: "clear" means the
       user wants the NEXT line, not a replay of the up-to-200 the server still
       holds. Leaving one view's lines behind would have a tab switch repaint what
       was just deleted, which is the opposite of clearing. */
    consoleViews.all.lines = [];
    Object.keys(consoleViews.wf).forEach(function (key) {
        consoleViews.wf[key].lines = [];
    });
    _wfActiveTab = 'all';
}

/* #177 — the "clear console before each run" option asks for a hard blank slate, not
   the soft one clearConsole gives: a new run must not briefly show the PREVIOUS run's
   per-workflow tabs. So the tab bar itself and every cursor go too. pollStatus rebuilds
   tabs from the fresh run's data, and resetting `all.seen` to 0 is exactly the "server
   buffer was zeroed, read from the start" state the poll already handles. */
function resetConsoleForNewRun() {
    var out = document.getElementById('console-output');
    if (out) out.innerHTML = '';
    var tabs = document.getElementById('console-tabs');
    if (tabs) tabs.innerHTML = '';
    consoleViews.all = { seen: 0, lines: [] };
    consoleViews.wf = {};
    _wfActiveTab = 'all';
}

function _clearConsoleBeforeRun() {
    /* AppSettings is a top-level const (never on window), so guard the binding itself.
       Unpulled settings answer false — a console nobody configured stays as before. */
    return typeof AppSettings !== 'undefined' &&
        !!(AppSettings._values && AppSettings._values.clear_console_before_run);
}
/* ── Run records manager ──────────────────────────────────────
   Every recorded run — including orphans the resume banner can no longer
   match (the workflow was rewired or deleted since). Each row offers the
   three things the banner offers and one it can't: continue, restart from
   scratch, delete outright, and a per-node breakdown. The panel itself is
   docked at the bottom of the window, console-style. */
var runsManager = {
    /* 当前工作流 is the default view: it answers "which results can this canvas
       load?" without making the user scan every unrelated record. '' until the
       panel first opens. */
    _tab: 'workflow',

    panel() {
        return document.getElementById('runs-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        var opening = !panel.classList.contains('open');
        /* Same bottom slot as the console and the export list — none stack. */
        if (opening) {
            closeDockedPanels('runs-panel');
            panel.classList.add('open');
            this.refresh();
        } else {
            this.close();
        }
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        /* Same trap as the console: the resize handle leaves an inline height
           behind, and an inline height overrides the CSS `height: 0` — the
           panel would refuse to shrink after being resized. */
        panel.style.height = '';
    },

    async refresh() {
        var body = document.getElementById('runs-mgr-body');
        if (!body) return;
        this.renderTabs();
        try {
            var result;
            if (this._tab === 'workflow') {
                /* A POST because the question is "which runs belong to THIS canvas",
                   and the answer is its structure fingerprint. A GET with the whole
                   workflow in a query string is not an option. */
                var wf = typeof canvas !== 'undefined' && canvas ? canvas.toWorkflowJSON() : null;
                if (!wf || !wf.nodes || !wf.nodes.length) {
                    this._lastRuns = [];
                    this._queue = [];
                    this.render([]);
                    this._detail = null;
                    return;
                }
                var resp = await fetch('/api/runs/for-workflow', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ workflow: wf, limit: 50 }),
                });
                result = await resp.json();
            } else {
                var allResp = await fetch('/api/runs/list?limit=50');
                result = await allResp.json();
            }
            this._lastRuns = (result.ok && result.runs) || [];
            /* Waiting requests come back with the records: the panel that shows
               what has run is where someone looks for what has not started. */
            this._queue = (result.ok && result.queue) || [];
            this._detail = null;
            this._compare = null;
            this.render(this._lastRuns);
        } catch (e) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('runsMgr.empty') + '</div>';
        }
    },

    /* The two views are different questions, so they are tabs rather than one table
       with a filter: 当前工作流 is "load a result into this canvas", 全部记录 is
       "manage every run this machine ever made". */
    renderTabs() {
        var tabs = document.getElementById('runs-tabs');
        if (!tabs) return;
        var current = this._tab === 'workflow';
        var count = (this._lastRuns || []).length;
        var label = function (key, isActive) {
            return (
                '<div class="runs-tab' + (isActive ? ' active' : '') +
                '" role="tab" aria-selected="' + (isActive ? 'true' : 'false') +
                '" onclick="runsManager.switchTab(\'' + key + '\')">' +
                I18n.t(key === 'workflow' ? 'runsMgr.tabWorkflow' : 'runsMgr.tabAll') +
                (isActive && count ? ' (' + count + ')' : '') +
                '</div>'
            );
        };
        tabs.innerHTML = label('workflow', current) + label('all', !current);
    },

    switchTab(tab) {
        var next = tab === 'all' ? 'all' : 'workflow';
        if (next === this._tab) return;
        this._tab = next;
        this._detail = null;
        this._compare = null;
        this._lastRuns = [];
        this._shown = [];
        this.refresh();
    },

    refreshIfOpen() {
        var panel = this.panel();
        if (panel && panel.classList.contains('open')) this.refresh();
    },

    /* Follow a live run without the user opening anything: while the console sees
       `running`, the panel that lists runs keeps itself current so the row appears
       and advances on its own. It stays silent when the panel is closed (no polling
       a panel nobody is reading) and while a detail row is expanded — re-rendering
       there would yank the very table the user is reading out from under them. */
    autoRefresh() {
        if (this._detailOpen()) return;
        this.refreshIfOpen();
    },

    _detailOpen() {
        /* The flag, not a DOM probe: render() replaces the whole table, so an
           expanded row can only have come from the last render — and every path
           that wipes rows (a manual refresh, a re-render) clears the flag with
           them. A real `querySelector` here would ask the page a question the
           panel's own bookkeeping already answers truthfully. A comparison row
           is the same kind of transient detail and pauses auto-refresh too. */
        return !!this._detail || !!this._compare;
    },

    /* Any listed record still claiming that no verdict has been written for it.
       Right after 停止 this is true twice over: the row says 正在停止 because the Stop
       request wrote that itself, and the worker may still be unwinding behind it.
       Neither is a finished record, so `awaitSettled` keeps reading through both —
       counting only 'running' made the panel stop watching at the exact moment the
       record had just left that status. */
    _awaitable() {
        return (this._shown || []).some(function (r) {
            return r.status === 'running' || r.status === 'stopping';
        });
    },

    /* Keep re-reading after a stop until the record has actually settled. Bounded so
       a wedged worker cannot make the panel poll forever; a missed flip is repaired
       the moment the panel is next opened. The bound is minutes rather than seconds
       because the worker may be inside a page load it cannot be pulled out of, and
       this is the only thing that turns 正在停止 into the run's real verdict without
       the user touching anything.

       The watch has to outlast the longest tail the worker can be inside, which is
       measured, not guessed (docs/crawler_notes.md): a model request gives up at its
       own 300 s timeout and the retry ladder runs it again — 600 s — while a crawl cut
       short by killing its driver lands in about 5 to 30 s. A 120 s watch expired in
       the middle of that, freezing the row at 正在停止 until somebody opened it again.
       `tries` is derived from the watch budget and the step actually used, so passing a
       shorter `waitMs` (a test does) cannot silently shorten the watch too. */
    async awaitSettled(tries, waitMs) {
        var step = waitMs || runsManager.SETTLE_POLL_MS;
        var n = tries || Math.ceil(runsManager.SETTLE_WATCH_MS / step);
        for (var i = 0; i < n; i++) {
            await new Promise(function (done) { setTimeout(done, step); });
            if (this._detailOpen()) continue;
            /* Awaited, and the flag read from THAT answer: `refreshIfOpen()` fires the
               request without waiting, so a poll that asked `_shown` immediately
               after was judging the PREVIOUS read — which could end the watch the
               moment it started, on a list captured before this run existed. */
            await this.refresh();
            if (!this._awaitable()) break;
        }
    },

    /* Poll interval and total watch of the loop above, as data: the frontend test pins
       that the watch outlasts the measured model tail, which a literal buried in a call
       argument could not be checked against. */
    SETTLE_POLL_MS: 500,
    SETTLE_WATCH_MS: 660000,

    /* The waiting list, drawn above the finished records. Each row can only be
       cancelled — starting it sooner would break the one-writer rule the whole
       checkpoint design rests on. */
    _queueBlock() {
        var queue = this._queue || [];
        if (!queue.length) return '';
        var rows = queue.map(function (entry, index) {
            return '<tr>' +
                '<td>' + (index + 1) + '</td>' +
                '<td class="runs-mgr-wf">' + escapeHtml(entry.workflow_name || I18n.t('name.unnamed')) + '</td>' +
                '<td>' + escapeHtml(String(entry.nodes || 0)) + '</td>' +
                '<td class="runs-mgr-time">' + escapeHtml(entry.queued_at || '') + '</td>' +
                '<td class="runs-mgr-ops"><button class="runs-mgr-btn del" onclick="runsManager.cancelQueued(\'' +
                entry.id + '\')">' + I18n.t('runsMgr.queueCancel') + '</button></td>' +
                '</tr>';
        }).join('');
        return '<div class="runs-mgr-empty">' +
            I18n.t('runsMgr.queueHeader').replace('{n}', queue.length) +
            '</div><table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>#</th><th>' + I18n.t('runsMgr.colWorkflow') + '</th>' +
            '<th>' + I18n.t('runsMgr.colNodes') + '</th>' +
            '<th>' + I18n.t('runsMgr.colStarted') + '</th><th></th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>';
    },

    async cancelQueued(queueId) {
        try {
            var resp = await fetch('/api/workflow/queue/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: queueId }),
            });
            var result = await resp.json();
            showToast(result.removed ? I18n.t('runsMgr.queueCancelled') : I18n.t('runsMgr.queueGone'));
        } catch (e) {
            showToast(I18n.t('runsMgr.queueCancelFailed'));
        }
        this.refresh();
    },

    /* Language switch: the table text is JS-built, so an open panel must be
       redrawn now. Re-render from the cached rows — no refetch needed, the
       data itself did not change, only its wording. */
    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        this.renderTabs();
        if (this._lastRuns) this.render(this._lastRuns);
        else this.refresh();
    },

    statusKey(status) {
        /* `stopping` is a status the record really holds: the Stop request writes it
           before the worker's verdict can arrive, so without this line the row would
           read 已完成 for the few seconds it is being stopped. */
        var known = ['running', 'stopping', 'interrupted', 'completed', 'failed', 'abandoned'];
        if (known.indexOf(status) >= 0) {
            return 'runsMgr.status.' + status;
        }
        /* Nothing here is 已完成 by default. A status this build has no word for came
           from somewhere else — an older row, a hand-edited database — and answering
           it with the friendly verdict states a fact the record never said. `I18n.t`
           returns an unknown key verbatim, so the row shows the stored word. */
        return String(status || '');
    },

    /* What kind of run this was, as chips beside the name: several workflows in one
       record (并行), and which window it crawled in. Both are stored facts, not
       guesses — and they matter when a record from last week is being read back:
       a visible-window crawl and a headless one fail differently. */
    tags(r) {
        var out = [];
        var count = r.wf_count || 1;
        if (count > 1 || r.mode === 'serial') {
            /* The mode is the fact; the count alone is not. A canvas can hold several
               workflows and still be run 串行, and labelling that 并行 claims a
               concurrency that never happened. Conversely a serial run IS one workflow
               per record, so its row says 串行 ×1 — the user asked for the mode to be
               stated even for a single one, not silently dropped. 并行 keeps needing
               count>1, because a lone workflow ran with no concurrency to report. */
            var key = r.mode === 'parallel' ? 'runsMgr.tagParallel' : 'runsMgr.tagSerial';
            out.push(I18n.t(key).replace('{n}', count));
        }
        /* 无头 / 窗口 says exactly what ran: a headless Chrome now carries a desktop
           fingerprint (#148), so nothing ever forces a real window into a run the user
           asked to keep headless. The record's requested value IS what ran, and no
           mixed 「无头→窗口」 chip is needed. */
        out.push(I18n.t(r.headless ? 'runsMgr.tagHeadless' : 'runsMgr.tagWindow'));
        /* Which workflows the record deliberately did NOT run. The console said it once
           at the time; a record read back last week has to carry the same answer, or a
           skipped workflow looks like it failed or was deleted. */
        if (r.skipped_workflows) {
            out.push(I18n.t('runsMgr.skipped').replace('{names}', r.skipped_workflows));
        }
        return out;
    },

    render(runs) {
        /* Remembered so a button can ask "which workflow is this row?" without
           the answer having to be woven into its onclick attribute. */
        this._shown = runs || [];
        /* The table is about to be replaced; a comparison row cannot survive it. */
        this._compare = null;
        var body = document.getElementById('runs-mgr-body');
        var count = document.getElementById('runs-mgr-count');
        if (!body) return;
        if (count) count.textContent = runs.length ? '(' + runs.length + ')' : '';
        /* Drawn first and kept in both branches: a queue can exist on a machine
           that has no finished records at all, and hiding it there would hide
           the one request the user is waiting for. */
        var queue = this._queueBlock();
        /* Which record the canvas is showing, said once above the table as well as
           on its row: after scrolling a long history the row is off screen, and the
           question the tab exists to answer would need a hunt. */
        var loadedId = typeof runResults !== 'undefined' ? runResults.runId : '';
        var loadedRow = runs.filter(function (r) {
            return r.run_id === loadedId;
        })[0];
        var loadedNote = loadedId
            ? '<div class="runs-mgr-loaded">' +
              escapeHtml(
                  I18n.t('runsMgr.loadedNote')
                      .replace('{when}', (loadedRow && loadedRow.started_at) || loadedId)
                      .replace('{rid}', loadedId)
              ) +
              '</div>'
            : '';
        if (!runs.length) {
            body.innerHTML =
                queue +
                loadedNote +
                '<div class="runs-mgr-empty">' +
                I18n.t(this._tab === 'workflow' ? 'runsMgr.emptyWorkflow' : 'runsMgr.empty') +
                '</div>';
            this.renderTabs();
            return;
        }
        var rows = runs.map(function (r) {
            var resumable = !!r.resumable;
            var isLoaded = typeof runResults !== 'undefined' && runResults.isLoaded(r.run_id);
            /* Only 当前工作流 offers 载入: its rows are guaranteed to belong to this
               canvas's node ids. An unrelated record in 全部记录 stays manageable
               (continue/delete/report) but cannot silently graft its table here. */
            var ops = '';
            if (runsManager._tab === 'workflow') {
                ops +=
                    '<button class="runs-mgr-btn' + (isLoaded ? ' loaded' : '') +
                    '" onclick="runsManager.loadRun(\'' + r.run_id + '\')">' +
                    I18n.t(isLoaded ? 'runsMgr.reloadResult' : 'runsMgr.loadResult') +
                    '</button>';
            }
            if (resumable) {
                ops += '<button class="runs-mgr-btn" onclick="runsManager.continueRun(\'' + r.run_id + '\')">' + I18n.t('runsMgr.resume') + '</button>';
                ops += '<button class="runs-mgr-btn" onclick="runsManager.restart(\'' + r.run_id + '\')">' + I18n.t('runsMgr.restart') + '</button>';
            }
            if (runsManager._tab === 'workflow' && runs.length > 1) {
                ops += '<button class="runs-mgr-btn" onclick="runsManager.compare(\'' + r.run_id + '\')">' +
                    I18n.t('runsMgr.compare') + '</button>';
            }
            ops += '<button class="runs-mgr-btn del" onclick="runsManager.remove(\'' + r.run_id + '\', ' + (resumable ? 'true' : 'false') + ')">' + I18n.t('runsMgr.remove') + '</button>';
            ops += '<button class="runs-mgr-btn" onclick="runsManager.detail(\'' + r.run_id + '\')">' + I18n.t('runsMgr.detail') + '</button>';
            ops += lockButtonHtml('runs', r.run_id);
            /* The stored tables are what a report needs, so a run from last week
               is reportable from here. Only the run id travels into the handler:
               a workflow name is user text, and a quote in it would close this
               attribute and start a new one. */
            ops += '<button class="runs-mgr-btn" onclick="runsManager.report(\'' + r.run_id + '\')">' + I18n.t('runsMgr.report') + '</button>';
            /* The console survives in the durable per-run log (run_store.run_log), so a run's
               full output is readable here long after the live tail rolled over or a reload
               cleared it. Only the run id travels into the handler — a name is user text. */
            ops += '<button class="runs-mgr-btn" onclick="runLogViewer.open(\'' + r.run_id + '\')">' + I18n.t('runLog.view') + '</button>';
            var tags = runsManager.tags(r).map(function (text) {
                return '<span class="runs-mgr-tag">' + escapeHtml(text) + '</span>';
            }).join('');
            return '<tr data-run-id="' + escapeHtml(r.run_id) + '" data-run-name="' + escapeHtml(r.workflow_name || '') + '">' +
                '<td class="runs-mgr-wf">' + escapeHtml(r.workflow_name || I18n.t('name.unnamed')) + tags +
                (isLoaded ? '<span class="runs-mgr-tag loaded">' + I18n.t('runsMgr.loaded') + '</span>' : '') +
                '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(r.run_id) + '</td>' +
                '<td><span class="runs-mgr-status st-' + escapeHtml(r.status || '') + '">' + I18n.t(runsManager.statusKey(r.status)) + '</span></td>' +
                '<td>' + (r.node_done || 0) + '/' + (r.node_total || 0) + '</td>' +
                '<td>' + (r.rows_kept || 0) + '</td>' +
                '<td class="runs-mgr-time">' + escapeHtml(r.started_at || '') + '</td>' +
                '<td class="runs-mgr-time">' + escapeHtml(runsManager._formatDuration(r.duration_seconds)) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        body.innerHTML =
            queue +
            loadedNote +
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('runsMgr.colWorkflow') + '</th>' +
            '<th>run_id</th>' +
            '<th>' + I18n.t('runsMgr.colStatus') + '</th>' +
            '<th>' + I18n.t('runsMgr.colNodes') + '</th>' +
            '<th>' + I18n.t('runsMgr.colRows') + '</th>' +
            '<th>' + I18n.t('runsMgr.colStarted') + '</th>' +
            '<th>' + I18n.t('runsMgr.colDuration') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>';
        this.renderTabs();
    },

    _formatDuration: function (seconds) {
        /* Elapsed wall time as a language-neutral clock (MM:SS, H:MM:SS past an hour). A run still in
           flight has no duration_seconds (the backend leaves it null) → a dash, not a fabricated 0. */
        if (seconds === null || seconds === undefined || seconds < 0) return '—';
        var s = Math.floor(seconds);
        var h = Math.floor(s / 3600);
        var m = Math.floor((s % 3600) / 60);
        var sec = s % 60;
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        return h > 0 ? h + ':' + pad(m) + ':' + pad(sec) : pad(m) + ':' + pad(sec);
    },

    _busy() {
        /* Same trap as resumeBar.refresh(): RunState is a `const` in app.js, so
           `window.RunState` was undefined and this returned false even mid-run —
           继续/重新开始 would close the panel and start a second attempt at the same
           data instead of saying "wait". `typeof` keeps the degradation the guard
           was written for (app.js missing) without pretending to read a property
           that does not exist. */
        if (typeof RunState !== 'undefined' && RunState.running) {
            showToast(I18n.t('runsMgr.busy'));
            return true;
        }
        return false;
    },

    /* A report for this stored run. The name is read back out of the rows the
       panel is already holding, because it is only the dialog's starting
       suggestion — it must not have to survive a trip through an inline
       handler, where one quote in a workflow name would close the attribute. */
    report(runId) {
        var row = (this._shown || []).filter(function (r) {
            return r.run_id === runId;
        })[0] || {};
        exportsManager.report(runId, row.workflow_name || '');
    },

    /* Load one record's results into the canvas: node verdicts, previews and every
       chart re-render now read that attempt. This does not run anything — the panel
       stays open so the 已载入 marker is visible where the choice was made. */
    async loadRun(runId) {
        if (typeof runResults === 'undefined' || !runResults.load) return;
        await runResults.load(runId);
        this.render(this._shown || []);
    },

    continueRun(runId) {
        if (this._busy()) return;
        /* Hand the bottom slot back to the console before the run starts. */
        this.close();
        workflow.execute({ resumeRunId: runId });
    },

    async restart(runId) {
        if (this._busy()) return;
        /* The app's own dialog, not window.confirm: a native box cannot be read
           in the interface language, cannot be styled with the rest of the page,
           and answers with a bare true/false that hides what is about to be lost. */
        var go = await showDialog({
            message: I18n.t('runsMgr.confirmRestart'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('runsMgr.restart'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        try {
            /* Same contract as the banner's restart: dropping the run drops
               its "already crawled" claims, or the fresh attempt would see
               everything as already-seen and quietly return fewer rows. */
            await fetch('/api/runs/discard', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: runId }),
            });
        } catch (e) { /* a failed discard still starts the run */ }
        this.close();
        workflow.execute();
    },

    async remove(runId, wasResumable) {
        var go = await showDialog({
            message: I18n.t('runsMgr.confirmRemove'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('runsMgr.remove'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        /* An interrupted run being deleted outright means "never continue
           it": its crawl claims must go too, or those items stay claimed by
           a run that no longer exists. A finished run keeps them — deleting
           its data must not resurrect items as unseen. */
        var url = wasResumable ? '/api/runs/discard' : '/api/runs/delete';
        try {
            var resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: runId }),
            });
            var result = await resp.json();
            showToast(result.ok ? I18n.t('runsMgr.removeDone') : ((result && result.error) || I18n.t('runsMgr.removeFailed')));
        } catch (e) {
            showToast(I18n.t('runsMgr.removeFailed'));
        }
        this.refresh();
        /* Deleting the record whose results are on screen would leave markers and
           previews pointing at a row nobody can read; fall back to the newest run of
           this workflow (or no run at all). */
        if (typeof runResults !== 'undefined' && runResults.isLoaded(runId)) runResults.refresh();
        if (window.resumeBar) resumeBar.refresh();
    },

    /* Emptying the whole list is not "remove" called N times: the backend does it in one
       transaction and, more importantly, hands back the crawl claims of every run it
       deletes — a per-row loop would leave a ledger of "already collected" items pointing
       at rows that are gone, and the next crawl would silently under-deliver. The dialog
       has to say that out loud, because it is the one thing the user cannot un-see. */
    async clearAll() {
        var go = await showDialog({
            message: I18n.t('runsMgr.confirmClearAll'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('runsMgr.clearAll'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        try {
            var resp = await fetch('/api/runs/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify({ confirm: true }),
            });
            var result = await resp.json();
            if (result && result.ok) {
                showToast(I18n.t('runsMgr.clearAllDone').replace('{n}', (result.removed || {}).runs || 0));
            } else {
                showToast(I18n.t('runsMgr.clearAllFailed') + ((result && result.error) ? ': ' + result.error : ''));
            }
        } catch (e) {
            showToast(I18n.t('runsMgr.clearAllFailed'));
        }
        /* Every record is gone, including the one the canvas was reading. */
        if (typeof runResults !== 'undefined') runResults.clear();
        this.refresh();
        if (window.resumeBar) resumeBar.refresh();
    },

    /* Node status → badge colour class + i18n key. Node statuses are their
       own vocabulary (done/partial/skipped/restored …), distinct from the
       run statuses above. */
    nodeStatusInfo(status) {
        var map = {
            done: 'st-completed',
            restored: 'st-completed',
            running: 'st-running',
            partial: 'st-interrupted',
            failed: 'st-failed',
            skipped: 'st-skipped',
            pending: 'st-skipped',
        };
        var known = ['pending', 'running', 'done', 'partial', 'failed', 'skipped', 'restored'];
        var s = String(status || '');
        /* An unfamiliar word is NOT retro-fitted to 已完成: the badge exists to say
           what the record actually claims. It shows the stored token in a neutral
           chip instead, so a status from a newer/older build cannot masquerade as
           success. (Canvas badges treat "not settled" as red — see applyRunStatuses.) */
        if (known.indexOf(s) < 0) return { cls: 'st-unknown', key: s };
        return { cls: map[s], key: 'runsMgr.node.' + s };
    },

    // One definition of "settled", shared with the backend's node_done: a node that
    // only replayed its stored rows is just as finished as one that computed them, and
    // one that failed or starved is not finished at all. The panel counted these two
    // statuses differently from the record until they were tied together.
    nodeDone(status) {
        var s = String(status || '');
        return s === 'done' || s === 'restored';
    },

    // Group a run's nodes by the workflow (connected component) they ran in, keeping
    // canvas order. One record holds every workflow of a serial run by design, so
    // without this the user could not tell which rows came from which workflow — the
    // complaint that started this. A record with a single group renders as it always
    // did: an unnamed one-workflow canvas does not need a heading over its own nodes.
    nodeGroups(nodes) {
        var groups = [];
        var byIndex = {};
        (nodes || []).forEach(function (n) {
            var idx = Number(n.component || 0);
            if (!byIndex[idx]) {
                byIndex[idx] = { index: idx, name: String(n.component_name || ''), nodes: [] };
                groups.push(byIndex[idx]);
            }
            byIndex[idx].nodes.push(n);
        });
        groups.sort(function (a, b) {
            return a.index - b.index;
        });
        return groups;
    },

    /* The live <tr> for one run, found by the attribute the table stamps it with — never
       by a selector built from the id, which would ask the page to parse user data. */
    _rowFor(runId) {
        var body = document.getElementById('runs-mgr-body');
        if (!body) return null;
        var rows = body.querySelectorAll('tr');
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].dataset && String(rows[i].dataset.runId) === String(runId)) return rows[i];
        }
        return null;
    },

    /* ── run-to-run comparison ─────────────────────────────────────
       The server owns the diff (DataAnalysisService.diff); this panel only asks
       which run to compare with, then draws the node summary and the chosen
       node's added/removed samples. A comparison row lives beside the run row
       that started it and survives until closed or the table is refreshed. */
    async compare(runId) {
        var others = (this._shown || []).filter(function (row) { return row.run_id !== runId; });
        if (!others.length) {
            showToast(I18n.t('runsMgr.compareNeedOther'));
            return;
        }
        var labels = others.map(function (row) {
            return row.run_id + ' · ' + (row.started_at || '') + ' · ' + (row.workflow_name || '');
        });
        var chosen = await showDialog({
            message: I18n.t('runsMgr.comparePick'),
            list: labels,
            buttons: [{ label: I18n.t('dialog.cancel'), value: null }],
        });
        if (!chosen) return;
        var other = others[labels.indexOf(chosen)];
        if (!other) return;
        try {
            var resp = await fetch(
                '/api/runs/compare?a=' + encodeURIComponent(runId) + '&b=' + encodeURIComponent(other.run_id)
            );
            var result = await resp.json();
            if (!resp.ok || !result.ok || !result.diff) {
                showToast((result && result.error) || I18n.t('runsMgr.compareFailed'));
                return;
            }
            this.closeCompare();
            var row = this._rowFor(runId);
            if (!row) return;
            this._compare = result.diff;
            var tr = document.createElement('tr');
            tr.id = 'runs-mgr-compare';
            tr.innerHTML = '<td colspan="8" class="runs-mgr-detail runs-compare">' +
                this._compareHtml(result.diff) + '</td>';
            row.parentNode.insertBefore(tr, row.nextSibling);
        } catch (e) {
            showToast(I18n.t('runsMgr.compareFailed'));
        }
    },

    closeCompare() {
        var row = document.getElementById('runs-mgr-compare');
        if (row && row.parentNode) row.parentNode.removeChild(row);
        this._compare = null;
    },

    _compareValue(value) {
        if (value === null || value === undefined) return '';
        var text = typeof value === 'object' ? JSON.stringify(value) : String(value);
        return text.length > 80 ? text.slice(0, 77) + '...' : text;
    },

    _compareSamples(titleKey, rows, total, columns) {
        if (!total) return '';
        var cols = (columns || []).slice(0, 8);
        if (!cols.length && rows && rows.length) cols = Object.keys(rows[0]).slice(0, 8);
        if (!cols.length) return '';
        var head = cols.map(function (col) { return '<th>' + escapeHtml(col) + '</th>'; }).join('');
        var body = (rows || []).slice(0, 10).map(function (row) {
            return '<tr>' + cols.map(function (col) {
                return '<td>' + escapeHtml(runsManager._compareValue(row[col])) + '</td>';
            }).join('') + '</tr>';
        }).join('');
        var shown = Math.min((rows || []).length, 10);
        var more = total > shown ? ' ' + I18n.t('runsMgr.compareMore', { n: total - shown }) : '';
        return '<div class="runs-compare-samples">' +
            '<div class="runs-compare-subtitle">' + I18n.t(titleKey) + ' (' + total + ')' + escapeHtml(more) + '</div>' +
            '<div class="runs-compare-scroll">' +
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' + head + '</tr></thead><tbody>' +
            body + '</tbody></table></div></div>';
    },

    _compareHtml(diff) {
        var self = this;
        var notes = [];
        if (!diff.same_workflow) notes.push(I18n.t('runsMgr.compareWorkflowDiff'));
        if (!diff.same_shape) notes.push(I18n.t('runsMgr.compareShapeDiff'));
        if (diff.key_used) notes.push(I18n.t('runsMgr.compareKeyUsed', { key: diff.key_used }));
        var nodes = (diff.nodes || []).map(function (node) {
            var left = self.nodeStatusInfo(node.status_a);
            var right = self.nodeStatusInfo(node.status_b);
            return '<tr>' +
                '<td class="runs-mgr-wf">' + escapeHtml(node.title || node.node_id) +
                '<span class="wf-snap-source">' + escapeHtml(node.node_id) + '</span></td>' +
                '<td>' + escapeHtml(I18n.t(left.key)) + ' → ' + escapeHtml(I18n.t(right.key)) + '</td>' +
                '<td>' + node.rows_a + ' → ' + node.rows_b + '</td>' +
                '<td>' + (node.row_delta > 0 ? '+' : '') + node.row_delta + '</td>' +
                '</tr>';
        }).join('');
        var node = diff.node || {};
        var table = diff.diff || {};
        var detail = '';
        if (node.node_id) {
            var columns = (table.columns_added || []).concat(table.columns_removed || []);
            var columnNote = columns.length
                ? '<div class="runs-compare-subtitle">' +
                    I18n.t('runsMgr.compareColumns', {
                        added: (table.columns_added || []).join(', ') || '-',
                        removed: (table.columns_removed || []).join(', ') || '-',
                    }) + '</div>'
                : '';
            detail = '<div class="runs-compare-detail">' +
                '<div class="runs-compare-subtitle">' +
                I18n.t('runsMgr.compareNode', { name: node.title || node.node_id }) + '</div>' +
                '<div class="runs-compare-counts">' +
                I18n.t('runsMgr.compareCounts', {
                    added: table.added_count || 0,
                    removed: table.removed_count || 0,
                    changed: table.changed_count || 0,
                }) + '</div>' +
                columnNote +
                (table.key_error ? '<div class="runs-compare-note">' + escapeHtml(table.key_error) + '</div>' : '') +
                this._compareSamples('runsMgr.compareAdded', table.added, table.added_count, table.columns_common) +
                this._compareSamples('runsMgr.compareRemoved', table.removed, table.removed_count, table.columns_common) +
                '</div>';
        }
        return '<div class="runs-compare-head">' +
            '<span class="rm-meta-title">' + I18n.t('runsMgr.compareTitle') + '</span>' +
            '<span class="runs-compare-pair">' + escapeHtml(diff.a.run_id) + ' ↔ ' + escapeHtml(diff.b.run_id) + '</span>' +
            '<button class="runs-mgr-btn" onclick="runsManager.closeCompare()">' +
            I18n.t('runsMgr.compareClose') + '</button></div>' +
            notes.map(function (note) { return '<div class="runs-compare-note">' + escapeHtml(note) + '</div>'; }).join('') +
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('runsMgr.compareColNode') + '</th>' +
            '<th>' + I18n.t('runsMgr.compareColStatus') + '</th>' +
            '<th>' + I18n.t('runsMgr.compareColRows') + '</th>' +
            '<th>' + I18n.t('runsMgr.compareColDelta') + '</th>' +
            '</tr></thead><tbody>' + nodes + '</tbody></table>' +
            detail;
    },

    async detail(runId) {
        var existing = document.getElementById('runs-mgr-detail-' + runId);
        if (existing) {
            existing.remove();
            if (this._detail === runId) this._detail = null;
            return;
        }
        try {
            var resp = await fetch('/api/runs/' + encodeURIComponent(runId));
            var result = await resp.json();
            if (!result.ok || !result.run) return;
            var run = result.run;
            var self = this;

            function cardHtml(n) {
                var info = self.nodeStatusInfo(n.status);
                var typeLabel = nodeTypeWord(n.node_type);
                /* Re-run is offered only on a node that actually produced a reusable
                   result (done/restored with rows). Anything else has nothing downstream
                   could re-key off, so the button would only ever be refused. */
                var canRerun = self.nodeDone(n.status) && (n.row_count || 0) > 0;
                var rerunBtn = canRerun
                    ? '<button class="runs-mgr-btn rm-node-rerun" onclick="workflow.rerunNode(\'' +
                      attrJsArg(n.node_id || '') + '\', \'' + attrJsArg(run.run_id || '') + '\')">' +
                      I18n.t('runsMgr.rerunFrom') + '</button>'
                    : '';
                return '<div class="rm-node nt-' + escapeHtml(n.node_type || 'misc') + '">' +
                    '<div class="rm-node-head">' +
                    '<span class="rm-node-id">' + escapeHtml(n.node_id || '') + '</span>' +
                    '<span class="rm-node-type">' + escapeHtml(typeLabel) + '</span>' +
                    '<span class="runs-mgr-status ' + info.cls + '">' + I18n.t(info.key) + '</span>' +
                    '<span class="rm-node-rows">' + (n.row_count || 0) + ' ' + I18n.t('runsMgr.colRows') + '</span>' +
                    '<span class="rm-node-duration">' + escapeHtml(self._formatDuration(n.duration_seconds)) + '</span>' +
                    rerunBtn +
                    '</div>' +
                    (n.error ? '<div class="rm-node-err">' + escapeHtml(n.error) + '</div>' : '') +
                    '</div>';
            }

            var groups = this.nodeGroups(run.nodes);
            var multi = groups.length > 1;
            var body = groups.map(function (group) {
                var cards = group.nodes.map(cardHtml).join('');
                if (!multi) {
                    return cards;
                }
                var done = group.nodes.filter(function (n) { return self.nodeDone(n.status); }).length;
                var rows = group.nodes.reduce(function (sum, n) { return sum + (n.row_count || 0); }, 0);
                return '<div class="rm-group">' +
                    '<div class="rm-group-head">' +
                    // The name is what the console called this workflow — the backend
                    // stores that same fallback per node, so a group is never left
                    // nameless and the two views can never disagree about one workflow.
                    '<span class="rm-group-name">' + escapeHtml(group.name) + '</span>' +
                    '<span class="rm-group-tally">' +
                    I18n.t('runsMgr.groupDone').replace('{done}', done).replace('{total}', group.nodes.length) +
                    ' · ' + rows + ' ' + I18n.t('runsMgr.colRows') +
                    '</span>' +
                    '</div>' +
                    '<div class="rm-nodes">' + cards + '</div>' +
                    '</div>';
            }).join('');
            var tr = document.createElement('tr');
            tr.id = 'runs-mgr-detail-' + runId;
            tr.innerHTML = '<td colspan="8" class="runs-mgr-detail">' +
                '<div class="rm-meta">' +
                '<span class="rm-meta-title">' + I18n.t('runsMgr.detailNodes') + '</span>' +
                '<span class="runs-mgr-status ' + this.nodeStatusInfo(run.status).cls + '">' +
                I18n.t(this.statusKey(run.status)) + '</span>' +
                '<span class="rm-meta-time">' + escapeHtml(run.started_at || '') +
                (run.finished_at ? ' &rarr; ' + escapeHtml(run.finished_at) : '') +
                (run.duration_seconds != null
                    ? ' &middot; ' + escapeHtml(I18n.t('runsMgr.colDuration')) + ' ' + escapeHtml(this._formatDuration(run.duration_seconds))
                    : '') +
                '</span>' +
                (run.note ? '<span class="rm-meta-note">' + escapeHtml(run.note) + '</span>' : '') +
                (run.skipped_workflows
                    ? '<span class="rm-meta-note">' +
                        escapeHtml(I18n.t('runsMgr.skipped').replace('{names}', run.skipped_workflows)) +
                        '</span>'
                    : '') +
                '</div>' +
                (multi
                    ? body
                    : '<div class="rm-nodes">' +
                        (body || '<div class="runs-mgr-empty">' + I18n.t('runsMgr.noNodes') + '</div>') +
                        '</div>') +
                '</td>';
            /* Re-resolved AFTER the fetch, from the live table. `refresh()` replaces the
               whole table while this request is in flight — the console keeps the run list
               current for a live run, which is exactly when a person opens a detail — so the
               row that was clicked can be an orphan by the time the answer lands. Inserting
               under that orphan drew the detail into a detached subtree (nothing appeared on
               screen) and then set `_detail`, which silences auto-refresh *for a detail
               nobody can see*: the panel went quiet and blank at once, and only a page
               reload or a manual refresh repaired it. A run no longer listed answers with
               nothing at all. */
            var row = this._rowFor(runId);
            if (!row) return;
            row.after(tr);
            this._detail = runId;
        } catch (e) { /* leave the table as it was */ }
    },
};

workflow.validate = function () {
    /* The run-gate and the parity tests read this flat, ordered list. It is a one-line
       projection of validateDetailed so there is exactly ONE rule body; the edit-time
       badges read validateDetailed to know WHICH node each message is about. */
    return workflow.validateDetailed().messages;
};

workflow.validateDetailed = function () {
    var errors = [];
    var perNode = {};
    function add(id, msg) {
        errors.push(msg);
        if (id !== null && id !== undefined) {
            (perNode[id] = perNode[id] || []).push(msg);
        }
    }
    var nodes = canvas.nodes;
    var conns = canvas.connections;

    if (Object.keys(nodes).length === 0) {
        add(null, I18n.t('validate.empty'));
        return { messages: errors, perNode: perNode };
    }

    /* Build lookup: which nodes have inputs/outputs, and how many inputs each
       one has (a join needs two: left table, right table). */
    var hasInput = {};
    var hasOutput = {};
    var inputCount = {};
    /* A wire FROM a name node is the labelling pattern, not a data table — the
       source feed gate must not see it as a feed (backend validate builds the same
       distinction off the same rule: parent type !== 'name'). */
    var dataInput = {};
    conns.forEach(function (c) {
        hasOutput[c.from] = true;
        hasInput[c.to] = true;
        inputCount[c.to] = (inputCount[c.to] || 0) + 1;
        var src = nodes[c.from];
        if (src && src.type !== 'name' && nodes[c.to]) dataInput[c.to] = true;
    });
    /* Direct parents' types per node — the compile/output rules below key on exactly the same
       immediate-upstream distinction the backend validate builds. */
    var parentTypes = {};
    conns.forEach(function (c) {
        var src = nodes[c.from];
        if (src && nodes[c.to]) (parentTypes[c.to] = parentTypes[c.to] || []).push(src.type);
    });
    var TABLE_TYPES = ['source', 'upload', 'resume', 'comment', 'process', 'analysis', 'biblio', 'accumulate', 'tokenize', 'output'];

    Object.keys(nodes).forEach(function (id) {
        var node = nodes[id];
        var params = node.params || {};
        var type = node.type;
        /* Old saved workflows can carry title:null — the message must still
           name the node (type label + id), never read 'node "null"'. */
        var label = node.title || I18n.t('node.' + type);

        if (type === 'source') {
            sourceNodeErrors(node, label, !!dataInput[id]).forEach(function (m) { add(id, m); });
            if (!hasOutput[id]) {
                add(id, I18n.t('validate.sourceDownstream').replace('{title}', label));
            }
        }

        if (type === 'process') {
            if (!hasInput[id]) {
                add(id, I18n.t('validate.processInput').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                add(id, I18n.t('validate.processDownstream').replace('{title}', label));
            }
        }

        if (type === 'analysis') {
            if (!hasInput[id]) {
                add(id, I18n.t('validate.analysisInput').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                add(id, I18n.t('validate.analysisDownstream').replace('{title}', label));
            }
            if (!params.operation) {
                add(id, I18n.t('validate.analysisOperation').replace('{title}', label));
            }
            if (params.operation === 'join_tables' && (inputCount[id] || 0) < 2) {
                /* The right-hand table is the node's second incoming
                   connection — without it the join has nothing to join with. */
                add(id, I18n.t('validate.joinNeedsTwo').replace('{title}', label));
            }
        }

        if (type === 'upload') {
            /* A source like any other: nothing upstream, but it must have a file. */
            if (!params.dataset_id) {
                add(id, I18n.t('validate.uploadFile').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                add(id, I18n.t('validate.uploadDownstream').replace('{title}', label));
            }
        }

        if (type === 'accumulate') {
            if (!String(params.lineage_name || '').trim()) {
                add(id, I18n.t('validate.accumulateName').replace('{title}', label));
            }
            if (params.identity === 'columns' && !String(params.key_columns || '').trim()) {
                add(id, I18n.t('validate.accumulateKeys').replace('{title}', label));
            }
            if ((inputCount[id] || 0) !== 1) {
                add(id, I18n.t('validate.accumulateOneParent').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                add(id, I18n.t('validate.accumulateDownstream').replace('{title}', label));
            }
        }

        if (type === 'biblio') {
            var biblioParents = parentTypes[id] || [];
            if (!dataInput[id]) {
                add(id, I18n.t('validate.biblioInput').replace('{title}', label));
            } else if (biblioParents.length > 1) {
                add(id, I18n.t('validate.biblioOneInput').replace('{title}', label).replace('{n}', biblioParents.length));
            }
            var entity = params.entity_type || 'keyword';
            var shape = params.output_shape || 'nodes';
            if (BIBLIO_ENTITY_TYPES.indexOf(entity) < 0) {
                add(id, I18n.t('validate.biblioEntity').replace('{title}', label));
            }
            if (BIBLIO_OUTPUT_SHAPES.indexOf(shape) < 0) {
                add(id, I18n.t('validate.biblioShape').replace('{title}', label));
            }
            if (isBiblioCoupling(entity) && boolParam(params.burst, true)) {
                add(id, I18n.t('validate.biblioBurstCoupling').replace('{title}', label));
            }
            if (shape === 'clusters' && !boolParam(params.cluster, true)) {
                add(id, I18n.t('validate.biblioShapeCluster').replace('{title}', label));
            }
            if (shape === 'bursts' && !boolParam(params.burst, !isBiblioCoupling(entity))) {
                add(id, I18n.t('validate.biblioShapeBurst').replace('{title}', label));
            }
            if (shape === 'dual_map' && !String(params.basemap_dataset_id || '').trim()) {
                add(id, I18n.t('validate.biblioBasemap').replace('{title}', label));
            }
        }

        if (type === 'name') {
            /* The name node is metadata, not data: it must sit at the head of
               the workflow (no incoming edges), wire into something, and
               carry a non-empty label — that label is what groups the run in
               the Execution History panel. */
            if (!params.workflow_name || !String(params.workflow_name).trim()) {
                add(id, I18n.t('validate.nameEmpty').replace('{title}', label));
            }
            if (hasInput[id]) {
                add(id, I18n.t('validate.nameMustLead').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                add(id, I18n.t('validate.nameDownstream').replace('{title}', label));
            }
        }

        if (type === 'tokenize') {
            if (!hasInput[id]) {
                add(id, I18n.t('validate.tokenizeInput').replace('{title}', label));
            }
            if (!params.text_column || !params.text_column.trim()) {
                add(id, I18n.t('validate.tokenizeColumn').replace('{title}', label));
            }
        }

        if (type === 'visualize') {
            if (!hasInput[id]) {
                add(id, I18n.t('validate.visualizeInput').replace('{title}', label));
            }
            if (!params.chart_type) {
                add(id, I18n.t('validate.visualizeChartType').replace('{title}', label));
            }
            // 模型一致率 has no x/y — it reads the tidy table's label column (the model/id columns
            // default to 模型/原行). The four bibliometric views read fixed columns too. Requiring
            // x_field here would block a chart that never uses it, so ask for the field THIS type
            // really needs, matching the backend's own refusal.
            if (BIBLIO_CHARTS.indexOf(params.chart_type) >= 0) {
                // fixed columns; nothing to ask for
            } else if (params.chart_type === 'model_agreement') {
                if (!params.agreement_label_field || !String(params.agreement_label_field).trim()) {
                    add(id, I18n.t('validate.visualizeAgreementLabel').replace('{title}', label));
                }
            } else if (!params.x_field || !params.x_field.trim()) {
                add(id, I18n.t('validate.visualizeXField').replace('{title}', label));
            }
        }

        if (type === 'compile') {
            /* A compile node turns a visualize parent's LaTeX into a PDF. Its source must be a visualize
               node that will actually emit some — mirrored off the same immediate-upstream rule as the
               backend, so a chart with neither LaTeX box on, or a non-visualize wire, is refused here too. */
            var cmpParents = parentTypes[id] || [];
            if (!cmpParents.length) {
                add(id, I18n.t('validate.compileInput').replace('{title}', label));
            }
            cmpParents.forEach(function (ptype) {
                if (ptype !== 'visualize') {
                    add(id, I18n.t('validate.compileBadParent').replace('{title}', label));
                }
            });
            conns.forEach(function (c) {
                if (String(c.to) !== String(id)) return;
                var par = nodes[c.from];
                if (par && par.type === 'visualize') {
                    var pp = par.params || {};
                    if (!boolParam(pp.emit_latex, true) && !boolParam(pp.emit_latex_table, true)) {
                        add(id, I18n.t('validate.compileSourceBothOff').replace('{title}', label));
                    }
                }
            });
        }

        if (type === 'output') {
            if (!hasInput[id]) {
                add(id, I18n.t('validate.outputInput').replace('{title}', label));
            }
            if ((params.operation === 'save' || params.operation === 'save_csv') && (!params.filename || !params.filename.trim())) {
                add(id, I18n.t('validate.outputFilename').replace('{title}', label));
            }
            /* PDF and a row table are mutually exclusive outputs: a pdf format needs a visualize/compile
               source (and no table alongside); a table format must not be fed only by a chart/compile. */
            var outTypes = parentTypes[id] || [];
            var isPdf = (params.operation === 'save' || params.operation === 'save_csv') &&
                (String(params.format || '').toLowerCase() === 'pdf' || String(params.filename || '').toLowerCase().endsWith('.pdf'));
            var anyTable = outTypes.some(function (t) { return TABLE_TYPES.indexOf(t) >= 0; });
            var anyPdfable = outTypes.some(function (t) { return t === 'visualize' || t === 'compile'; });
            if (isPdf) {
                if (anyTable) add(id, I18n.t('validate.outputPdfMixed').replace('{title}', label));
                if (!anyPdfable) add(id, I18n.t('validate.outputPdfOnly').replace('{title}', label));
                if (outTypes.indexOf('visualize') >= 0 && outTypes.indexOf('compile') >= 0) {
                    add(id, I18n.t('validate.outputPdfTwoSources').replace('{title}', label));
                }
            } else if (anyPdfable && !anyTable) {
                add(id, I18n.t('validate.outputNeedsPdf').replace('{title}', label));
            }
        }
    });

    var hasUpstream = Object.keys(nodes).some(function (id) {
        return ['source', 'upload', 'process', 'analysis', 'tokenize', 'resume', 'comment'].indexOf(nodes[id].type) >= 0;
    });
    if (hasUpstream) {
        var hasTerminal = Object.keys(nodes).some(function (id) {
            return nodes[id].type === 'output' || nodes[id].type === 'visualize';
        });
        if (!hasTerminal) {
            add(null, I18n.t('validate.noTerminal'));
        }
    }

    return { messages: errors, perNode: perNode };
};
