/* Main-program self-update: one paper card, one consent dialog, one restart.

 * The server owns the feed, the download, the hash check, the swap AND the job's state (it lives
 * in `data/updates/job.json`, not in this page): this file only paints what the server says and
 * sends the three answers a user can give — 立即更新 / 稍后 / 取消. A reload, a second window or a
 * closed window therefore continue the same download instead of starting a new opinion about it.

 * Two rules the card owes the workspace:
 *   · it sits BELOW the menu strip (`--menuH`) and under the menu's own z-index, so it can never
 *     cover the one navigation this page has;
 *   · 稍后 is remembered for a day and per version. It used to live in `sessionStorage`, which in
 *     a desktop window means "dies with the window" — i.e. the same prompt at every launch.
 */
const UpdatePanel = {
    _info: null,
    _job: null,
    _card: null,
    _timer: null,
    _polling: false,
    _busy: false,
    _notice: '',
    _announced: '',
    SNOOZE_MS: 24 * 60 * 60 * 1000,
    SNOOZE_KEY: 'update-snooze',
    ANNOUNCE_KEY: 'update-announced',

    async check() {
        try {
            const response = await fetch('/api/update/check');
            const answer = await response.json();
            if (!answer || !answer.ok || !answer.supported) {
                this._hide();
                return;
            }
            this._info = answer;
            this._job = answer.job || { state: 'idle' };
            this._announce(answer);
            this._render();
        } catch (err) {
            /* An update check is a convenience; a failed check must not disturb the workspace. */
        }
    },

    /* ── the card ───────────────────────────────────────────────────────── */

    _mount() {
        const card = document.createElement('section');
        card.id = 'update-banner';
        card.className = 'update-card';
        card.setAttribute('role', 'status');
        card.setAttribute('aria-live', 'polite');
        card.hidden = true;
        const head = document.createElement('div');
        head.className = 'update-head';
        const label = document.createElement('span');
        label.className = 'update-label';
        const version = document.createElement('span');
        version.className = 'update-version';
        head.appendChild(label);
        head.appendChild(version);
        const text = document.createElement('p');
        text.className = 'update-text';
        const progress = document.createElement('div');
        progress.className = 'update-progress';
        progress.hidden = true;
        const bar = document.createElement('i');
        bar.className = 'update-bar';
        progress.appendChild(bar);
        const actions = document.createElement('div');
        actions.className = 'update-actions';
        const now = document.createElement('button');
        now.type = 'button';
        now.className = 'update-btn update-now';
        now.onclick = () => this._onPrimary();
        const later = document.createElement('button');
        later.type = 'button';
        later.className = 'update-btn update-later';
        later.onclick = () => this._postponeAndHide();
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'update-btn update-cancel';
        cancel.onclick = () => this._cancel();
        actions.appendChild(now);
        actions.appendChild(later);
        actions.appendChild(cancel);
        card.appendChild(head);
        card.appendChild(text);
        card.appendChild(progress);
        card.appendChild(actions);
        document.body.appendChild(card);
        this._card = card;
        return card;
    },

    _parts() {
        const card = this._card || this._mount();
        return {
            card: card,
            label: card.querySelector('.update-label'),
            version: card.querySelector('.update-version'),
            text: card.querySelector('.update-text'),
            progress: card.querySelector('.update-progress'),
            bar: card.querySelector('.update-bar'),
            now: card.querySelector('.update-now'),
            later: card.querySelector('.update-later'),
            cancel: card.querySelector('.update-cancel'),
        };
    },

    /* The one painter. Every state the server can report has a row here, so a new state shows up
       as an unlit card rather than as a silently frozen sentence from three states ago. */
    _render() {
        const info = this._info || {};
        const job = this._job || { state: 'idle' };
        const state = String(job.state || 'idle');
        const version = String(job.version || info.latest || '').trim();
        if (!this._shouldShow(info, job)) {
            this._hide();
            return;
        }
        const parts = this._parts();
        parts.label.textContent = I18n.t('update.label');
        parts.version.textContent = version;
        parts.card.hidden = false;
        parts.progress.hidden = true;
        parts.bar.style.width = '0%';
        parts.now.hidden = false;
        parts.later.hidden = false;
        parts.cancel.hidden = true;
        this._actions = 'ready';
        if (state === 'downloading') {
            const percent = Math.max(0, Math.min(100, Number(job.progress) || 0));
            parts.text.textContent = I18n.t('update.downloading', { progress: percent });
            parts.progress.hidden = false;
            parts.bar.style.width = percent + '%';
            parts.now.hidden = true;
            parts.cancel.hidden = false;
            parts.cancel.textContent = I18n.t('update.cancel');
            this._actions = 'downloading';
        } else if (state === 'staging') {
            parts.text.textContent = I18n.t('update.staging');
            parts.progress.hidden = false;
            parts.bar.style.width = '100%';
            parts.now.hidden = true;
            this._actions = 'staging';
        } else if (state === 'staged') {
            parts.text.textContent = this._notice || I18n.t('update.ready', { version: version });
            parts.now.textContent = I18n.t('update.restart');
            this._actions = 'staged';
        } else if (state === 'applying') {
            parts.text.textContent = I18n.t('update.restarting');
            parts.now.hidden = true;
            parts.later.hidden = true;
            this._actions = 'applying';
        } else if (state === 'failed') {
            parts.text.textContent = I18n.t('update.failed', { err: this._errorText(job) });
            parts.now.textContent = I18n.t('update.retry');
            this._actions = 'failed';
        } else if (!info.apply_supported) {
            parts.text.textContent = I18n.t('update.unsupported', { version: version });
            parts.now.hidden = true;
            this._actions = 'unsupported';
        } else {
            parts.text.textContent = I18n.t('update.available', { version: version });
            parts.now.textContent = I18n.t('update.now');
        }
        parts.later.textContent = I18n.t('update.later');
        this._syncPolling();
    },

    _shouldShow(info, job) {
        const state = String(job.state || 'idle');
        const version = String(job.version || info.latest || '');
        if (state !== 'applying' && this._snoozed(version)) return false;
        if (state !== 'idle' && state !== 'cancelled' && state !== 'applied') return true;
        return !!info.update_available;
    },

    _hide() {
        if (this._card) this._card.hidden = true;
    },

    /* ── the three answers ──────────────────────────────────────────────── */

    _onPrimary() {
        const action = this._actions || 'ready';
        if (action === 'staged') return this._restart();
        if (action === 'failed') return this._start();
        return this._ask();
    },

    async _ask() {
        const info = this._info || {};
        const notes = String(info.notes || '').trim();
        const lines = [
            I18n.t('update.summary', { current: info.current || '', latest: info.latest || '' }),
        ];
        if (info.signed) lines.push(I18n.t('update.signed'));
        else lines.push(I18n.t('update.unsigned'));
        if (notes) lines.push(I18n.t('update.notes') + '\n' + notes);
        const answer = await showDialog({
            message: lines.join('\n\n'),
            buttons: [
                { label: I18n.t('update.now'), value: 'now', primary: true },
                { label: I18n.t('update.later'), value: 'later' },
                { label: I18n.t('update.skip'), value: 'skip' },
            ],
        });
        if (answer === 'now') {
            await this._start();
            return;
        }
        this._notice = '';
        this._snooze(String(info.latest || ''), answer === 'skip');
        this._hide();
    },

    async _start() {
        if (this._busy) return;
        this._busy = true;
        this._notice = '';
        this._job = { state: 'downloading', progress: 0, version: (this._info || {}).latest || '' };
        this._render();
        try {
            const response = await fetch('/api/update/download', { method: 'POST' });
            const answer = await response.json();
            if (!answer || !answer.ok) throw new Error((answer && answer.error) || 'download');
            this._job = answer.job || this._job;
        } catch (err) {
            this._job = { state: 'failed', error_code: '', error_detail: String(err.message || err) };
        } finally {
            this._busy = false;
        }
        this._render();
    },

    async _restart() {
        if (this._busy) return;
        this._busy = true;
        this._notice = '';
        const parts = this._parts();
        parts.text.textContent = I18n.t('update.restarting');
        parts.now.hidden = true;
        parts.later.hidden = true;
        this._job = Object.assign({}, this._job || {}, { state: 'applying' });
        try {
            const response = await fetch('/api/update/restart', { method: 'POST' });
            const answer = await response.json();
            if (!answer || !answer.ok) throw new Error((answer && answer.error) || 'restart');
        } catch (err) {
            this._busy = false;
            this._job = Object.assign({}, this._job || {}, { state: 'staged' });
            this._notice = String(err.message || err);
            this._render();
        }
    },

    async _cancel() {
        try {
            const response = await fetch('/api/update/cancel', { method: 'POST' });
            const answer = await response.json();
            if (answer && answer.job) this._job = answer.job;
        } catch (err) {
            /* the next poll reports whatever really happened */
        }
        this._notice = '';
        this._snooze(this._currentVersion());
        this._hide();
    },

    /* ── polling ────────────────────────────────────────────────────────── */

    _syncPolling() {
        const state = String((this._job || {}).state || '');
        const live = state === 'downloading' || state === 'staging';
        if (!live) {
            this._polling = false;
            if (this._timer) {
                window.clearTimeout(this._timer);
                this._timer = null;
            }
            return;
        }
        if (this._polling) return;
        this._polling = true;
        const tick = async () => {
            if (!this._polling) return;
            try {
                const response = await fetch('/api/update/status');
                const answer = await response.json();
                if (answer && answer.ok && answer.job) this._job = answer.job;
            } catch (err) {
                /* one failed poll is not a failed update; the next tick asks again */
            }
            const next = String((this._job || {}).state || '');
            if (next !== 'downloading' && next !== 'staging') {
                this._polling = false;
                this._someoneFinished();
                return;
            }
            this._render();
            this._timer = window.setTimeout(tick, 900);
        };
        this._timer = window.setTimeout(tick, 300);
    },

    /* A download that finished while the window was elsewhere still has to be OFFERED, not just
       painted: the card may have been hidden by 稍后 before the job existed. */
    _someoneFinished() {
        const state = String((this._job || {}).state || '');
        if (state === 'staged' && this._snoozed(this._currentVersion())) {
            return;
        }
        this._render();
    },

    /* ── 稍后 / 不再提示 ────────────────────────────────────────────────── */

    _snoozeState() {
        try {
            const raw = localStorage.getItem(this.SNOOZE_KEY);
            const value = raw ? JSON.parse(raw) : null;
            return value && typeof value === 'object' ? value : null;
        } catch (err) {
            return null;
        }
    },

    _snoozed(version) {
        const state = this._snoozeState();
        if (!state || !version) return false;
        if (String(state.version || '') !== String(version)) return false;
        if (state.skip) return true;
        return Number(state.until || 0) > Date.now();
    },

    _snooze(version, skip) {
        if (!version) return;
        try {
            localStorage.setItem(
                this.SNOOZE_KEY,
                JSON.stringify({ version: String(version), until: Date.now() + this.SNOOZE_MS, skip: !!skip }),
            );
        } catch (err) {
            /* a window that refuses localStorage simply asks again later */
        }
    },

    _postponeAndHide() {
        const job = this._job || {};
        this._snooze(String(job.version || (this._info || {}).latest || ''));
        this._hide();
    },

    _currentVersion() {
        const job = this._job || {};
        const info = this._info || {};
        return String(job.version || info.latest || '');
    },

    /* ── words, notices ─────────────────────────────────────────────────── */

    _errorText(job) {
        const code = String((job && job.error_code) || '');
        const detail = String((job && job.error_detail) || '');
        if (code) {
            const key = 'update.err.' + code;
            const dict = (I18n.dict && (I18n.dict[I18n.lang] || I18n.dict.en)) || {};
            if (dict[key] !== undefined) {
                return detail ? I18n.t('update.errDetail', { message: I18n.t(key), detail: detail }) : I18n.t(key);
            }
        }
        return detail || I18n.t('update.errUnknown');
    },

    _announce(answer) {
        const job = answer.job || {};
        if (job.state !== 'applied' || !job.version) return;
        if (String(job.version) !== String(answer.current || '')) return;
        if (this._announced === String(job.version)) return;
        this._announced = String(job.version);
        try {
            if (localStorage.getItem(this.ANNOUNCE_KEY) === String(job.version)) return;
            localStorage.setItem(this.ANNOUNCE_KEY, String(job.version));
        } catch (err) {
            /* the toast is not worth failing over */
        }
        if (typeof showToast === 'function') {
            showToast(I18n.t('update.applied', { version: String(job.version) }));
        }
    },

    /* A language switch re-stamps everything I18n.apply() can reach, but the card carries a
       {version}/{progress} sentence, which data-i18n attributes cannot. Repaint from the cached
       answer (no request) so the prompt follows the page it sits on. */
    onLanguageChange() {
        if (!this._card) return;
        this._render();
    },
};

window.UpdatePanel = UpdatePanel;
