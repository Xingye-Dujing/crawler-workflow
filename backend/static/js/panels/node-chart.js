/* node-chart.js — 可视化节点的设置：图型清单与 renderVisualizeSettings
 *
 * Split out of `panels/settings.js` on 2026-10-29 as a contiguous slice (its own banner section),
 * so every name here is still a page global and inline `onclick="…"` handlers keep calling it by
 * name. index.html loads it right after `panels/settings.js`; `tests/frontend/splits.json` declares
 * it a companion of that file, so a harness naming one receives both.
 */
/* ── Visualize node settings ── */
var CHART_TYPES = ['bar', 'line', 'dual_line', 'stack_pct', 'topic_map', 'topic_terms', 'pie', 'scatter', 'histogram', 'box', 'heatmap', 'model_agreement', 'sankey', 'network', 'knowledge_graph', 'cluster_timeline', 'burst', 'timezone', 'circular', 'landscape', 'biblio_heatmap', 'graph3d', 'variation', 'dual_map', 'geo_map', 'sentiment_overlay', 'topic_overlay', 'concentric', 'wordcloud', 'map'];
var BIBLIO_CHARTS = ['knowledge_graph', 'cluster_timeline', 'burst', 'timezone', 'circular', 'landscape', 'biblio_heatmap', 'graph3d', 'variation', 'dual_map', 'geo_map', 'sentiment_overlay', 'topic_overlay', 'concentric'];

// The two renderers, kept equal to app.py's `_CHART_ENGINES` by the contract test.
var ENGINES = [
    { value: 'echarts', label: 'ECharts' },
    { value: 'matplotlib', label: 'Matplotlib' },
];

/* Field labels change meaning per chart type (e.g. x/y are two category
   dimensions for heatmap/sankey, not "category + value" like bar/line). */
var CHART_X_LABEL_KEY = {
    heatmap: 'settings.xFieldCat1', sankey: 'settings.sourceField', network: 'settings.sourceField',
    wordcloud: 'settings.textField', map: 'settings.regionField',
};
var CHART_Y_LABEL_KEY = { heatmap: 'settings.yFieldCat2', sankey: 'settings.targetField', network: 'settings.targetField' };
var CHARTS_WITH_Y_AS_CATEGORY = ['heatmap', 'sankey', 'network'];
var CHARTS_WITH_VALUE_FIELD = ['heatmap', 'sankey', 'network', 'wordcloud', 'map', 'topic_map'];
var CHARTS_NO_Y = ['histogram', 'wordcloud', 'map', 'stack_pct', 'model_agreement'].concat(BIBLIO_CHARTS).concat(CHARTS_WITH_Y_AS_CATEGORY);
// The right-hand scale, which only 双轴折线 asks for. Kept equal to the backend's
// ECHARTS_ONLY_TYPES by tests/unit/test_visualization.py, because the renderer that cannot
// draw two axes refuses by name and the panel must not offer it silently.
// 显著词图 asks for y2 too, but as a SECOND BAR SERIES on the same scale, not as a second
// axis — the two counts are in the same unit, and splitting them across scales would let a
// rare word look bigger than a common one.
var CHARTS_WITH_Y2 = ['dual_line', 'topic_terms'];
var CHARTS_WITH_LABEL = ['topic_map'];
var ECHARTS_ONLY_CHARTS = ['wordcloud', 'sankey', 'map', 'dual_line', 'topic_map', 'topic_terms', 'network', 'model_agreement', 'knowledge_graph', 'cluster_timeline', 'burst', 'timezone', 'circular', 'landscape', 'biblio_heatmap', 'graph3d', 'variation', 'dual_map', 'geo_map', 'sentiment_overlay', 'topic_overlay', 'concentric'];
// The types that draw a vertical line at one x-axis label, so an event ("5/19 公安通报") sits
// on the curve it explains. Kept equal to the backend's ANNOTATED_TYPES by
// tests/unit/test_visualization.py: a box the figure cannot honour would drop the date in
// silence, which is the one outcome a reader of the figure must not be left with.
var CHARTS_WITH_ANNOTATIONS = ['bar', 'line', 'dual_line'];

