/* node-analysis.js — 分析节点的设置：ops 清单与 renderAnalysisSettings
 *
 * Split out of `panels/settings.js` on 2026-10-29 as a contiguous slice (its own banner section),
 * so every name here is still a page global and inline `onclick="…"` handlers keep calling it by
 * name. index.html loads it right after `panels/settings.js`; `tests/frontend/splits.json` declares
 * it a companion of that file, so a harness naming one receives both.
 */
/* ── Analysis node settings ── */
/* The 分析 node's 步骤 list comes from the capability manifests (``NodeTypes.operators()``), so a
   new operator is a manifest and never an edit here. The per-operation FIELD blocks below are still
   hand-written; moving them onto the served parameter list is the remaining half of this migration. */
function analysisOps() {
    var rows = (typeof NodeTypes !== 'undefined' && NodeTypes.operators) ? NodeTypes.operators() : [];
    var ids = rows.map(function (row) { return row.id; });
    /* A cold page that has not loaded the catalogue yet still gets a usable form; an empty select is
       a form nobody can submit. */
    return ids.length ? ids : ['drop_null'];
}
/* The operator's form profile from the capability manifests; null before the catalogue loads. */
function analysisOperator(op) {
    if (typeof NodeTypes === 'undefined' || !NodeTypes.operator) return null;
    return NodeTypes.operator(op);
}

/* A migrated operator renders exactly the boxes its manifest declares, in declaration order.
   An empty ``panel`` means the hand-written block below still draws it: the migration shrinks. */
function renderOperatorPanel(nodeId, p, profile) {
    var html = '';
    (profile.panel || []).forEach(function (field) {
        if (field.hideWhen && field.hideWhen.length === 2) {
            if ((field.hideWhen[1] || []).indexOf(p[field.hideWhen[0]]) >= 0) return;
        }
        if (field.control === 'select') {
            html += renderParamSelect(nodeId, p, field.key, field.labelKey, field.default,
                (field.options || []).map(function (o) {
                    return { v: o.value, l: o.labelKey ? I18n.t(o.labelKey) : o.value };
                }));
        } else if (field.control === 'checkbox') {
            html += renderParamCheckbox(nodeId, p, field.key, field.labelKey, field.default);
        } else {
            html += renderParamInput(nodeId, p, field.key, field.labelKey, field.control, field.default, field.placeholder);
        }
        if (field.hintKey) {
            html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                I18n.t(field.hintKey) + '</div></div>';
        }
    });
    return html;
}

/* The matching modes a two-table step offers, pinned against
   services/analysis/matching.MATCH_MODES by tests/api/test_analysis_api.py. */
var MATCH_MODES = ['exact', 'trim', 'url', 'text', 'similar'];
var COUNT_MATCH_MODES = ['exact', 'trim', 'url', 'text'];
var KEEP_MODES = ['exclude', 'keep'];
var FILTER_OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains', 'in', 'not_in', 'is_null', 'not_null'];
var CONVERT_TYPES = ['str', 'int', 'float', 'bool', 'datetime'];

function renderAnalysisSettings(nodeId, p) {
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.operation') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'operation\',this.value)">' +
        selectOptionTags(
            analysisOps().map(function (op) {
                return { value: op, label: I18n.t('op.' + op) };
            }),
            p.operation,
            'drop_null'
        ) +
        '</select></div>';

    var op = p.operation || 'drop_null';
    /* A migrated operation's boxes come from its manifest; the blocks below are the shrinking rest. */
    var profile = analysisOperator(op);
    if (profile && profile.panel && profile.panel.length) {
        return html + renderOperatorPanel(nodeId, p, profile);
    }
    /* Every box below is declared in the operator manifests (panel=...) — this function only keeps
       the 分析 node's operation picker and the preview button. */
    if (op === 'anti_join') {
        /* 内容去重. The role readout is the point: "which table is filtered, which is the
           basis" is decided by wire order, so the panel names both parents instead of
           leaving the user to guess from two identical column boxes. */
        html += twoTableRoleLine(nodeId, boolParam(p.swap_tables, false),
            'settings.antiJoinKeepRole', 'settings.antiJoinBasisRole');
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.antiJoinHint') + '</div>';
        html += renderParamSelect(nodeId, p, 'keep_mode', 'settings.antiJoinKeep', 'exclude',
            [{ v: 'exclude', l: I18n.t('settings.antiJoinExclude') },
             { v: 'keep', l: I18n.t('settings.antiJoinKeepOnly') }]);
        html += renderParamInput(nodeId, p, 'left_on', 'settings.antiJoinLeft', 'text', '');
        html += renderParamInput(nodeId, p, 'right_on', 'settings.antiJoinRight', 'text', '');
        html += renderParamSelect(nodeId, p, 'match_mode', 'settings.matchMode', 'trim',
            MATCH_MODES.map(function (mode) {
                return { v: mode, l: I18n.t('matchMode.' + mode) };
            }));
        html += renderParamCheckbox(nodeId, p, 'ignore_case', 'settings.matchIgnoreCase', false);
        if ((p.match_mode || 'trim') === 'similar') {
            html += renderParamInput(nodeId, p, 'max_distance', 'settings.matchDistance', 'number', '8');
        }
        html += renderParamCheckbox(nodeId, p, 'swap_tables', 'settings.swapTables', false);
    }
    html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    return html;
}

registerSettingsRenderer('analysis', {
    html: function (nodeId, node) {
        return renderAnalysisSettings(nodeId, node.params);
    },
});

