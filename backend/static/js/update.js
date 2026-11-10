/* Main-program self-update: a small banner, one consent dialog, then a restart.

 * The server owns the feed, the download, the hash check and the swap script. This file only
 * paints the prompt and polls the job; it never decides whether an update exists.
 */
const UpdatePanel = {
    _info: null,
    _timer: null,
    _busy: false,

    async check() {
        try {
            const response = await fetch('/api/update/check');
            const answer = await response.json();
            if (!answer.ok || !answer.supported || !answer.update_available) return;
            if (sessionStorage.getItem('update-postponed') === answer.latest) return;
            this._info = answer;
            this._banner(answer);
        } catch (err) {
            /* An update check is a convenience; a failed check must not disturb the workspace. */
        }
    },

    _banner(info) {
        let banner = document.getElementById('update-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'update-banner';
            const text = document.createElement('span');
            text.className = 'update-text';
            const button = document.createElement('button');
            button.className = 'update-now';
            button.type = 'button';
            button.textContent = I18n.t('update.now');
            button.onclick = () => this._ask();
            banner.append(text, button);
            document.body.appendChild(banner);
        }
        banner.querySelector('.update-text').textContent = I18n.t('update.available', { version: info.latest });
        const button = banner.querySelector('.update-now');
        if (button) button.hidden = false;
        banner.hidden = false;
    },

    _hide() {
        const banner = document.getElementById('update-banner');
        if (banner) banner.hidden = true;
    },

    /* A language switch re-stamps everything I18n.apply() can reach, but the banner's sentence
       carries a {version} variable, which data-i18n attributes cannot. Repaint it from the cached
       answer (no request) so the prompt follows the page it sits on. */
    onLanguageChange() {
        const banner = document.getElementById('update-banner');
        if (!banner || !this._info || banner.hidden) return;
        banner.querySelector('.update-text').textContent = I18n.t('update.available', {
            version: this._info.latest,
        });
        const button = banner.querySelector('.update-now');
        if (button) button.textContent = I18n.t('update.now');
    },

    _message(text) {
        const banner = document.getElementById('update-banner');
        if (!banner) return;
        banner.querySelector('.update-text').textContent = text;
        const button = banner.querySelector('.update-now');
        if (button) button.hidden = true;
    },

    async _ask() {
        const info = this._info || {};
        const notes = String(info.notes || '').trim();
        const detail = I18n.t('update.summary', { current: info.current || '', latest: info.latest || '' }) +
            (notes ? '\n\n' + I18n.t('update.notes') + '\n' + notes : '');
        const answer = await showDialog({
            message: detail,
            buttons: [
                { label: I18n.t('update.now'), value: 'now', primary: true },
                { label: I18n.t('update.later'), value: 'later' },
            ],
        });
        if (answer !== 'now') {
            sessionStorage.setItem('update-postponed', info.latest || '');
            this._hide();
            return;
        }
        await this._download();
    },

    async _download() {
        if (this._busy) return;
        this._busy = true;
        this._message(I18n.t('update.staging'));
        try {
            const response = await fetch('/api/update/download', { method: 'POST' });
            const answer = await response.json();
            if (!answer.ok) throw new Error(answer.error || 'download');
            this._poll(answer.job.id);
        } catch (err) {
            this._busy = false;
            await this._failed(String(err.message || err));
        }
    },

    _poll(jobId) {
        const tick = async () => {
            try {
                const response = await fetch('/api/update/job/' + encodeURIComponent(jobId));
                const answer = await response.json();
                if (!answer.ok) throw new Error(answer.error || 'job');
                const job = answer.job || {};
                if (job.state === 'downloading') {
                    this._message(I18n.t('update.downloading', { progress: Number(job.progress) || 0 }));
                    this._timer = window.setTimeout(tick, 800);
                    return;
                }
                if (job.state === 'staging') {
                    this._message(I18n.t('update.staging'));
                    this._timer = window.setTimeout(tick, 800);
                    return;
                }
                if (job.state === 'failed') {
                    this._busy = false;
                    await this._failed(job.error || 'download');
                    return;
                }
                if (job.state === 'done') {
                    this._message(I18n.t('update.restarting'));
                    const applied = await fetch('/api/update/apply', { method: 'POST' });
                    const result = await applied.json();
                    if (!result.ok) throw new Error(result.error || 'apply');
                    return;
                }
                this._timer = window.setTimeout(tick, 800);
            } catch (err) {
                this._busy = false;
                await this._failed(String(err.message || err));
            }
        };
        tick();
    },

    async _failed(message) {
        const answer = await showDialog({
            message: I18n.t('update.failed', { err: message }),
            buttons: [
                { label: I18n.t('update.retry'), value: 'retry', primary: true },
                { label: I18n.t('update.close'), value: 'close' },
            ],
        });
        if (answer === 'retry') await this._download();
    },
};

window.UpdatePanel = UpdatePanel;
