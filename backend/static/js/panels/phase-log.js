/* phase-log.js — the Console's startup / phase timing strip.
 *
 * The user's report that started this (“打开窗口没有反应”) is a question about TIME: a
 * slow account spends a minute opening the search before a note appears, and the console
 * shows nothing until the first row. This strip answers it with numbers from
 * ``/api/run/phases`` (runtime/phases.py): how long the browser took, the crawl, and each
 * comment link — with the status and row count that link settled on.
 *
 * Its own two-second poll, deliberately not the run status's: the strip must also work
 * between runs (reading the last run's timings), and it must not add work to the status
 * loop. A repaint happens only when the payload changed, so a quiet crawl does not churn
 * the DOM every poll.
 */
const PhaseLog = {
    _timer: null,
    _signature: '',

    start() {
        if (this._timer) return;
        this._timer = setInterval(function () {
            PhaseLog.refresh();
        }, 2000);
    },

    async refresh() {
        const panel = document.getElementById('console-panel');
        if (!panel || !panel.classList.contains('open')) return;
        let data = null;
        try {
            const resp = await fetch('/api/run/phases');
            data = await resp.json();
        } catch (e) {
            return;
        }
        if (!data || !data.ok) return;
        this.render(data.phases || []);
    },

    _word(prefix, token) {
        // The key is assembled from a literal root the reachability gate can see
        // (``'phaseLog.phase.' +``), never from an opaque variable.
        const key = prefix === 'phase' ? 'phaseLog.phase.' + token : 'phaseLog.status.' + token;
        const word = I18n.t(key);
        return word === key ? String(token) : word;
    },

    _detail(entry) {
        const bits = [];
        if (entry.rows !== undefined && entry.rows !== null) {
            bits.push(I18n.t('phaseLog.rows').replace('{n}', String(entry.rows)));
        }
        if (entry.status) bits.push(this._word('status', entry.status));
        if (entry.unproven) bits.push(I18n.t('phaseLog.unproven').replace('{n}', String(entry.unproven)));
        if (entry.wall) bits.push(I18n.t('phaseLog.wall'));
        if (entry.risk) bits.push(I18n.t('phaseLog.risk'));
        if (entry.for_login) bits.push(I18n.t('phaseLog.loginWindow'));
        return bits.join(' · ');
    },

    _label(entry) {
        const platform = entry.platform ? I18n.t('platform.' + entry.platform) : '';
        const base = platform && platform !== 'platform.' + entry.platform ? platform : entry.label || '';
        const tail = this._urlTail(entry.url);
        return tail ? base + ' …/' + tail : base;
    },

    _urlTail(url) {
        const text = String(url || '').split('?')[0].replace(/\/+$/, '');
        if (!text) return '';
        const tail = text.slice(text.lastIndexOf('/') + 1);
        return tail.length > 28 ? tail.slice(0, 28) + '…' : tail;
    },

    render(phases) {
        const box = document.getElementById('console-phases-body');
        if (!box) return;
        const signature = JSON.stringify(phases);
        if (signature === this._signature) return;
        this._signature = signature;
        if (!phases.length) {
            box.innerHTML = '<div class="phase-empty">' + escapeHtml(I18n.t('phaseLog.empty')) + '</div>';
            return;
        }
        const rows = phases
            .map(function (entry) {
                const name = PhaseLog._word('phase', entry.phase);
                const detail = PhaseLog._detail(entry);
                return (
                    '<tr>' +
                    '<td class="phase-name">' + escapeHtml(name) + '</td>' +
                    '<td class="phase-label">' + escapeHtml(PhaseLog._label(entry)) + '</td>' +
                    '<td class="phase-seconds">' + escapeHtml(Number(entry.seconds || 0).toFixed(1)) + 's</td>' +
                    '<td class="phase-detail">' + escapeHtml(detail) + '</td>' +
                    '</tr>'
                );
            })
            .join('');
        box.innerHTML = '<table class="phase-table"><tbody>' + rows + '</tbody></table>';
    },
};

/* A top-level ``const`` is not a property of the page's global object, so the console and
   the node harnesses can only reach this object through an explicit export. */
window.PhaseLog = PhaseLog;

PhaseLog.start();
