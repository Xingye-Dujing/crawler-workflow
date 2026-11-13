/* settings-panel.js — the full settings page, rendered from /api/settings/schema.
 *
 * The old dropdown holds a handful of machine paths; this panel is the one place that
 * shows every crawl-affecting value, so a new key declared in
 * ``runtime/settings_schema.py`` appears here without a second table to keep in sync.
 *
 * It also owns the two actions the dropdown cannot express: the 慢速采集 preset
 * (apply/restore as one atomic step) and configuration export/import.
 */
const SettingsPanel = {
    schema: null,
    values: {},
    draft: {},
    readOnly: false,
    activeGroup: '',
    filter: '',
    _loading: false,

    async open() {
        closeDockedPanels('settings-panel');
        const panel = document.getElementById('settings-panel');
        if (!panel) return;
        panel.classList.add('open');
        panel.style.height = '';
        if (window.closeSettingsMenu) closeSettingsMenu();
        await this.refresh();
    },

    close() {
        const panel = document.getElementById('settings-panel');
        if (!panel) return;
        panel.classList.remove('open');
        panel.style.height = '';
    },

    toggle() {
        const panel = document.getElementById('settings-panel');
        if (!panel) return;
        if (panel.classList.contains('open')) this.close();
        else this.open();
    },

    async refresh() {
        if (this._loading) return;
        this._loading = true;
        try {
            if (window.AppSettings) await AppSettings.pull(true);
            const resp = await fetch('/api/settings/schema');
            const result = await resp.json();
            if (!result || !result.ok) {
                showToast(I18n.t('settingsPanel.schemaFailed'));
                return;
            }
            this.schema = result.schema;
            this.readOnly = result.read_only === true;
            this.installerAvailable = !(result.schema && result.schema.installer_available === false);
            this.values = Object.assign({}, (window.AppSettings && AppSettings._values) || {});
            this.draft = {};
            if (!this.activeGroup && this.schema.groups.length) this.activeGroup = this.schema.groups[0].id;
            this.render();
            this.renderPresetState();
            this.setStatus('');
        } catch (e) {
            showToast(I18n.t('settingsPanel.schemaFailed'));
        } finally {
            this._loading = false;
        }
    },

    _spec(key) {
        if (!this.schema) return null;
        return this.schema.settings.filter(function (s) { return s.key === key; })[0] || null;
    },

    _value(key) {
        if (Object.prototype.hasOwnProperty.call(this.draft, key)) return this.draft[key];
        return this.values[key];
    },

    setFilter(value) {
        this.filter = String(value || '').trim().toLowerCase();
        this.render();
    },

    showGroup(group) {
        this.activeGroup = group;
        this.filter = '';
        const box = document.getElementById('settings-panel-search');
        if (box) box.value = '';
        this.render();
    },

    _label(spec) {
        return I18n.t(spec.label || spec.key) || spec.key;
    },

    _hint(spec) {
        if (!spec.hint) return '';
        return I18n.t(spec.hint) || '';
    },

    _matches(spec) {
        if (!this.filter) return true;
        const hay = (this._label(spec) + ' ' + this._hint(spec) + ' ' + spec.key).toLowerCase();
        return hay.indexOf(this.filter) >= 0;
    },

    render() {
        if (!this.schema) return;
        const nav = document.getElementById('settings-panel-nav');
        if (nav) {
            nav.innerHTML = this.schema.groups.map(function (group) {
                const active = !this.filter && group.id === this.activeGroup ? ' active' : '';
                return '<button type="button" class="' + active + '" onclick="SettingsPanel.showGroup(\'' +
                    escapeHtml(group.id) + '\')">' + escapeHtml(I18n.t(group.label) || group.id) + '</button>';
            }, this).join('');
        }
        const form = document.getElementById('settings-panel-form');
        if (!form) return;
        const groups = this.filter
            ? this.schema.groups
            : this.schema.groups.filter(function (g) { return g.id === this.activeGroup; }, this);
        let html = '';
        groups.forEach(function (group) {
            const fields = this.schema.settings.filter(function (spec) {
                if (this.installerAvailable === false && spec.key === 'component_source') return false;
                return spec.group === group.id && this._matches(spec);
            }, this);
            if (!fields.length) return;
            html += '<div class="settings-group-title">' + escapeHtml(I18n.t(group.label) || group.id) + '</div>';
            html += fields.map(this._fieldHtml.bind(this)).join('');
        }, this);
        if (!html) html = '<div class="settings-field-hint">' + escapeHtml(I18n.t('settingsPanel.noMatch')) + '</div>';
        form.innerHTML = html;
        this._applyDisabledState();
    },

    _fieldHtml(spec) {
        const value = this._value(spec.key);
        const disabled = this.readOnly ? ' disabled' : '';
        const id = 'sp-' + spec.key;
        const label = escapeHtml(this._label(spec));
        const hint = this._hint(spec);
        const hintHtml = hint ? '<span class="settings-field-hint">' + escapeHtml(hint) + '</span>' : '';
        const badges = [];
        if (spec.restart) badges.push(I18n.t('settingsPanel.restartBadge'));
        if (spec.portable === false) badges.push(I18n.t('settingsPanel.machineBadge'));
        const badgeHtml = badges.length
            ? ' <span class="settings-field-hint">' + escapeHtml(badges.join(' · ')) + '</span>'
            : '';
        let control = '';
        if (spec.kind === 'bool') {
            control = '<label class="settings-checkbox-label"><input type="checkbox" id="' + escapeHtml(id) +
                '" data-setting="' + escapeHtml(spec.key) + '"' + (value ? ' checked' : '') +
                disabled + ' onchange="SettingsPanel.fieldChanged(this)"><span>' +
                (value ? escapeHtml(I18n.t('settingsPanel.on')) : escapeHtml(I18n.t('settingsPanel.off'))) +
                '</span></label>';
        } else if (spec.kind === 'enum') {
            const options = (spec.choices || []).map(function (choice) {
                const choiceLabel = I18n.t('set.choice.' + spec.key + '.' + choice);
                return '<option value="' + escapeHtml(choice) + '"' +
                    (String(value) === String(choice) ? ' selected' : '') + '>' +
                    escapeHtml(choiceLabel === 'set.choice.' + spec.key + '.' + choice ? choice : choiceLabel) +
                    '</option>';
            }).join('');
            control = '<select class="settings-select" id="' + escapeHtml(id) + '" data-setting="' +
                escapeHtml(spec.key) + '"' + disabled + ' onchange="SettingsPanel.fieldChanged(this)">' +
                options + '</select>';
        } else {
            const type = spec.kind === 'int' || spec.kind === 'float' ? 'number' : 'text';
            const step = spec.kind === 'float' ? '0.01' : (type === 'number' ? '1' : '');
            const bounds = (spec.minimum !== null && spec.minimum !== undefined ? ' min="' + spec.minimum + '"' : '') +
                (spec.maximum !== null && spec.maximum !== undefined ? ' max="' + spec.maximum + '"' : '') +
                (step ? ' step="' + step + '"' : '');
            control = '<input class="settings-input" type="' + type + '" id="' + escapeHtml(id) +
                '" data-setting="' + escapeHtml(spec.key) + '" value="' + escapeHtml(value === undefined || value === null ? '' : value) +
                '"' + bounds + disabled + ' onchange="SettingsPanel.fieldChanged(this)">';
        }
        const reset = this.readOnly
            ? ''
            : '<button type="button" class="settings-field-reset" title="' + escapeHtml(I18n.t('settingsPanel.reset')) +
              '" onclick="SettingsPanel.resetField(\'' + escapeHtml(spec.key) + '\')">' +
              escapeHtml(I18n.t('settingsPanel.resetShort')) + '</button>';
        return '<div class="settings-field" data-group="' + escapeHtml(spec.group) + '" data-key="' +
            escapeHtml(spec.key) + '"><div class="settings-field-label">' + label + badgeHtml + hintHtml +
            '</div><div>' + control + '</div><div>' + reset + '</div></div>';
    },

    _applyDisabledState() {
        const save = document.getElementById('settings-panel-save');
        if (save) save.disabled = this.readOnly;
        const exportBtn = document.getElementById('settings-export-btn');
        if (exportBtn) exportBtn.disabled = this.readOnly;
        const importBtn = document.getElementById('settings-import-btn');
        if (importBtn) importBtn.disabled = this.readOnly;
        const include = document.getElementById('settings-include-machine');
        if (include) {
            include.disabled = this.readOnly;
            /* Machine paths are an installer-build concept: the source checkout reads
               this machine directly, so exporting them is neither needed nor offered.
               `display` rather than the `hidden` attribute: the label is a flex box,
               and its own display rule beats the UA's [hidden] rule. */
            const row = include.closest && include.closest('.settings-checkbox-label');
            if (row) row.style.display = this.installerAvailable === false ? 'none' : '';
        }
    },

    fieldChanged(el) {
        const key = (el && el.getAttribute && el.getAttribute('data-setting')) || (el && el.dataset && el.dataset.setting);
        if (!key) return;
        let value;
        if (el.type === 'checkbox') value = !!el.checked;
        else if (el.type === 'number') value = el.value === '' ? '' : Number(el.value);
        else value = el.value;
        this.draft[key] = value;
        this.setStatus(I18n.t('settingsPanel.unsaved'));
        if (el.type === 'checkbox') {
            const span = el.closest && el.closest('.settings-checkbox-label');
            if (span) span.querySelector('span').textContent = value ? I18n.t('settingsPanel.on') : I18n.t('settingsPanel.off');
        }
    },

    async resetField(key) {
        const spec = this._spec(key);
        if (!spec) return;
        this.draft[key] = spec.default;
        const el = document.getElementById('sp-' + key);
        if (el) {
            if (el.type === 'checkbox') {
                el.checked = !!spec.default;
                const span = el.closest && el.closest('.settings-checkbox-label');
                if (span) span.querySelector('span').textContent = spec.default ? I18n.t('settingsPanel.on') : I18n.t('settingsPanel.off');
            } else {
                el.value = spec.default === undefined || spec.default === null ? '' : spec.default;
            }
        }
        this.setStatus(I18n.t('settingsPanel.unsaved'));
    },

    setStatus(text) {
        const box = document.getElementById('settings-panel-status');
        if (box) box.textContent = text || '';
    },

    _setWarnings(warnings) {
        const box = document.getElementById('settings-panel-warnings');
        if (!box) return;
        box.innerHTML = (warnings || []).map(function (w) {
            return '<div>• ' + escapeHtml(w) + '</div>';
        }).join('');
    },

    async save() {
        if (this.readOnly) {
            showToast(I18n.t('toast.setReadOnly'));
            return;
        }
        if (!Object.keys(this.draft).length) {
            showToast(I18n.t('toast.setNoChange'));
            return;
        }
        const btn = document.getElementById('settings-panel-save');
        if (btn) btn.disabled = true;
        try {
            const resp = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: this.draft }),
            });
            const result = await resp.json();
            if (result.ok) {
                if (window.AppSettings) {
                    AppSettings._values = result.settings || {};
                    AppSettings.applyPresetState(result.preset);
                }
                this.values = Object.assign({}, result.settings || {});
                this.draft = {};
                this._setWarnings(result.warnings || []);
                this.render();
                this.renderPresetState();
                const warns = result.warnings || [];
                showToast(warns.length ? I18n.t('toast.setSavedWarn') + ' ' + warns.join('；') : I18n.t('toast.setSaved'));
                this.setStatus(I18n.t('settingsPanel.saved'));
                if (window.AppSettings) {
                    AppSettings.applyToPanel();
                    AppSettings.refreshAfterSave();
                }
            } else {
                showToast(I18n.t('toast.setSaveFail') + ': ' + (result.error || ''));
            }
        } catch (e) {
            showToast(I18n.t('toast.setSaveFail') + ': ' + e.message);
        } finally {
            if (btn) btn.disabled = this.readOnly;
        }
    },

    async renderPresetState() {
        const card = document.getElementById('settings-preset-card');
        if (!card || !this.schema) return;
        const preset = (window.AppSettings && AppSettings.preset) ||
            (typeof AppSettings !== 'undefined' && AppSettings.preset) || null;
        const meta = (this.schema.presets || {}).slow || {};
        const title = I18n.t(meta.label || 'set.presetSlow');
        const hint = I18n.t(meta.hint || 'set.presetSlowHint');
        let html = '<h3>' + escapeHtml(title) + '</h3><p>' + escapeHtml(hint) + '</p>';
        if (preset && preset.active) {
            html += '<p><strong>' + escapeHtml(I18n.t('settingsPanel.presetActive')) + '</strong>' +
                (preset.customized ? ' · ' + escapeHtml(I18n.t('settingsPanel.presetCustomized')) : '') +
                (preset.applied_at ? ' · ' + escapeHtml(preset.applied_at) : '') + '</p>';
            html += '<div class="settings-preset-actions"><button class="menu-btn" type="button" ' +
                (this.readOnly ? 'disabled ' : '') + 'onclick="SettingsPanel.restorePreset()">' +
                escapeHtml(I18n.t('settingsPanel.presetRestore')) + '</button></div>';
        } else {
            html += '<div class="settings-preset-actions"><button class="menu-btn" type="button" ' +
                (this.readOnly ? 'disabled ' : '') + 'onclick="SettingsPanel.applyPreset()">' +
                escapeHtml(I18n.t('settingsPanel.presetApply')) + '</button></div>';
        }
        card.innerHTML = html;
    },

    async applyPreset() {
        if (this.readOnly) return;
        try {
            const resp = await fetch('/api/settings/preset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'apply', preset: 'slow' }),
            });
            const result = await resp.json();
            if (!result.ok) {
                showToast((result && result.error) || I18n.t('toast.setSaveFail'));
                return;
            }
            this.values = Object.assign({}, result.settings || {});
            this.draft = {};
            if (window.AppSettings) {
                AppSettings._values = result.settings || {};
                AppSettings.applyPresetState(result.preset);
                AppSettings.applyToPanel();
                AppSettings.refreshAfterSave();
            }
            this.render();
            this.renderPresetState();
            this._setWarnings(result.warnings || []);
            showToast(I18n.t('settingsPanel.presetApplied'));
        } catch (e) {
            showToast(I18n.t('toast.setSaveFail') + ': ' + e.message);
        }
    },

    async restorePreset() {
        if (this.readOnly) return;
        const preset = (window.AppSettings && AppSettings.preset) || {};
        const message = (preset.customized
            ? I18n.t('settingsPanel.restoreCustomized') + '\n\n'
            : '') + I18n.t('settingsPanel.restoreConfirm');
        const choice = await showDialog({
            message: message,
            buttons: [
                { label: I18n.t('settingsPanel.presetRestore'), value: 'go', primary: true },
                { label: I18n.t('dialog.cancel'), value: null },
            ],
        });
        if (choice !== 'go') return;
        try {
            const resp = await fetch('/api/settings/preset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'restore' }),
            });
            const result = await resp.json();
            if (!result.ok) {
                showToast((result && result.error) || I18n.t('toast.setSaveFail'));
                return;
            }
            this.values = Object.assign({}, result.settings || {});
            this.draft = {};
            if (window.AppSettings) {
                AppSettings._values = result.settings || {};
                AppSettings.applyPresetState(result.preset);
                AppSettings.applyToPanel();
                AppSettings.refreshAfterSave();
            }
            this.render();
            this.renderPresetState();
            this._setWarnings(result.warnings || []);
            showToast(I18n.t('settingsPanel.presetRestored'));
        } catch (e) {
            showToast(I18n.t('toast.setSaveFail') + ': ' + e.message);
        }
    },

    exportSettings() {
        if (this.readOnly) return;
        const include = document.getElementById('settings-include-machine');
        const flag = include && include.checked ? '1' : '0';
        window.location.href = window.__cu('/api/settings/export?include_machine=' + flag);
    },

    pickImport() {
        if (this.readOnly) return;
        const input = document.getElementById('settings-import-file');
        if (input) {
            input.value = '';
            input.click();
        }
    },

    async importFile(input) {
        const file = input && input.files && input.files[0];
        if (!file) return;
        let payload;
        try {
            payload = JSON.parse(await file.text());
        } catch (e) {
            showToast(I18n.t('settingsPanel.importBadJson'));
            return;
        }
        const include = document.getElementById('settings-include-machine');
        const includeMachine = !!(include && include.checked);
        let preview;
        try {
            const resp = await fetch('/api/settings/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ payload: payload, mode: 'merge', include_machine: includeMachine, dry_run: true }),
            });
            preview = await resp.json();
        } catch (e) {
            showToast(I18n.t('toast.setSaveFail') + ': ' + e.message);
            return;
        }
        if (!preview || !preview.ok) {
            showToast((preview && preview.error) || I18n.t('settingsPanel.importFailed'));
            return;
        }
        const changed = preview.changed || [];
        const skipped = preview.skipped || [];
        const warnings = preview.warnings || [];
        let summary = I18n.t('settingsPanel.importSummary')
            .replace('{changed}', String(changed.length))
            .replace('{skipped}', String(skipped.length));
        if (changed.length) summary += '\n' + changed.slice(0, 12).join(', ') + (changed.length > 12 ? '…' : '');
        if (warnings.length) summary += '\n\n' + warnings.join('\n');
        const choice = await showDialog({
            message: summary,
            buttons: [
                { label: I18n.t('settingsPanel.importApply'), value: 'go', primary: true },
                { label: I18n.t('dialog.cancel'), value: null },
            ],
        });
        if (choice !== 'go') return;
        try {
            const resp = await fetch('/api/settings/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ payload: payload, mode: 'merge', include_machine: includeMachine, dry_run: false }),
            });
            const result = await resp.json();
            if (!result.ok) {
                showToast((result && result.error) || I18n.t('settingsPanel.importFailed'));
                return;
            }
            showToast(I18n.t('settingsPanel.importDone'));
            setTimeout(function () { window.location.reload(); }, 600);
        } catch (e) {
            showToast(I18n.t('toast.setSaveFail') + ': ' + e.message);
        }
    },

    onLanguageChange() {
        if (this.schema) {
            this.render();
            this.renderPresetState();
        }
    },
};

window.SettingsPanel = SettingsPanel;
