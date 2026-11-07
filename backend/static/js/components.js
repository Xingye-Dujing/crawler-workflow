/* Environment & components modal - the browser's view of /api/environment and /api/components.
 *
 * The server owns every fact: which capability is usable and why, which component is installed, and
 * whether an install is running. This file only paints rows and polls a job; it never guesses that
 * a missing Chrome is "probably fine".
 */
const ComponentsPanel = {
    _jobTimer: null,
    _busy: false,
    _source: '',
    _sourceBusy: false,
    _stateKeys: {
        ok: 'env.stateOk',
        degraded: 'env.stateDegraded',
        missing: 'env.stateMissing',
        unknown: 'env.stateUnknown',
    },
    /* Which copy a capability row is using. The server names it per row; an unknown source is
       simply not annotated, never guessed. */
    _sourceKeys: {
        component: 'env.sourceComponent',
        system: 'env.sourceSystemNow',
        settings: 'env.sourceSettings',
    },

    open() {
        const panel = document.getElementById('components-panel');
        if (panel) panel.hidden = false;
        this.refresh();
    },

    close() {
        const panel = document.getElementById('components-panel');
        if (panel) panel.hidden = true;
        if (this._jobTimer) window.clearTimeout(this._jobTimer);
        this._jobTimer = null;
        this._busy = false;
    },

    _label(id) {
        const key = 'components.' + id + 'Label';
        const text = I18n.t(key);
        return text === key ? id : text;
    },

    async refresh() {
        const body = document.getElementById('components-body');
        if (body) body.textContent = I18n.t('env.loading');
        try {
            const [envRes, componentsRes] = await Promise.all([
                fetch('/api/environment'),
                fetch('/api/components'),
            ]);
            const env = await envRes.json();
            const components = await componentsRes.json();
            if (!env.ok) throw new Error(env.error || 'environment');
            this._render(env, components.ok ? components.components : []);
        } catch (err) {
            if (body) body.textContent = I18n.t('env.failed', { err: String(err.message || err) });
        }
    },

    _render(env, components) {
        const body = document.getElementById('components-body');
        if (!body) return;
        body.textContent = '';

        // Which copy the NEXT start uses: the stored preference, not this process's frozen
        // choice, so the button the user just pressed stays pressed until a restart applies it.
        this._source = env.component_source_preference || env.component_source || 'bundled';
        body.append(this._sourcePicker());

        const caps = document.createElement('div');
        for (const row of env.capabilities || []) {
            const line = document.createElement('div');
            line.className = 'env-row';
            const state = document.createElement('span');
            state.className = 'env-state ' + row.state;
            state.textContent = I18n.t(this._stateKeys[row.state] || 'env.stateUnknown');
            const name = document.createElement('span');
            name.className = 'env-name';
            name.textContent = I18n.t(row.label_key);
            const reason = document.createElement('span');
            reason.className = 'env-reason';
            reason.textContent = I18n.t(row.reason_key, row.reason_params || {});
            line.append(state, name, reason);
            const from = this._sourceKeys[row.source];
            if (from) {
                const tag = document.createElement('span');
                tag.className = 'env-src';
                tag.textContent = '· ' + I18n.t(from);
                line.append(tag);
            }
            caps.append(line);
        }
        body.append(caps);

        const title = document.createElement('div');
        title.className = 'env-hint';
        title.textContent = env.root || '';
        body.append(title);

        for (const component of components) {
            const line = document.createElement('div');
            line.className = 'env-component';
            const name = document.createElement('span');
            name.className = 'env-grow';
            name.textContent = this._label(component.id) + '  ' + component.version;
            const state = document.createElement('span');
            state.className = 'env-state ' + (component.installed ? 'ok' : 'missing');
            state.textContent = component.installed ? I18n.t('env.installed') : I18n.t('env.notInstalled');
            line.append(name, state);
            if (component.downloadable && (!component.installed || component.update)) {
                const button = document.createElement('button');
                button.className = 'panel-close';
                button.textContent = I18n.t(component.installed ? 'env.update' : 'env.install');
                button.onclick = () => this.install(component.id);
                line.append(button);
            }
            if (component.installed && component.id !== 'app') {
                const remove = document.createElement('button');
                remove.className = 'panel-close';
                remove.textContent = I18n.t('env.remove');
                remove.onclick = () => this.remove(component.id);
                line.append(remove);
            }
            body.append(line);
        }
    },

    _sourcePicker() {
        const row = document.createElement('div');
        row.className = 'env-source';
        const label = document.createElement('span');
        label.className = 'env-name';
        label.textContent = I18n.t('env.sourceTitle');
        row.append(label);
        for (const [value, key] of [['bundled', 'env.sourceBundled'], ['system', 'env.sourceSystem']]) {
            const button = document.createElement('button');
            button.className = 'env-source-choice';
            button.setAttribute('aria-pressed', value === this._source ? 'true' : 'false');
            button.textContent = I18n.t(key);
            button.onclick = () => this.setSource(value);
            row.append(button);
        }
        const hint = document.createElement('span');
        hint.className = 'env-reason';
        hint.textContent = I18n.t('env.sourceHint');
        row.append(hint);
        return row;
    },

    async setSource(value) {
        if (this._sourceBusy || value === this._source) return;
        this._sourceBusy = true;
        try {
            const response = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ component_source: value }),
            });
            const answer = await response.json();
            if (!answer.ok) throw new Error(answer.error || 'source');
            await this.refresh();
            this._restartHint();
        } catch (err) {
            await this._error(I18n.t('env.sourceFailed', { err: String(err.message || err) }));
        } finally {
            this._sourceBusy = false;
        }
    },

    async _error(message) {
        await showDialog({
            message: message,
            buttons: [{ label: I18n.t('env.close'), value: 'ok', primary: true }],
        });
    },

    async install(id) {
        if (this._busy) return;
        this._busy = true;
        const body = document.getElementById('components-body');
        if (body) {
            const note = document.createElement('div');
            note.className = 'env-hint';
            note.textContent = I18n.t('env.installing', { id: id });
            body.prepend(note);
        }
        try {
            const response = await fetch('/api/components/install', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: id }),
            });
            const answer = await response.json();
            if (!answer.ok) throw new Error(answer.error || 'install');
            this._poll(answer.job.id);
        } catch (err) {
            this._busy = false;
            await this._error(I18n.t('env.installFailed', { err: String(err.message || err) }));
        }
    },

    async remove(id) {
        const answer = await showDialog({
            message: I18n.t('env.removeConfirm', { id: this._label(id) }),
            buttons: [
                { label: I18n.t('env.remove'), value: 'yes', primary: true },
                { label: I18n.t('env.close'), value: 'no' },
            ],
        });
        if (answer !== 'yes') return;
        try {
            const response = await fetch('/api/components/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: id }),
            });
            const result = await response.json();
            if (!result.ok) throw new Error(result.error || 'remove');
            showToast(I18n.t('env.removed', { id: this._label(id) }));
            this.refresh();
        } catch (err) {
            await this._error(I18n.t('components.removeFailed', { component: id, err: String(err.message || err) }));
        }
    },

    _restartHint() {
        const body = document.getElementById('components-body');
        if (!body || body.querySelector('.env-restart')) return;
        const note = document.createElement('div');
        note.className = 'env-hint env-restart';
        note.textContent = I18n.t('env.restartHint');
        body.prepend(note);
    },

    _poll(jobId) {
        const tick = async () => {
            try {
                const response = await fetch('/api/components/jobs/' + encodeURIComponent(jobId));
                const answer = await response.json();
                if (!answer.ok) throw new Error(answer.error || 'job');
                if (answer.job.state === 'running') {
                    this._jobTimer = window.setTimeout(tick, 900);
                    return;
                }
                const finished = answer.job.state === 'done';
                if (answer.job.state === 'failed') {
                    await this._error(I18n.t('env.installFailed', { err: answer.job.error || '' }));
                } else if (finished) {
                    showToast(I18n.t('env.installDone', { id: answer.job.component }));
                }
                // The hint has to be painted AFTER the repaint, not before it: _render clears the
                // body, so a hint prepended first is wiped in the same tick and never shows.
                await this.refresh();
                if (finished) this._restartHint();
                this._busy = false;
            } catch (err) {
                this._busy = false;
                await this._error(I18n.t('env.installFailed', { err: String(err.message || err) }));
            }
        };
        tick();
    },
};

window.ComponentsPanel = ComponentsPanel;

function toggleComponentsPanel() {
    const panel = document.getElementById('components-panel');
    if (panel && panel.hidden) ComponentsPanel.open();
    else ComponentsPanel.close();
}

