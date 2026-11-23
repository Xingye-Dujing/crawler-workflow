/* node-chart.js — 可视化节点的设置：图型清单与 renderVisualizeSettings
 *
 * Split out of `panels/settings.js` on 2026-10-29 as a contiguous slice (its own banner section),
 * so every name here is still a page global and inline `onclick="…"` handlers keep calling it by
 * name. index.html loads it right after `panels/settings.js`; `tests/frontend/splits.json` declares
 * it a companion of that file, so a harness naming one receives both.
 *
 * The chart types, and which field each one reads, come from the server's chart registry through
 * `NodeTypes.charts()`. This file used to keep eight parallel arrays (which chart shows y, which
 * takes a source/target pair, which accepts annotations…); every one of them was a second opinion
 * about a fact the Python registry already declares, and a new chart type had to be added here as
 * well. A field box is now drawn because the profile names it, with the label and hint the
 * declaration carries.
 */
/* ── Visualize node settings ── */
// The two renderers, kept equal to app.py's `_CHART_ENGINES` by the contract test.
var ENGINES = [
    { value: 'echarts', label: 'ECharts' },
    { value: 'matplotlib', label: 'Matplotlib' },
];

//: The word-cloud palettes. Keys are the localized `wordcloudStyle.*` entries; the drawing side
//: declares the same names in `services/charts/style.WORDCLOUD_STYLES`, pinned by a contract test.
var WORDCLOUD_STYLES = ['vibrant', 'monoBlue', 'monoOrange', 'pastel', 'ocean', 'sunset', 'forest'];

//: The aggregations the panel offers. The engine accepts more (every pandas reduction), but a
//: figure a reader has to interpret offers these five.
var CHART_AGGREGATIONS = ['sum', 'mean', 'count', 'max', 'min'];

/* ── Widgets a chart's declaration can attach ──
   Each chart profile lists its free-standing controls by name (`annotations`, `center_node`, …),
   and a field may name one to render directly under itself (`agg` under the value it aggregates).
   A name nobody registered renders nothing rather than guessing at a control. */
var CHART_CONTROLS = {};
function registerChartControl(id, renderer) {
    CHART_CONTROLS[id] = renderer;
}

function _chartSelect(nodeId, param, items, stored, defVal) {
    return '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'' + param + '\',this.value)">' +
        selectOptionTags(items, stored, defVal) +
        '</select>';
}

function _aggOptions() {
    return CHART_AGGREGATIONS.map(function (a) {
        return { value: a, label: a };
    });
}

registerChartControl('agg', function (nodeId, p) {
    return '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg') + '</label>' +
        _chartSelect(nodeId, 'agg', _aggOptions(), p.agg, 'sum') + '</div>';
});
registerChartControl('agg2', function (nodeId, p) {
    return '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg2') + '</label>' +
        _chartSelect(nodeId, 'agg2', _aggOptions(), p.agg2, 'sum') + '</div>';
});
registerChartControl('center_node', function (nodeId, p) {
    // A co-occurrence graph over the whole candidate set is unreadable past ~20 words, and its
    // detail only surfaces on hover — which cannot be saved. Naming one word renders that word's
    // ego-network instead: a persistent figure that exports exactly as it previews. Blank leaves
    // the full graph.
    return '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.networkCenter') + '</label>' +
        '<input class="settings-input" value="' + escapeHtml(p.center_node || '') + '" placeholder="' +
        I18n.t('settings.networkCenterPlaceholder') + '" onchange="updateParam(\'' + nodeId + '\',\'center_node\',this.value)"></div>' +
        '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('hint.networkCenter') + '</div>';
});
registerChartControl('annotations', function (nodeId, p) {
    return '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartAnnotations') + '</label>' +
        '<input class="settings-input" value="' + escapeHtml(p.annotations || '') + '" ' +
        'placeholder="2024-05-19=公安通报; 2024-04-23=遗体打捞" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'annotations\',this.value)"></div>' +
        '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('hint.annotations') + '</div>';
});
registerChartControl('tokenize', function (nodeId, p) {
    return '<div class="settings-group"><label class="settings-checkbox-label">' +
        '<input type="checkbox" ' + (boolParam(p.tokenize, false) ? 'checked' : '') + ' ' +
        'onchange="updateParam(\'' + nodeId + '\',\'tokenize\',this.checked)"> ' +
        I18n.t('settings.tokenize') + '</label></div>';
});
registerChartControl('wordcloud_style', function (nodeId, p) {
    return '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.wordcloudStyle') + '</label>' +
        _chartSelect(
            nodeId,
            'wordcloud_style',
            WORDCLOUD_STYLES.map(function (s) {
                return { value: s, label: I18n.t('wordcloudStyle.' + s) };
            }),
            p.wordcloud_style,
            'vibrant'
        ) + '</div>';
});