function renderVisualizeSettings(nodeId, p) {
    var upstream = canvas.getUpstreamNodeId(nodeId);
    var upstreamNode = upstream ? canvas.nodes[upstream] : null;
    var isTokenizeUpstream = upstreamNode && upstreamNode.type === 'tokenize';

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

        var ct = p.chart_type || 'bar';
        var TOKENIZE_CHART_TYPES = ['bar', 'pie', 'wordcloud'];

        // Wordcloud only supports ECharts engine. Corrected in the params (not saved), because a
        // stored 'matplotlib' would fail the run — but a mere panel open still earns no undo step.
        var isWordcloud = ct === 'wordcloud';
        if (isWordcloud && p.engine !== 'echarts') p.engine = 'echarts';

        var html = '<div class="settings-group" style="margin-bottom:6px;">' +
            '<span style="font-size:11px;color:var(--accent);">' + I18n.t('settings.tokenizeUpstream') + '</span></div>' +
            (isWordcloud ? '' :
                '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.engine') + '</label>' +
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'engine\',this.value)">' +
                selectOptionTags(ENGINES, p.engine, 'echarts') +
                '</select></div>') +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartType') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'chart_type\',this.value)">' +
            selectOptionTags(
                TOKENIZE_CHART_TYPES.map(function (c) {
                    return { value: c, label: I18n.t('chart.' + c) };
                }),
                ct,
                'bar'
            ) +
            '</select></div>';
        if (isWordcloud) {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.wordcloudStyle') + '</label>' +
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'wordcloud_style\',this.value)">' +
                ['vibrant', 'monoBlue', 'monoOrange', 'pastel', 'ocean', 'sunset', 'forest']
                    .map(function (s) { return '<option value="' + s + '"' + ((p.wordcloud_style || 'vibrant') === s ? ' selected' : '') + '>' + I18n.t('wordcloudStyle.' + s) + '</option>'; }).join('') +
                '</select></div>';
        }
        html += '<div class="settings-group" style="display:flex;gap:8px;">' +
            '<button class="menu-btn toggle-on" onclick="dataNodes.previewVisualize(\'' + nodeId + '\')">' + I18n.t('btn.preview') + '</button>' +
            '<button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button>' +
            '</div>';
        return html;
    }

    var ct = p.chart_type || 'bar';
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartType') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'chart_type\',this.value)">' +
        selectOptionTags(
            CHART_TYPES.map(function (c) {
                return { value: c, label: I18n.t('chart.' + c) };
            }),
            ct,
            'bar'
        ) +
        '</select></div>' +
        '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.engine') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'engine\',this.value)">' +
        selectOptionTags(ENGINES, p.engine, 'echarts') +
        '</select></div>';
    if (p.engine === 'matplotlib' && ECHARTS_ONLY_CHARTS.indexOf(ct) >= 0) {
        html += '<div class="settings-group" style="color:#e67e22;font-size:11px;">' + I18n.t('warn.echartsOnly') + '</div>';
    }
    if (BIBLIO_CHARTS.indexOf(ct) >= 0) {
        /* These four read the fixed columns a Bibliometrics node emits, so x/y boxes would
           promise a choice the builder never reads. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('biblio.ui.chartHint') + '</div>';
    } else if (ct === 'model_agreement') {
        // 模型一致率 reads the tidy multi-model table by three columns, not x/y: which names a
        // model, which holds its label, which aligns the same text across models. Defaults match
        // what the analysis step writes, so a fresh chart needs no typing.
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.modelField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.model_field || '模型') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'model_field\',this.value)"></div>';
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agreementLabelField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.agreement_label_field || '') + '" placeholder="emotion / tendency / sentiment" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'agreement_label_field\',this.value)"></div>';
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.idField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.id_field || '原行') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'id_field\',this.value)"></div>';
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.modelAgreement') + '</div>';
    } else {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t(CHART_X_LABEL_KEY[ct] || 'settings.xField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.x_field || '') + '" placeholder="category / numeric column" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'x_field\',this.value)"></div>';
    }
    if (ct === 'stack_pct') {
        // A 100%-stacked share takes its segments from a LIST of columns, not one y: each period
        // is normalised to 100%, so the box wants the positive/neutral/negative (or tendency,
        // emotion, …) columns that the analysis step just wrote.
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.stackFields') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.stack_fields || '') + '" placeholder="积极占比, 中性占比, 消极占比" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'stack_fields\',this.value)"></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.stackFields') + '</div>';
    }
    if (CHARTS_WITH_Y_AS_CATEGORY.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t(CHART_Y_LABEL_KEY[ct]) + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.y_field || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'y_field\',this.value)"></div>';
    } else if (CHARTS_NO_Y.indexOf(ct) < 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.yField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.y_field || '') + '" placeholder="optional: value column" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'y_field\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'agg\',this.value)">' +
            ['sum', 'mean', 'count', 'max', 'min'].map(function (a) { return '<option value="' + a + '"' + (p.agg === a ? ' selected' : '') + '>' + a + '</option>'; }).join('') +
            '</select></div>';
    }
    if (CHARTS_WITH_VALUE_FIELD.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.valueField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.value_field || '') + '" placeholder="optional: weight column (default = count)" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value_field\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'agg\',this.value)">' +
            ['sum', 'mean', 'count', 'max', 'min'].map(function (a) { return '<option value="' + a + '"' + (p.agg === a ? ' selected' : '') + '>' + a + '</option>'; }).join('') +
            '</select></div>';
    }
    if (ct === 'network') {
        // A co-occurrence graph over the whole candidate set is unreadable past ~20 words, and
        // its detail only surfaces on hover — which cannot be saved. Naming one word renders
        // that word's ego-network instead (it + the words directly co-occurring with it): a
        // persistent figure that exports exactly as it previews. Blank leaves the full graph.
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.networkCenter') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.center_node || '') + '" placeholder="' + I18n.t('settings.networkCenterPlaceholder') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'center_node\',this.value)"></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.networkCenter') + '</div>';
    }
    if (CHARTS_WITH_LABEL.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.labelField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.label_field || 'topic') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'label_field\',this.value)"></div>';
    }
    if (CHARTS_WITH_Y2.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.y2Field') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.y2_field || '') + '" placeholder="right-axis value column" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'y2_field\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg2') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'agg2\',this.value)">' +
            ['sum', 'mean', 'count', 'max', 'min'].map(function (a) { return '<option value="' + a + '"' + (p.agg2 === a ? ' selected' : '') + '>' + a + '</option>'; }).join('') +
            '</select></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.dualLine') + '</div>';
    }
    if (CHARTS_WITH_ANNOTATIONS.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartAnnotations') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.annotations || '') + '" ' +
            'placeholder="2024-05-19=公安通报; 2024-04-23=遗体打捞" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'annotations\',this.value)"></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.annotations') + '</div>';
    }
    if (ct === 'wordcloud') {
        html += '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (boolParam(p.tokenize, false) ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'tokenize\',this.checked)"> ' +
            I18n.t('settings.tokenize') + '</label></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.wordcloudStyle') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'wordcloud_style\',this.value)">' +
            ['vibrant', 'monoBlue', 'monoOrange', 'pastel', 'ocean', 'sunset', 'forest']
                .map(function (s) { return '<option value="' + s + '"' + ((p.wordcloud_style || 'vibrant') === s ? ' selected' : '') + '>' + I18n.t('wordcloudStyle.' + s) + '</option>'; }).join('') +
            '</select></div>';
    }
    if (ct === 'map') {
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.mapRegionNames') + '</div>';
    }
    // LaTeX export is orthogonal to the renderer: the node still draws its chart, and these add a
    // compilable figure source / a booktabs three-line table as .txt next to it. Bibliometric views
    // have paper twins too; only model_agreement remains an on-screen-only matrix.
    if (ct !== 'model_agreement') {
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

