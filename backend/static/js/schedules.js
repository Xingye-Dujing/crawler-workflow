/* ─── Scheduled tasks: the clock's panel ────────────────────────────────────
   A timer that runs a saved canvas on a wall clock — the point of leaving this
   app running on a cloud box. The panel writes `data/schedules.json` through
   `/api/schedules*`; a daemon thread inside `python app.py` fires the due ones
   through the SAME start path the 执行 button uses, so a scheduled run on a busy
   server is QUEUED, never refused and never run by a second, weaker path.

   Four things this file deliberately does not decide, because the server already
   did and a second opinion here would be the wrong one:

   * whether a canvas may run on a timer — `runnable` / `why_not` come from the
     server, which asks the executor which fields will call a model (a scheduled
     run has no browser request behind it, so there is nowhere for an API key to
     come from);
   * when a task fires next — `next_run_local` / `last_run_local` arrive already
     rendered in the TASK's own zone, because the screen watching a UTC box is
     usually in Beijing, and a moment this file formatted would be the browser's
     zone wearing the server's name;
   * whether the clock is running — `status.running` says so, and the panel prints
     it, because 「保存了但没人执行」 and 「保存了并在执行」 otherwise look alike;
   * what a status word reads as — the server sends a token, this file maps it to
     a catalogue word, and an unknown token is shown AS ITSELF.

   No polling, on purpose: the console polls because lines keep arriving, but a
   schedule only changes when the user changes it or a fire happens, and a second
   permanent timer in the browser would be a cost with no reader. */

var SCHED_FIELD = {
    name: 'sched-name',
    canvas: 'sched-canvas',
    kind: 'sched-kind',
    at: 'sched-at',
    weekday: 'sched-weekday',
    interval: 'sched-interval',
    cron: 'sched-cron',
    zone: 'sched-zone',
    lang: 'sched-lang',
    enabled: 'sched-enabled',
};

function toggleSchedulesPanel() {
    schedulesManager.toggle();
}