/* The chart a blank `chart_type` means — read from the visualize manifest's parameter default,
   the same declaration a new node starts from, never a literal here. */
function _defaultChartType() {
    var specs = typeof NodeTypes !== 'undefined' && NodeTypes.ready() ? NodeTypes.params('visualize') : [];
    for (var i = 0; i < specs.length; i += 1) {
        if (specs[i].name === 'chart_type') return String(specs[i].default || '');
    }
    return '';
}

function _chartProfile(key) {
    if (typeof NodeTypes === 'undefined' || !NodeTypes.ready()) return null;
    return NodeTypes.chart(key);
}

/* One box per field the chart declares. A blank box shows the contract's default as its value
   without storing it: an untouched 主题距离图 node already reads pc1/pc2 at run time, so the panel
   may show what will happen — but opening a panel is not an edit and must not stamp a draft.
   A field the server's validation names (its ``param``) is outlined, so the raw parameter name in
   the problem sentence points at a box instead of asking the user to decode it. */
function renderChartField(nodeId, p, profile, field) {
    var stored = p[field.name];
    var fallback = (profile.defaults || {})[field.name];
    var value = stored === undefined || stored === null || String(stored) === '' ? fallback || '' : stored;
    var placeholder = field.placeholderKey ? I18n.t(field.placeholderKey) : field.placeholder || '';
    var bad = validationEntriesFor(nodeId).some(function (entry) {
        return entry.param === field.name;
    });
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t(field.labelKey) + '</label>' +
        '<input class="settings-input"' + (bad ? ' style="border-color:#d9705a"' : '') + ' value="' +
        escapeHtml(String(value)) + '" placeholder="' + escapeHtml(placeholder) +
        '" onchange="updateParam(\'' + nodeId + '\',\'' + field.name + '\',this.value)"></div>';
    if (field.hintKey) {
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t(field.hintKey) + '</div>';
    }
    if (field.control && CHART_CONTROLS[field.control]) {
        html += CHART_CONTROLS[field.control](nodeId, p, profile);
    }
    return html;
}

function _chartControl(nodeId, p, profile, name) {
    return CHART_CONTROLS[name] ? CHART_CONTROLS[name](nodeId, p, profile) : '';
}

