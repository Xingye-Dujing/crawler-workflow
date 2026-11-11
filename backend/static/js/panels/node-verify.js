/* node-verify.js — 采集校验节点的设置：两张表的角色、比较列、条数口径与输出方式。
 *
 * Split out of `panels/settings.js` the way `node-analysis.js` / `node-biblio.js` /
 * `node-chart.js` were: every name here stays a page global (inline `onclick="…"` handlers
 * call `updateParam` by name), and `tests/frontend/splits.json` declares this file a
 * companion of `panels/settings.js`, so a harness naming one receives both.
 *
 * The panel says WHICH upstream fills WHICH role — the roles are decided by connection order
 * (`panels/settings.js: twoTableRoleLine` reads the same wires the engine does), and a user
 * wiring "post table → comment table → audit" must be able to check that order without
 * opening the JSON.
 */

/* The parent the audit will read as its RESULT table (the second wire, or the first when the
   two tables are swapped). Only the panel reads this: the executor is handed the rows and the
   console prints the resolved names. */
function _verifyResultParent(nodeId, swapped) {
    if (typeof canvas === 'undefined' || !canvas || typeof canvas._tableParentsOf !== 'function') return null;
    var parents = canvas._tableParentsOf(nodeId);
    return parents[swapped ? 0 : 1] || null;
}

/* If the result upstream is a crawl node with a 每篇上限, comparing against the site's full
   count would call every article short. The panel cannot change another node's setting, so it
   says what it found and lets the user copy it into 每篇上限. */
function _verifyLimitHint(nodeId, swapped) {
    var parent = _verifyResultParent(nodeId, swapped);
    if (!parent || !canvas.nodes[parent.id]) return '';
    var limit = parseInt((canvas.nodes[parent.id].params || {}).comment_limit, 10);
    if (!(limit > 0)) return '';
    return '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('settings.verifyLimitDetected', { n: limit }) + '</div>';
}

function renderVerifySettings(nodeId, p) {
    var swapped = boolParam(p.swap_tables, false);
    var html = '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('settings.verifyHint') + '</div>';
    html += twoTableRoleLine(
        nodeId,
        swapped,
        'settings.verifyListRole',
        'settings.verifyResultRole'
    );
    html += renderParamInput(nodeId, p, 'input_key_column', 'settings.verifyListKey', 'text', '链接');
    html += renderParamInput(nodeId, p, 'result_key_column', 'settings.verifyResultKey', 'text', '文章URL');
    html += renderParamInput(nodeId, p, 'expected_count_column', 'settings.verifyCountColumn', 'text', '评论数');
    html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('settings.verifyCountHint') + '</div>';
    html += renderParamSelect(nodeId, p, 'match_mode', 'settings.matchMode', 'url',
        COUNT_MATCH_MODES.map(function (mode) {
            return { v: mode, l: I18n.t('matchMode.' + mode) };
        }));
    html += renderParamInput(nodeId, p, 'tolerance', 'settings.verifyTolerance', 'number', '0');
    html += renderParamInput(nodeId, p, 'per_link_limit', 'settings.verifyPerLinkLimit', 'number', '');
    html += _verifyLimitHint(nodeId, swapped);
    html += renderParamSelect(nodeId, p, 'output_mode', 'settings.verifyOutputMode', 'gaps',
        [{ v: 'gaps', l: I18n.t('settings.verifyOutGaps') },
         { v: 'all', l: I18n.t('settings.verifyOutAll') }]);
    html += renderParamCheckbox(nodeId, p, 'swap_tables', 'settings.swapTables', false);
    html += renderParamCheckbox(nodeId, p, 'ignore_case', 'settings.matchIgnoreCase', false);
    html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('settings.verifyRetryHint') + '</div>';
    html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' +
        I18n.t('btn.previewData') + '</button></div>';
    return html;
}
