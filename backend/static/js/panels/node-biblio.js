/* node-biblio.js — 文献计量与融合节点的设置：实体/连线/剪枝清单与两张面板
 *
 * Split out of `panels/settings.js` on 2026-10-29 as a contiguous slice (its own banner section),
 * so every name here is still a page global and inline `onclick="…"` handlers keep calling it by
 * name. index.html loads it right after `panels/settings.js`; `tests/frontend/splits.json` declares
 * it a companion of that file, so a harness naming one receives both.
 */
/* ── Bibliometrics node settings ── */
var BIBLIO_ENTITY_TYPES = ['keyword', 'author', 'institution', 'country', 'term', 'category', 'journal', 'source', 'funder', 'grant', 'document_cocitation', 'author_cocitation', 'journal_cocitation', 'article', 'document', 'bibliographic_coupling'];
var BIBLIO_SELECTION_MODES = ['top_n', 'top_pct', 'g_index', 'threshold'];
var BIBLIO_LINK_MEASURES = ['cosine', 'dice', 'jaccard', 'association'];
var BIBLIO_COUNTING = ['full', 'fractional'];
var BIBLIO_PRUNING_MODES = ['none', 'mst', 'pathfinder'];
var BIBLIO_PRUNING_SCOPES = ['slices', 'merged'];
var BIBLIO_PATHFINDER_R = ['1', '2', 'inf'];
var BIBLIO_LABEL_METHODS = ['llr', 'lsi', 'mi', 'tfidf'];
var BIBLIO_LABEL_SOURCES = ['all', 'title', 'abstract', 'keywords', 'author'];
var BIBLIO_OUTPUT_SHAPES = ['nodes', 'edges', 'clusters', 'bursts', 'variation', 'dual_map'];

function biblioOption(value, label) {
    /* Both shapes: `selectOptionTags` reads value/label, `renderParamSelect`
       reads v/l. One list, so a new entity type cannot appear in one control
       and be missing from the other. The key prefixes are spelled literally so
       the i18n reachability audit can see every label this panel renders. */
    return { value: value, label: label, v: value, l: label };
}
function biblioEntityOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.entity.' + value)); });
}
function biblioSelectionOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.selection.' + value)); });
}
function biblioMeasureOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.measure.' + value)); });
}
function biblioCountingOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.counting.' + value)); });
}
function biblioPruningOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.pruning.' + value)); });
}
function biblioPruningScopeOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.scope.' + value)); });
}
function biblioPathfinderOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.pfnetR.' + value)); });
}
function biblioLabelOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.label.' + value)); });
}
function biblioLabelSourceOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.label_source.' + value)); });
}
function biblioOutputShapeOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.shape.' + value)); });
}
var BIBLIO_COUPLING_TYPES = ['document', 'bibliographic_coupling', 'journal', 'source'];
function isBiblioCoupling(entity) {
    return BIBLIO_COUPLING_TYPES.indexOf(entity) >= 0;
}

function updateBiblioEntity(nodeId, entity) {
    updateParam(nodeId, 'entity_type', entity);
    /* Coupling nodes are the citing papers themselves, so burst detection has
       no meaning there. Uncheck it as a derived default when that mode is
       chosen; an EXPLICIT true is still refused by the backend by name. */
    if (isBiblioCoupling(entity)) updateParam(nodeId, 'burst', false);
    openSettings(nodeId);
}

/* One candidate list per role, in the order the fold tries them. */
var FUSE_ROLE_FIELDS = [
    ['entity_columns', 'fuse.ui.entityColumns'],
    ['year_columns', 'fuse.ui.yearColumns'],
    ['title_columns', 'fuse.ui.titleColumns'],
    ['author_columns', 'fuse.ui.authorColumns'],
    ['affiliation_columns', 'fuse.ui.affiliationColumns'],
    ['text_columns', 'fuse.ui.textColumns'],
    ['reference_columns', 'fuse.ui.referenceColumns'],
    ['source_columns', 'fuse.ui.sourceColumns']
];