function renderVisualizeSettings(nodeId, p) {
    var upstream = canvas.getUpstreamNodeId(nodeId);
    var upstreamNode = upstream ? canvas.nodes[upstream] : null;
    var charts = (typeof NodeTypes !== 'undefined' && NodeTypes.ready()) ? NodeTypes.charts() : [];
    /* 分词 is reachable both as a legacy node type and as a 处理 operation; this panel is
       loaded without canvas.js in some harnesses, so the rule stays local. */
    var isTokenizeUpstream = !!upstreamNode && (
        upstreamNode.type === 'tokenize' ||
        (upstreamNode.type === 'process' &&
            (upstreamNode.operation || (upstreamNode.params && upstreamNode.params.operation)) === 'tokenize')
    );

    // Simplified settings when connected to a tokenize node
    if (isTokenizeUpstream) {
        /* The tokenize columns have fixed names, so a never-configured chart still knows what to
           read. Filling them here is a DISPLAY default only — it must NOT call saveState() or
           updateNodeDisplay: opening a panel is not an edit, and stamping an undo step + the dirty
           dot every time the user merely looked at the node was the bug. The values reach the
           preview/executor from the params, so they are set without persisting. */
        if (!p.x_field) p.x_field = 'word';
        if (!p.y_field) p.y_field = 'frequency';
        if (!p.value_field) p.value_field = 'frequency';

        var defaultType = _defaultChartType();
        var ct = p.chart_type || defaultType;
        var tokenizeCharts = charts.filter(function (chart) {
            return chart.tokenize;
        });

        // Wordcloud only supports ECharts engine. Corrected in the params (not saved), because a
        // stored 'matplotlib' would fail the run — but a mere panel open still earns no undo step.
        var isWordcloud = ct === 'wordcloud';
        if (isWordcloud && p.engine !== 'echarts') p.engine = 'echarts';

        var html = '<div class="settings-group" style="margin-bottom:6px;">' +
            '<span style="font-size:11px;color:var(--accent);">' + I18n.t('settings.tokenizeUpstream') + '</span></div>' +
            (isWordcloud ? '' :
                '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.engine') + '</label>' +
                _chartSelect(nodeId, 'engine', ENGINES, p.engine, 'echarts') + '</div>') +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartType') + '</label>' +
            _chartSelect(
                nodeId,
                'chart_type',
                tokenizeCharts.map(function (chart) {
                    return { value: chart.key, label: I18n.t(chart.labelKey) };
                }),
                ct,
                defaultType
            ) + '</div>';
        if (isWordcloud) {
            html += _chartControl(nodeId, p, _chartProfile('wordcloud'), 'wordcloud_style');
        }
        html += '<div class="settings-group" style="display:flex;gap:8px;">' +
            '<button class="menu-btn toggle-on" onclick="dataNodes.previewVisualize(\'' + nodeId + '\')">' + I18n.t('btn.preview') + '</button>' +
            '<button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button>' +
            '</div>';
        return html;
    }

    var ct = p.chart_type || _defaultChartType();
    var profile = _chartProfile(ct);
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartType') + '</label>' +
        _chartSelect(
            nodeId,
            'chart_type',
            charts.map(function (chart) {
                return { value: chart.key, label: I18n.t(chart.labelKey) };
            }),
            ct,
            _defaultChartType()
        ) + '</div>' +
        '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.engine') + '</label>' +
        _chartSelect(nodeId, 'engine', ENGINES, p.engine, 'echarts') + '</div>';
    if (!profile) {
        /* A stored type the catalogue no longer serves: say so by name. A silent fall-through to
           the bar form would draw a chart nobody asked for, and validation refuses it too. */
        html += '<div class="settings-group settings-renderer-refusal">' +
            escapeHtml(I18n.t('settings.unknownChart', { chart: String(ct) })) + '</div>';
    } else {
        if (p.engine === 'matplotlib' && profile.echartsOnly) {
            html += '<div class="settings-group" style="color:#e67e22;font-size:11px;">' +
                I18n.t('warn.echartsOnly') + '</div>';
        }
        /* Fields in declaration order: which box a chart shows is the registry's answer, and its
           role is what the preflight checks the named column against. */
        for (var i = 0; i < profile.fields.length; i += 1) {
            html += renderChartField(nodeId, p, profile, profile.fields[i]);
        }
        for (var j = 0; j < profile.controls.length; j += 1) {
            html += _chartControl(nodeId, p, profile, profile.controls[j]);
        }
        if (profile.hintKey) {
            html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
                I18n.t(profile.hintKey) + '</div>';
        }
    }
    // LaTeX export is orthogonal to the renderer: the node still draws its chart, and these add a
    // compilable figure source / a booktabs three-line table as .txt next to it. Bibliometric views
    // have paper twins too; only model_agreement remains an on-screen-only matrix.
    if (!profile || profile.latexBuildable) {
        html += '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (boolParam(p.emit_latex, true) ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'emit_latex\',this.checked)"> ' +
            I18n.t('settings.emitLatex') + '</label>' +
            '<div style="font-size:11px;color:var(--text-dim);margin-top:2px;">' + I18n.t('settings.emitLatexHint') + '</div></div>';
        html += '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (boolParam(p.emit_latex_table, true) ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'emit_latex_table\',this.checked)"> ' +
            I18n.t('settings.emitLatexTable') + '</label></div>';
    }
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.title') + '</label>' +
        '<input class="settings-input" value="' + escapeHtml(p.title || '') + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'title\',this.value)"></div>';
    html += '<div class="settings-group" style="display:flex;gap:8px;flex-wrap:wrap;">' +
        '<button class="menu-btn toggle-on" onclick="dataNodes.previewVisualize(\'' + nodeId + '\')">' + I18n.t('btn.preview') + '</button>' +
        '<button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button>' +
        '<button class="menu-btn" onclick="chartStudio.openForNode(\'' + nodeId + '\')">' + I18n.t('btn.studio') + '</button>' +
        '</div>';
    return html;
}

registerSettingsRenderer('visualize', {
    html: function (nodeId, node) {
        return renderVisualizeSettings(nodeId, node.params);
    },
});