var schedulesManager = {
    _tasks: null,
    _canvases: null,
    _status: null,

    panel() {
        return document.getElementById('schedules-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('schedules-panel');
        panel.classList.add('open');
        this.refresh();
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        /* The resize handle leaves an inline height behind, and an inline height
           overrides the CSS `height: 0` — Close looks dead after a resize. */
        panel.style.height = '';
    },

    async refresh() {
        var body = document.getElementById('schedules-mgr-body');
        if (!body) return;
        var answer = await fetchJSON('/api/schedules');
        if (!answer || !answer.ok) {
            body.innerHTML =
                '<div class="runs-mgr-empty">' +
                escapeHtml((answer && answer.error) || I18n.t('schedMgr.unreachable')) +
                '</div>';
            return;
        }
        this._apply(answer);
    },

    /* The language switch repaints from the cache for the same reason the other
       docks do: every word in this table is built here, so `I18n.apply()` (which
       only re-stamps `data-i18n` nodes) never reaches it. */
    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        if (this._tasks) this.render();
        else this.refresh();
    },

    _apply(answer) {
        if (answer.tasks) this._tasks = answer.tasks;
        if (answer.canvases) this._canvases = answer.canvases;
        if (answer.status) this._status = answer.status;
        this.render();
    },

    render() {
        var body = document.getElementById('schedules-mgr-body');
        if (!body) return;
        var rows = this._tasks || [];
        var head = this._statusLine();
        if (!rows.length) {
            body.innerHTML = head + '<div class="runs-mgr-empty">' + I18n.t('schedMgr.empty') + '</div>';
            return;
        }
        var self = this;
        body.innerHTML =
            head +
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('schedMgr.colName') + '</th>' +
            '<th>' + I18n.t('schedMgr.colCanvas') + '</th>' +
            '<th>' + I18n.t('schedMgr.colWhen') + '</th>' +
            '<th>' + I18n.t('schedMgr.colNext') + '</th>' +
            '<th>' + I18n.t('schedMgr.colLast') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' +
            rows.map(function (task) {
                return self._row(task);
            }).join('') +
            '</tbody></table>';
    },

    /* The operator's line: which box this is, what it calls 「现在」, and whether
       the clock is actually running. */
    _statusLine() {
        var s = this._status || {};
        var parts = [];
        if (s.now_local) parts.push(I18n.t('schedMgr.serverNow').replace('{at}', s.now_local));
        if (s.local_zone) parts.push(I18n.t('schedMgr.serverZone').replace('{zone}', s.local_zone));
        parts.push(s.running ? I18n.t('schedMgr.clockOn') : I18n.t('schedMgr.clockOff'));
        return (
            '<div class="sched-status' + (s.running ? '' : ' sched-status-off') + '">' +
            parts.map(escapeHtml).join(' · ') +
            '</div>'
        );
    },

    _row(task) {
        var off = !task.enabled;
        var chips = '';
        if (off) chips += '<span class="sched-chip">' + I18n.t('schedMgr.off') + '</span>';
        var missed = (task.missed || {}).count || 0;
        if (missed) {
            chips +=
                '<span class="sched-chip sched-chip-missed">' +
                escapeHtml(I18n.t('schedMgr.missed').replace('{n}', String(missed))) +
                '</span>';
        }
        return (
            '<tr' + (off ? ' class="sched-row-off"' : '') + '>' +
            '<td class="runs-mgr-wf">' + escapeHtml(task.name || task.id || '') + chips + '</td>' +
            '<td>' + escapeHtml(task.workflow || '') + '</td>' +
            '<td>' + escapeHtml(task.trigger_text || '') + '</td>' +
            '<td class="runs-mgr-time">' +
            escapeHtml(off ? I18n.t('schedMgr.off') : task.next_run_local || '') +
            '</td>' +
            '<td class="runs-mgr-time">' + this._lastCell(task) + '</td>' +
            '<td class="runs-mgr-ops">' + this._ops(task) + '</td>' +
            '</tr>'
        );
    },

    /* What happened last time, in the task's own zone — plus the refusal reason
       when there was one. A task that was refused at 03:00 is the one row the
       user came to this panel to read. */
    _lastCell(task) {
        var last = task.last_run || {};
        if (!last.status) return '<span class="sched-none">' + I18n.t('schedMgr.never') + '</span>';
        var html =
            '<div>' +
            escapeHtml(this._statusWord(last.status)) +
            ' · ' +
            escapeHtml(task.last_run_local || '') +
            '</div>';
        if (last.note) html += '<div class="sched-note">' + escapeHtml(last.note) + '</div>';
        return html;
    },

    /* One token per outcome → one catalogue word. An unknown token (a newer
       server, a hand-edited file) is shown AS ITSELF rather than as the
       friendliest of the five. Literal calls, not a key table: the suite that
       refuses a key nobody wrote scans for `I18n.t('…')`. */
    _statusWord(status) {
        if (status === 'started') return I18n.t('schedMgr.statusStarted');
        if (status === 'queued') return I18n.t('schedMgr.statusQueued');
        if (status === 'refused') return I18n.t('schedMgr.statusRefused');
        if (status === 'missed') return I18n.t('schedMgr.statusMissed');
        if (status === 'error') return I18n.t('schedMgr.statusError');
        return String(status || '');
    },

    _quote(value) {
        return attrJsArg(value);
    },

    _ops(task) {
        var id = this._quote(task.id);
        var ops = '';
        ops +=
            '<button class="runs-mgr-btn" onclick="schedulesManager.toggleTask(\'' + id + '\', ' +
            (task.enabled ? 'false' : 'true') + ')">' +
            (task.enabled ? I18n.t('schedMgr.disable') : I18n.t('schedMgr.enable')) +
            '</button>';
        ops +=
            '<button class="runs-mgr-btn" onclick="schedulesManager.runNow(\'' + id + '\')">' +
            I18n.t('schedMgr.runNow') +
            '</button>';
        ops +=
            '<button class="runs-mgr-btn" onclick="schedulesManager.edit(\'' + id + '\')">' +
            I18n.t('schedMgr.edit') +
            '</button>';
        var runId = (task.last_run || {}).run_id || '';
        if (runId) {
            ops +=
                '<button class="runs-mgr-btn" onclick="runLogViewer.open(\'' + this._quote(runId) + '\')">' +
                I18n.t('schedMgr.viewLog') +
                '</button>';
        }
        ops +=
            '<button class="runs-mgr-btn del" onclick="schedulesManager.remove(\'' + id + '\')">' +
            I18n.t('schedMgr.remove') +
            '</button>';
        return ops;
    },

    /* ── The editor ──
       One dialog, all fields, like every other editor in this app: what a kind
       does not use is left in the box rather than removed, so switching 每天 →
       每周 → 每天 does not lose the time that was typed. */

    _find(id) {
        var wanted = String(id);
        var rows = this._tasks || [];
        for (var i = 0; i < rows.length; i++) {
            if (String(rows[i].id) === wanted) return rows[i];
        }
        return null;
    },

    async create() {
        if (!this._canvases) await this.refresh();
        return this.edit('');
    },

    async edit(id) {
        var task = id ? this._find(id) : null;
        if (id && !task) {
            /* The row is gone (another tab deleted it) — reload rather than open a
               form whose save would re-create a task nobody asked for. */
            showToast(I18n.t('schedMgr.gone'));
            await this.refresh();
            return;
        }
        var trigger = (task && task.trigger) || { kind: 'daily', at: '08:00' };
        var answer = await showDialog({
            message: I18n.t('schedMgr.formHint'),
            fields: [
                {
                    id: SCHED_FIELD.name,
                    label: I18n.t('schedMgr.fName'),
                    type: 'text',
                    value: (task && task.name) || '',
                },
                {
                    id: SCHED_FIELD.canvas,
                    label: I18n.t('schedMgr.fCanvas'),
                    type: 'select',
                    options: this._canvasOptions(task && task.workflow),
                    value: (task && task.workflow) || '',
                },
                {
                    id: SCHED_FIELD.kind,
                    label: I18n.t('schedMgr.fKind'),
                    type: 'select',
                    options: this._kindOptions(),
                    value: trigger.kind || 'daily',
                },
                {
                    id: SCHED_FIELD.at,
                    label: I18n.t('schedMgr.fAt'),
                    type: 'text',
                    value: trigger.at || '08:00',
                    onlyWhen: { field: SCHED_FIELD.kind, values: ['daily', 'weekly'] },
                },
                {
                    id: SCHED_FIELD.weekday,
                    label: I18n.t('schedMgr.fWeekday'),
                    type: 'select',
                    options: this._weekdayOptions(),
                    value: String(trigger.weekday || 1),
                    onlyWhen: { field: SCHED_FIELD.kind, values: ['weekly'] },
                },
                {
                    id: SCHED_FIELD.interval,
                    label: I18n.t('schedMgr.fInterval'),
                    type: 'number',
                    value: String(trigger.minutes || 30),
                    min: '1',
                    max: '10080',
                    onlyWhen: { field: SCHED_FIELD.kind, values: ['interval'] },
                },
                {
                    id: SCHED_FIELD.cron,
                    label: I18n.t('schedMgr.fCron'),
                    type: 'text',
                    value: trigger.expr || '',
                    onlyWhen: { field: SCHED_FIELD.kind, values: ['cron'] },
                },
                {
                    id: SCHED_FIELD.zone,
                    label: I18n.t('schedMgr.fZone'),
                    type: 'text',
                    value: (task && task.timezone) || '',
                },
                {
                    id: SCHED_FIELD.lang,
                    label: I18n.t('schedMgr.fLang'),
                    type: 'select',
                    options: [
                        { value: 'zh', label: '中文' },
                        { value: 'en', label: 'English' },
                    ],
                    value: (task && task.lang) || I18n.lang,
                },
            ],
            toggles: [{ id: SCHED_FIELD.enabled, label: I18n.t('schedMgr.fEnabled'), checked: task ? !!task.enabled : true }],
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('schedMgr.save'), value: 'save', collect: true, primary: true },
            ],
        });
        if (!answer || answer.value !== 'save') return;
        return this.submit(task, answer.fields || {}, answer.toggles || {});
    },

    _canvasOptions(current) {
        var options = (this._canvases || []).map(function (item) {
            /* A canvas that may not run on a timer keeps its place, with the
               server's own sentence beside it: the user is choosing now, not at
               03:00 when a refusal would be a line in a history nobody reads. */
            var label = item.runnable ? item.name : item.name + ' — ' + (item.why_not || I18n.t('schedMgr.canvasLocked'));
            return { value: item.name, label: label };
        });
        /* A stored canvas no longer on the list (the file was renamed) is shown
           AS ITSELF: a <select> whose value is not among its options answers ''
           and the save would then refuse a task the user never touched. */
        if (
            current &&
            !options.some(function (option) {
                return option.value === current;
            })
        ) {
            options.unshift({ value: current, label: current });
        }
        return options;
    },

    _kindOptions() {
        return [
            { value: 'daily', label: I18n.t('schedMgr.kindDaily') },
            { value: 'weekly', label: I18n.t('schedMgr.kindWeekly') },
            { value: 'interval', label: I18n.t('schedMgr.kindInterval') },
            { value: 'cron', label: I18n.t('schedMgr.kindCron') },
        ];
    },

    _weekdayOptions() {
        var keys = [
            'schedMgr.weekday1',
            'schedMgr.weekday2',
            'schedMgr.weekday3',
            'schedMgr.weekday4',
            'schedMgr.weekday5',
            'schedMgr.weekday6',
            'schedMgr.weekday7',
        ];
        return keys.map(function (key, index) {
            return { value: String(index + 1), label: I18n.t(key) };
        });
    },

    /* Only the keys the chosen kind means: a daily rule that also carried
       `minutes` would be a task whose sentence and whose arithmetic could drift
       apart. */
    _triggerFrom(kind, fields) {
        var at = String(fields[SCHED_FIELD.at] || '').trim();
        if (kind === 'interval') return { kind: 'interval', minutes: Number(fields[SCHED_FIELD.interval]) };
        if (kind === 'cron') return { kind: 'cron', expr: String(fields[SCHED_FIELD.cron] || '').trim() };
        if (kind === 'weekly') {
            return { kind: 'weekly', at: at, weekday: Number(fields[SCHED_FIELD.weekday]) };
        }
        return { kind: 'daily', at: at };
    },

    async submit(task, fields, toggles) {
        var payload = {
            name: String(fields[SCHED_FIELD.name] || '').trim(),
            workflow: String(fields[SCHED_FIELD.canvas] || ''),
            timezone: String(fields[SCHED_FIELD.zone] || '').trim(),
            lang: String(fields[SCHED_FIELD.lang] || 'zh'),
            enabled: !!toggles[SCHED_FIELD.enabled],
            trigger: this._triggerFrom(String(fields[SCHED_FIELD.kind] || 'daily'), fields),
        };
        if (task) payload.id = task.id;
        var answer = await this._post('/api/schedules/save', payload);
        if (!answer) return;
        showToast(I18n.t('schedMgr.saved'));
    },

    async toggleTask(id, enabled) {
        await this._post('/api/schedules/toggle', { id: id, enabled: !!enabled });
    },

    async runNow(id) {
        var answer = await this._post('/api/schedules/run', { id: id });
        if (!answer) return;
        var result = answer.result || {};
        if (result.status === 'queued') {
            showToast(I18n.t('schedMgr.runQueued').replace('{name}', result.name || ''), 4000);
        } else {
            showToast(I18n.t('schedMgr.runStarted').replace('{name}', result.name || ''));
            /* A 立即执行 fire that really started owns a live console, but the stream only ever
               took itself up from a page load — so the user had to refresh to watch it. Take the
               same attach the Run button and the boot reconnect take, now. reconnectConsole reads
               the running status, replays what the fire has written so far, opens the panel and
               starts polling; it returns early when a stream is already attached, so a queued fire
               (which never reaches here) and a double click cannot double-poll. */
            if (result.status === 'started' && typeof workflow !== 'undefined' && workflow) {
                workflow.reconnectConsole();
            }
        }
    },

    async remove(id) {
        var task = this._find(id);
        var name = (task && task.name) || String(id || '');
        var answer = await showDialog({
            message: I18n.t('schedMgr.confirmRemove').replace('{name}', name),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('schedMgr.remove'), value: 'yes', primary: true },
            ],
        });
        if (answer !== 'yes') return;
        await this._post('/api/schedules/delete', { id: id });
    },

    /* One POST for all four verbs. A refusal is shown as the SERVER worded it —
       it names the field to fix (a time, a zone, a canvas whose steps need a
       model) — and the payload that comes back with it is applied, so the table
       never sits on a task the server just refused to write. */
    async _post(url, payload) {
        var answer = await fetchJSON(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!answer || !answer.ok) {
            showToast((answer && answer.error) || I18n.t('schedMgr.unreachable'), 4000);
            if (answer && answer.tasks) this._apply(answer);
            return null;
        }
        this._apply(answer);
        return answer;
    },
};
