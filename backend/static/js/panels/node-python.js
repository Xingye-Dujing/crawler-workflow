/* node-python.js — Python 扩展节点的设置。
 *
 * The node stores a script ID, never code: the script lives in the account's reusable library
 * (`services.python_scripts`) so the AI, this panel and a later workflow all run the same reviewed
 * artifact. The panel therefore shows the library and a link to its manager, not an editor that
 * would fork a second copy into the canvas.
 */

function _pythonSelectOptions(scripts, current) {
    var rows = (scripts || []).map(function (item) {
        return { v: item.id, l: item.name + (item.builtin ? ' · built-in' : '') };
    });
    if (current && !rows.some(function (row) { return row.v === current; })) {
        rows.unshift({ v: current, l: current });
    }
    /* The placeholder is its own empty option above; passing the sentence here would make
       `selectOptionTags` emit a SECOND option whose VALUE is that sentence (it treats `defVal` as
       the stored value), and the async refill would then keep it as the node's script_id. */
    return selectOptionTags(rows, current, '');
}

function renderPythonSettings(nodeId, p) {
    var current = String(p.script_id || '');
    var html = '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('settings.pythonHint') + '</div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.pythonScript') + '</label>' +
        '<select class="settings-select" id="python-script-' + nodeId + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'script_id\',this.value)">' +
        '<option value="">' + I18n.t('settings.pythonPick') + '</option>' +
        _pythonSelectOptions([], current) +
        '</select>' +
        '<div style="display:flex;gap:6px;margin-top:4px;">' +
        '<button class="menu-btn" onclick="AIWorkspace.openStudio(\'python\')">' +
        I18n.t('settings.pythonManage') + '</button>' +
        '<span class="settings-hint" id="python-status-' + nodeId + '">' + I18n.t('settings.pythonChecking') + '</span>' +
        '</div></div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.pythonArgs') + '</label>' +
        '<textarea class="settings-input" rows="3" placeholder=\'{"column": "正文"}\' ' +
        'onchange="updateParam(\'' + nodeId + '\',\'args\',this.value)">' + escapeHtml(p.args || '{}') + '</textarea>' +
        '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.pythonArgsHint') + '</div></div>';
    html += renderParamInput(nodeId, p, 'timeout', 'settings.pythonTimeout', 'number', '120');
    html += renderParamInput(nodeId, p, 'max_rows', 'settings.pythonMaxRows', 'number', '200000');
    html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' +
        I18n.t('btn.previewData') + '</button></div>';
    setTimeout(function () { loadPythonNodePanel(nodeId, current); }, 0);
    return html;
}

/* Async fill: the option list and the interpreter verdict both come from the server, so the panel
   never keeps a second script table or guesses whether Python exists. */
function loadPythonNodePanel(nodeId, current) {
    fetch('/api/ai/python/scripts').then(function (response) { return response.json(); }).then(function (data) {
        if (!data.ok) return;
        var select = document.getElementById('python-script-' + nodeId);
        if (select) {
            select.innerHTML = '<option value="">' + I18n.t('settings.pythonPick') + '</option>' +
                _pythonSelectOptions(data.scripts || [], current || select.value);
        }
    }).catch(function () { /* the panel still works; the server refuses at run time by name */ });
    fetch('/api/ai/python/status').then(function (response) { return response.json(); }).then(function (data) {
        var hint = document.getElementById('python-status-' + nodeId);
        if (!hint) return;
        var report = data.report || {};
        if (report.available) {
            hint.textContent = 'Python ' + (report.version || '?') + ' · ' + (report.path || '');
        } else {
            hint.textContent = I18n.t('settings.pythonMissing');
        }
    }).catch(function () { /* status is advisory; the run still answers by name */ });
}