function renderFuseSettings(nodeId, p) {
    var html = '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('fuse.ui.hint') + '</div>';
    FUSE_ROLE_FIELDS.forEach(function (field) {
        html += renderParamInput(nodeId, p, field[0], field[1], 'text', '');
    });
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('fuse.ui.sourceLabels') + '</label>' +
        '<textarea class="settings-input" rows="3" placeholder="' +
        escapeHtml(I18n.t('fuse.ui.sourceLabelsPlaceholder')) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'source_labels\',this.value)">' +
        escapeHtml(p.source_labels || '') + '</textarea>' +
        '<div class="settings-hint">' + I18n.t('fuse.ui.sourceLabelsHint') + '</div></div>';
    html += renderParamCheckbox(nodeId, p, 'keep_undated', 'fuse.ui.keepUndated', true);
    html += renderParamCheckbox(nodeId, p, 'export_files', 'fuse.ui.exportFiles', false);
    return html;
}

function renderBiblioSettings(nodeId, p) {
    var entity = p.entity_type || 'keyword';
    var html = '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('biblio.ui.hint') + '</div>';

    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.entityType') + '</label>' +
        '<select class="settings-select" onchange="updateBiblioEntity(\'' + nodeId + '\', this.value)">' +
        selectOptionTags(biblioEntityOptions(BIBLIO_ENTITY_TYPES), entity, 'keyword') +
        '</select></div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.columns') + '</div>';
    html += renderParamInput(nodeId, p, 'entity_column', 'biblio.ui.entityColumn', 'text', '') +
        renderParamInput(nodeId, p, 'year_column', 'biblio.ui.yearColumn', 'text', '年份') +
        renderParamInput(nodeId, p, 'title_column', 'biblio.ui.titleColumn', 'text', '题名') +
        renderParamInput(nodeId, p, 'abstract_column', 'biblio.ui.abstractColumn', 'text', '摘要') +
        renderParamInput(nodeId, p, 'reference_column', 'biblio.ui.referenceColumn', 'text', '参考文献') +
        renderParamInput(nodeId, p, 'tc_column', 'biblio.ui.tcColumn', 'text', '引用次数') +
        renderParamInput(nodeId, p, 'usage_column', 'biblio.ui.usageColumn', 'text', '使用次数') +
        '<div class="settings-hint">' + I18n.t('biblio.ui.columnsHint') + '</div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.network') + '</div>';
    html += renderParamInput(nodeId, p, 'time_start', 'biblio.ui.timeStart', 'number', '') +
        renderParamInput(nodeId, p, 'time_end', 'biblio.ui.timeEnd', 'number', '') +
        renderParamInput(nodeId, p, 'slice_years', 'biblio.ui.sliceYears', 'number', 1) +
        renderParamInput(nodeId, p, 'look_back_years', 'biblio.ui.lookBackYears', 'number', 0) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.timeHint') + '</div>';
    html += renderParamSelect(nodeId, p, 'selection', 'biblio.ui.selection', 'top_n', biblioSelectionOptions(BIBLIO_SELECTION_MODES)) +
        renderParamInput(nodeId, p, 'top_n', 'biblio.ui.topN', 'number', 50) +
        renderParamInput(nodeId, p, 'top_pct', 'biblio.ui.topPct', 'number', 10) +
        renderParamInput(nodeId, p, 'g_index', 'biblio.ui.gIndex', 'number', 25) +
        renderParamInput(nodeId, p, 'min_count', 'biblio.ui.minCount', 'number', 2) +
        renderParamInput(nodeId, p, 'threshold_c', 'biblio.ui.thresholdC', 'number', 0) +
        renderParamInput(nodeId, p, 'threshold_cc', 'biblio.ui.thresholdCC', 'number', 1) +
        renderParamInput(nodeId, p, 'threshold_ccv', 'biblio.ui.thresholdCCV', 'number', 0) +
        renderParamInput(nodeId, p, 'min_tc', 'biblio.ui.minTc', 'number', '') +
        renderParamInput(nodeId, p, 'min_usage', 'biblio.ui.minUsage', 'number', '') +
        renderParamCheckbox(nodeId, p, 'largest_component', 'biblio.ui.largestComponent', false);
    html += renderParamSelect(nodeId, p, 'link_measure', 'biblio.ui.linkMeasure', 'cosine', biblioMeasureOptions(BIBLIO_LINK_MEASURES)) +
        renderParamSelect(nodeId, p, 'counting', 'biblio.ui.counting', 'full', biblioCountingOptions(BIBLIO_COUNTING)) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.countingHint') + '</div>' +
        renderParamInput(nodeId, p, 'citation_expansion', 'biblio.ui.citationExpansion', 'number', 0) +
        renderParamInput(nodeId, p, 'max_links_per_node', 'biblio.ui.maxLinks', 'number', 10) +
        renderParamInput(nodeId, p, 'lrf', 'biblio.ui.lrf', 'number', 2.5) +
        renderParamSelect(nodeId, p, 'pruning', 'biblio.ui.pruning', 'none', biblioPruningOptions(BIBLIO_PRUNING_MODES)) +
        renderParamSelect(nodeId, p, 'pruning_scope', 'biblio.ui.pruningScope', 'slices', biblioPruningScopeOptions(BIBLIO_PRUNING_SCOPES)) +
        renderParamSelect(nodeId, p, 'pathfinder_r', 'biblio.ui.pathfinderR', 'inf', biblioPathfinderOptions(BIBLIO_PATHFINDER_R)) +
        renderParamInput(nodeId, p, 'pathfinder_lmax', 'biblio.ui.pathfinderLmax', 'number', 0) +
        renderParamInput(nodeId, p, 'pathfinder_dmax', 'biblio.ui.pathfinderDmax', 'number', 1) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.pathfinderHint') + '</div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.cluster') + '</div>';
    html += renderParamCheckbox(nodeId, p, 'cluster', 'biblio.ui.cluster', true) +
        renderParamInput(nodeId, p, 'cluster_count', 'biblio.ui.clusterCount', 'number', '') +
        renderParamSelect(nodeId, p, 'label_method', 'biblio.ui.labelMethod', 'llr', biblioLabelOptions(BIBLIO_LABEL_METHODS)) +
        renderParamSelect(nodeId, p, 'label_source', 'biblio.ui.labelSource', 'all', biblioLabelSourceOptions(BIBLIO_LABEL_SOURCES)) +
        renderParamInput(nodeId, p, 'top_terms', 'biblio.ui.topTerms', 'number', 5) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.labelSourceHint') + '</div>' +
        '<div class="settings-hint">' + I18n.t('biblio.ui.clusterHint') + '</div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.burst') + '</div>';
    html += renderParamCheckbox(nodeId, p, 'burst', 'biblio.ui.burst', true) +
        renderParamInput(nodeId, p, 'burst_gamma', 'biblio.ui.burstGamma', 'number', 1.0) +
        renderParamInput(nodeId, p, 'burst_min_duration', 'biblio.ui.burstMinDuration', 'number', 2) +
        renderParamInput(nodeId, p, 'burst_weight', 'biblio.ui.burstWeight', 'number', 2.0) +
        renderParamInput(nodeId, p, 'burst_top', 'biblio.ui.burstTop', 'number', 20) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.burstHint') + '</div>';
    if (isBiblioCoupling(entity)) {
        html += '<div class="settings-group" style="font-size:11px;color:#e67e22;">' + I18n.t('biblio.ui.burstCoupling') + '</div>';
    }

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.variation') + '</div>';
    html += renderParamCheckbox(nodeId, p, 'variation', 'biblio.ui.variation', false) +
        renderParamInput(nodeId, p, 'variation_min', 'biblio.ui.variationMin', 'number', 0.05) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.variationHint') + '</div>';
    if (isBiblioCoupling(entity)) {
        // The switch is refused by the server here, so the panel says so instead of offering a
        // box that only ever produces an error at run time.
        html += '<div class="settings-group" style="font-size:11px;color:#e67e22;">' + I18n.t('biblio.ui.variationCoupling') + '</div>';
    }

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.overlay') + '</div>';
    html += renderParamInput(nodeId, p, 'sentiment_column', 'biblio.ui.sentimentColumn', 'text', '') +
        renderParamInput(nodeId, p, 'topic_column', 'biblio.ui.topicColumn', 'text', '') +
        '<div class="settings-hint">' + I18n.t('biblio.ui.overlayHint') + '</div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.correction') + '</div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.aliases') + '</label>' +
        '<textarea class="settings-input" rows="4" placeholder="' + escapeHtml(I18n.t('biblio.ui.aliasesPlaceholder')) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'aliases\',this.value)">' + escapeHtml(p.aliases || '') + '</textarea></div>' +
        '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.exclusions') + '</label>' +
        '<textarea class="settings-input" rows="4" placeholder="' + escapeHtml(I18n.t('biblio.ui.exclusionsPlaceholder')) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'exclude_values\',this.value)">' + escapeHtml(p.exclude_values || '') + '</textarea>' +
        '<div class="settings-hint">' + I18n.t('biblio.ui.correctionHint') + '</div></div>';
    if (!isBiblioCoupling(entity)) {
        // A coupling network's clusters are the citing documents, which no one names by hand;
        // the box only appears where a label can actually be overridden.
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.clusterLabels') + '</label>' +
            '<textarea class="settings-input" rows="3" placeholder="' +
            escapeHtml(I18n.t('biblio.ui.clusterLabelsPlaceholder')) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'cluster_labels\',this.value)">' +
            escapeHtml(p.cluster_labels || '') + '</textarea>' +
            '<div class="settings-hint">' + I18n.t('biblio.ui.clusterLabelsHint') + '</div></div>';
    }

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.output') + '</div>';
    html += renderParamSelect(nodeId, p, 'output_shape', 'biblio.ui.outputShape', 'nodes', biblioOutputShapeOptions(BIBLIO_OUTPUT_SHAPES));
    var basemapId = escapeHtml(p.basemap_dataset_id || '');
    var basemapOptions = '<option value="' + basemapId + '" selected>' + escapeHtml(p.basemap_dataset_id || I18n.t('biblio.ui.noBasemap')) + '</option>';
    if (p.basemap_dataset_id && dataNodes._datasets && dataNodes._datasets[p.basemap_dataset_id]) {
        basemapOptions = '<option value="' + basemapId + '" selected>' + escapeHtml(dataNodes._dsLabel(dataNodes._datasets[p.basemap_dataset_id])) + '</option>';
    }
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.basemap') + '</label>' +
        '<select class="settings-select" id="biblio-basemap-' + nodeId + '" onchange="updateParam(\'' + nodeId + '\',\'basemap_dataset_id\',this.value)">' +
        basemapOptions + '</select>' +
        '<button class="menu-btn" onclick="dataNodes.loadBiblioBasemapOptions(\'' + nodeId + '\')">' + I18n.t('settings.capLoaded') + '</button>' +
        '<div class="settings-hint">' + I18n.t('biblio.ui.basemapHint') + '</div></div>';
    html += renderParamInput(nodeId, p, 'watch_project', 'biblio.ui.watchProject', 'text', '') +
        renderParamInput(nodeId, p, 'watch_baseline', 'biblio.ui.watchBaseline', 'text', '') +
        renderParamInput(nodeId, p, 'watch_label', 'biblio.ui.watchLabel', 'text', '') +
        '<div class="settings-hint">' + I18n.t('biblio.ui.watchHint') + '</div>';
    html += renderParamCheckbox(nodeId, p, 'export_files', 'biblio.ui.exportFiles', true) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.exportHint') + '</div>' +
        '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    return html;
}

