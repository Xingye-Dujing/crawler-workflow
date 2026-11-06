/* Environment & components modal 鈥?the browser's view of /api/environment and /api/components.
 *
 * The server owns every fact: which capability is usable and why, which component is installed, and
 * whether an install is running. This file only paints rows and polls a job; it never guesses that
 * a missing Chrome is "probably fine".
 */
const ComponentsPanel = {
    _jobTimer: null,
    _stateKeys: {
        ok: 'env.stateOk',
        degraded: 'env.stateDegraded',
        missing: 'env.stateMissing',
        unknown: 'env.stateUnknown',
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
            body.append(line);
        }
    },

    async _error(message) {
        await showDialog({
            message: message,
            buttons: [{ label: I18n.t('env.close'), value: 'ok', primary: true }],
        });
    },

    async install(id) {
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
            await this._error(I18n.t('env.installFailed', { err: String(err.message || err) }));
        }
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
                if (answer.job.state === 'failed') {
                    await this._error(I18n.t('env.installFailed', { err: answer.job.error || '' }));
                } else if (answer.job.state === 'done') {
                    showToast(I18n.t('env.installDone', { id: answer.job.component }));
                }
                this.refresh();
            } catch (err) {
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

