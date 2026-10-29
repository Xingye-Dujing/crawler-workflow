/* node-analysis.js — 分析节点的设置：ops 清单与 renderAnalysisSettings
 *
 * Split out of `panels/settings.js` on 2026-10-29 as a contiguous slice (its own banner section),
 * so every name here is still a page global and inline `onclick="…"` handlers keep calling it by
 * name. index.html loads it right after `panels/settings.js`; `tests/frontend/splits.json` declares
 * it a companion of that file, so a harness naming one receives both.
 */
/* ── Analysis node settings ── */
var ANALYSIS_OPS = ['drop_null', 'fill_null', 'drop_duplicates', 'dedupe_similar', 'filter_rows', 'select_columns', 'rename_columns', 'strip_whitespace', 'convert_type', 'sort_rows', 'sample_rows', 'groupby_agg', 'join_tables', 'column_calc', 'bin_column', 'extract_time', 'bin_time', 'suggest_stages', 'topic_model', 'topic_by_stage', 'topic_label', 'cluster_label', 'cluster_review', 'topic_map', 'topic_salience', 'topic_timeline', 'topic_flow', 'topic_coherence', 'cooccur', 'reply_graph', 'compare_platform', 'forecast', 'alert', 'sentiment_evolution'];
var FILTER_OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains', 'in', 'not_in', 'is_null', 'not_null'];
var CONVERT_TYPES = ['str', 'int', 'float', 'bool', 'datetime'];

function renderAnalysisSettings(nodeId, p) {
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.operation') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'operation\',this.value)">' +
        selectOptionTags(
            ANALYSIS_OPS.map(function (op) {
                return { value: op, label: I18n.t('op.' + op) };
            }),
            p.operation,
            'drop_null'
        ) +
        '</select></div>';

    var op = p.operation || 'drop_null';
    if (['drop_null', 'fill_null', 'drop_duplicates', 'select_columns', 'strip_whitespace'].indexOf(op) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.columns') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.columns || '') + '" placeholder="col1, col2 (empty = all)" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'columns\',this.value)"></div>';
    }
    if (op === 'drop_null') {
        /* 'any' drops a row with one empty cell, 'all' only when every selected
           cell is empty — the two produce very different tables, so the choice
           has to be on the panel and not buried in a default. */
        html += renderParamSelect(nodeId, p, 'how', 'settings.dropHow', 'any',
            [{ v: 'any', l: I18n.t('settings.dropHowAny') }, { v: 'all', l: I18n.t('settings.dropHowAll') }]);
    }
    if (op === 'drop_duplicates') {
        /* Exact text and normalised text are different questions about the same table: a
           comment farm's repost is a NEW string and the same comment. Naming both here is
           what keeps the node from answering the second while the user asked the first. */
        html += renderParamSelect(nodeId, p, 'mode', 'settings.dedupeMode', 'exact',
            [{ v: 'exact', l: I18n.t('settings.dedupeModeExact') },
             { v: 'normalized', l: I18n.t('settings.dedupeModeNormalized') }]);
    }
    if (op === 'dedupe_similar') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>' +
            renderParamInput(nodeId, p, 'max_distance', 'settings.dedupeDistance', 'number', 8) +
            '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.dedupeSimilarHint') + '</div></div>';
    }

    /* ── The event study: when, which subjects, and which way the crowd leaned ──
       These four are the paper-replication steps. They share one shape — name the
       column, name the new column — so they are rendered together rather than one
       block per operation with the same three inputs copied into each. */
    if (op === 'extract_time') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'time_new_col', 'settings.newColumn', 'text', '日期');
        html += renderParamSelect(nodeId, p, 'time_part', 'settings.timePart', 'date',
            [{ v: 'date', l: I18n.t('settings.timePartDate') },
             { v: 'hour', l: I18n.t('settings.timePartHour') },
             { v: 'weekday', l: I18n.t('settings.timePartWeekday') },
             { v: 'month', l: I18n.t('settings.timePartMonth') },
             { v: 'year', l: I18n.t('settings.timePartYear') }]);
    }
    if (op === 'bin_time') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'phase_new_col', 'settings.newColumn', 'text', '阶段');
        html += renderParamInput(nodeId, p, 'phase_edges', 'settings.phaseEdges', 'text', '');
        html += renderParamInput(nodeId, p, 'phase_labels', 'settings.phaseLabels', 'text', '');
        html += renderParamInput(nodeId, p, 'phase_order_col', 'settings.phaseOrderColumn', 'text', '阶段序号');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.phaseHint') + '</div></div>';
    }
    if (op === 'suggest_stages') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'stages_min_days', 'settings.stagesMinDays', 'number', 3);
        html += renderParamInput(nodeId, p, 'stages_max_windows', 'settings.stagesMaxWindows', 'number', 6);
        html += renderParamInput(nodeId, p, 'stages_peak_ratio', 'settings.stagesPeakRatio', 'number', 2);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.stagesHint') + '</div></div>';
    }
    if (op === 'topic_model') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'n_topics', 'settings.nTopics', 'number', 5);
        html += renderParamSelect(nodeId, p, 'topic_method', 'settings.topicMethod', 'auto',
            [{ v: 'auto', l: I18n.t('settings.topicMethodAuto') }, { v: 'embedding', l: I18n.t('settings.topicMethodEmbed') }, { v: 'lda', l: I18n.t('settings.topicMethodLda') }]);
        html += renderParamInput(nodeId, p, 'embedding_model', 'settings.embeddingModel', 'text', 'BAAI/bge-small-zh-v1.5');
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicTopn', 'number', 10);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicHint') + '</div></div>';
    }
    if (op === 'topic_by_stage') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'stage_col', 'settings.stageColumn', 'text', '阶段');
        html += renderParamInput(nodeId, p, 'stage_order_col', 'settings.stageOrderColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'stage_topic_counts', 'settings.stageTopicCounts', 'text', '5,6,4,4,4');
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicTopn', 'number', 10);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += renderParamInput(nodeId, p, 'topic_sample_n', 'settings.topicSampleN', 'number', 5);
        html += renderParamSelect(nodeId, p, 'topic_method', 'settings.topicMethod', 'auto',
            [{ v: 'auto', l: I18n.t('settings.topicMethodAuto') }, { v: 'embedding', l: I18n.t('settings.topicMethodEmbed') }, { v: 'lda', l: I18n.t('settings.topicMethodLda') }]);
        html += renderParamInput(nodeId, p, 'embedding_model', 'settings.embeddingModel', 'text', 'BAAI/bge-small-zh-v1.5');
        html += renderParamSelect(nodeId, p, 'word_source', 'settings.topicWordSource', 'tfidf',
            [{ v: 'tfidf', l: I18n.t('settings.topicWordSourceTfidf') },
             { v: 'lda', l: I18n.t('settings.topicWordSourceLda') }]);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicStageHint') + '</div></div>';
    }
    if (op === 'topic_label') {
        html += renderParamInput(nodeId, p, 'label_words_col', 'settings.labelWordsColumn', 'text', 'feature_words');
        html += renderParamInput(nodeId, p, 'label_samples_col', 'settings.labelSamplesColumn', 'text', 'sample_texts');
        html += renderParamInput(nodeId, p, 'label_summary_col', 'settings.labelSummaryColumn', 'text', '主题概括');
        html += renderParamSelect(nodeId, p, 'label_on_fail', 'settings.labelOnFail', 'abort',
            [{ v: 'abort', l: I18n.t('settings.labelOnFailAbort') },
             { v: 'blank', l: I18n.t('settings.labelOnFailBlank') },
             { v: 'fallback', l: I18n.t('settings.labelOnFailFallback') }]);
        html += renderParamInput(nodeId, p, 'label_max_topics', 'settings.labelMaxTopics', 'number', 30);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicLabelHint') + '</div></div>';
    }
    if (op === 'cluster_label') {
        html += renderParamInput(nodeId, p, 'cluster_group_col', 'settings.clusterGroupColumn', 'text', 'cluster');
        html += renderParamInput(nodeId, p, 'cluster_text_col', 'settings.clusterTextColumn', 'text', '正文');
        html += renderParamInput(nodeId, p, 'cluster_summary_col', 'settings.clusterSummaryColumn', 'text', '摘要');
        html += renderParamSelect(nodeId, p, 'cluster_on_fail', 'settings.clusterOnFail', 'abort',
            [{ v: 'abort', l: I18n.t('settings.labelOnFailAbort') },
             { v: 'blank', l: I18n.t('settings.labelOnFailBlank') },
             { v: 'fallback', l: I18n.t('settings.labelOnFailFallback') }]);
        html += renderParamInput(nodeId, p, 'cluster_max_groups', 'settings.clusterMaxGroups', 'number', 60);
        html += renderParamInput(nodeId, p, 'cluster_sample_n', 'settings.clusterSampleN', 'number', 8);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.clusterLabelHint') + '</div></div>';
    }
    if (op === 'cluster_review') {
        html += renderParamInput(nodeId, p, 'review_group_col', 'settings.reviewGroupColumn', 'text', '聚类');
        html += renderParamInput(nodeId, p, 'review_label_col', 'settings.reviewLabelColumn', 'text', '聚类标签');
        html += renderParamInput(nodeId, p, 'review_name_col', 'settings.reviewNameColumn', 'text', '节点');
        html += renderParamInput(nodeId, p, 'review_freq_col', 'settings.reviewFreqColumn', 'text', '频次');
        html += renderParamInput(nodeId, p, 'review_summary_col', 'settings.reviewSummaryColumn', 'text', '簇综述');
        html += renderParamSelect(nodeId, p, 'review_on_fail', 'settings.clusterOnFail', 'abort',
            [{ v: 'abort', l: I18n.t('settings.labelOnFailAbort') },
             { v: 'blank', l: I18n.t('settings.labelOnFailBlank') },
             { v: 'fallback', l: I18n.t('settings.labelOnFailFallback') }]);
        html += renderParamInput(nodeId, p, 'review_max_groups', 'settings.clusterMaxGroups', 'number', 60);
        html += renderParamInput(nodeId, p, 'review_members', 'settings.reviewMembers', 'number', 12);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.clusterReviewHint') + '</div></div>';
    }
    if (op === 'topic_map') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'n_topics', 'settings.nTopics', 'number', 5);
        html += renderParamSelect(nodeId, p, 'topic_method', 'settings.topicMethod', 'auto',
            [{ v: 'auto', l: I18n.t('settings.topicMethodAuto') }, { v: 'embedding', l: I18n.t('settings.topicMethodEmbed') }, { v: 'lda', l: I18n.t('settings.topicMethodLda') }]);
        html += renderParamInput(nodeId, p, 'embedding_model', 'settings.embeddingModel', 'text', 'BAAI/bge-small-zh-v1.5');
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicMapTopn', 'number', 6);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicMapHint') + '</div></div>';
    }
    if (op === 'topic_salience') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'n_topics', 'settings.nTopics', 'number', 5);
        html += renderParamSelect(nodeId, p, 'topic_method', 'settings.topicMethod', 'auto',
            [{ v: 'auto', l: I18n.t('settings.topicMethodAuto') }, { v: 'embedding', l: I18n.t('settings.topicMethodEmbed') }, { v: 'lda', l: I18n.t('settings.topicMethodLda') }]);
        html += renderParamInput(nodeId, p, 'embedding_model', 'settings.embeddingModel', 'text', 'BAAI/bge-small-zh-v1.5');
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicTermsTopn', 'number', 30);
        html += renderParamInput(nodeId, p, 'topic_lambda', 'settings.topicLambda', 'number', 1);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicSalienceHint') + '</div></div>';
    }
    if (op === 'topic_timeline') {
        // Every box names a column 分阶段 LDA writes, so the defaults are that step's own
        // output names: an untouched form is the pipeline hand-off, not a guess.
        html += renderParamInput(nodeId, p, 'timeline_stage_col', 'settings.timelineStageColumn', 'text', 'stage');
        html += renderParamInput(nodeId, p, 'timeline_topic_col', 'settings.timelineTopicColumn', 'text', 'topic');
        html += renderParamInput(nodeId, p, 'timeline_words_col', 'settings.timelineWordsColumn', 'text', 'feature_words');
        html += renderParamInput(nodeId, p, 'timeline_size_col', 'settings.timelineSizeColumn', 'text', 'doc_n');
        html += renderParamInput(nodeId, p, 'timeline_order_col', 'settings.timelineOrderColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'timeline_overlap', 'settings.timelineOverlap', 'number', 0.5);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.timelineHint') + '</div></div>';
    }
    if (op === 'topic_flow') {
        html += renderParamInput(nodeId, p, 'flow_stage_col', 'settings.flowStageColumn', 'text', 'stage');
        html += renderParamInput(nodeId, p, 'flow_topic_col', 'settings.flowTopicColumn', 'text', 'topic');
        html += renderParamInput(nodeId, p, 'flow_words_col', 'settings.flowWordsColumn', 'text', 'feature_words');
        html += renderParamInput(nodeId, p, 'flow_weights_col', 'settings.flowWeightsColumn', 'text', 'weights');
        html += renderParamInput(nodeId, p, 'flow_order_col', 'settings.flowOrderColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'flow_label_col', 'settings.flowLabelColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'flow_min_similarity', 'settings.flowMinSimilarity', 'number', 0.5);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.flowHint') + '</div></div>';
    }
    if (op === 'topic_coherence') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'coherence_min_topics', 'settings.coherenceMinTopics', 'number', 2);
        html += renderParamInput(nodeId, p, 'coherence_max_topics', 'settings.coherenceMaxTopics', 'number', 8);
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicTopn', 'number', 10);
        html += renderParamInput(nodeId, p, 'coherence_max_documents', 'settings.coherenceMaxDocuments', 'number', 2000);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.coherenceHint') + '</div></div>';
    }
    if (op === 'cooccur') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'cooccur_topn', 'settings.cooccurTopn', 'number', 30);
        html += renderParamInput(nodeId, p, 'cooccur_min_count', 'settings.cooccurMinCount', 'number', 2);
        html += renderParamInput(nodeId, p, 'cooccur_window', 'settings.cooccurWindow', 'number', 0);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.cooccurHint') + '</div></div>';
    }
    if (op === 'reply_graph') {
        html += renderParamInput(nodeId, p, 'reply_author_col', 'settings.replyAuthorColumn', 'text', '评论者');
        html += renderParamInput(nodeId, p, 'reply_floor_col', 'settings.replyFloorColumn', 'text', '楼层');
        html += renderParamInput(nodeId, p, 'reply_parent_col', 'settings.replyParentColumn', 'text', '父楼层');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.replyGraphHint') + '</div></div>';
    }
    if (op === 'compare_platform') {
        html += renderParamInput(nodeId, p, 'compare_platform_col', 'settings.comparePlatformColumn', 'text', 'platform');
        html += renderParamInput(nodeId, p, 'compare_value_col', 'settings.compareValueColumn', 'text', '');
        html += renderParamSelect(nodeId, p, 'compare_agg', 'settings.compareAgg', 'mean',
            [{ v: 'mean', l: I18n.t('settings.compareAggMean') }, { v: 'sum', l: I18n.t('settings.compareAggSum') }]);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.compareHint') + '</div></div>';
    }
    if (op === 'forecast') {
        html += renderParamInput(nodeId, p, 'forecast_period_col', 'settings.forecastPeriodColumn', 'text', 'period');
        html += renderParamInput(nodeId, p, 'forecast_value_col', 'settings.forecastValueColumn', 'text', 'sentiment_index');
        html += renderParamSelect(nodeId, p, 'forecast_method', 'settings.forecastMethod', 'moving_average',
            [{ v: 'moving_average', l: I18n.t('settings.forecastMethodMa') },
             { v: 'holt', l: I18n.t('settings.forecastMethodHolt') },
             { v: 'seasonal_naive', l: I18n.t('settings.forecastMethodSeasonalNaive') },
             { v: 'holt_winters', l: I18n.t('settings.forecastMethodHoltWinters') }]);
        html += renderParamInput(nodeId, p, 'forecast_horizon', 'settings.forecastHorizon', 'number', 3);
        html += renderParamInput(nodeId, p, 'forecast_window', 'settings.forecastWindow', 'number', 3);
        html += renderParamInput(nodeId, p, 'forecast_season', 'settings.forecastSeason', 'number', 7);
        html += renderParamInput(nodeId, p, 'forecast_alpha', 'settings.forecastAlpha', 'number', 0.5);
        html += renderParamInput(nodeId, p, 'forecast_beta', 'settings.forecastBeta', 'number', 0.3);
        html += renderParamInput(nodeId, p, 'forecast_gamma', 'settings.forecastGamma', 'number', 0.35);
        html += renderParamInput(nodeId, p, 'forecast_min_periods', 'settings.forecastMinPeriods', 'number', 4);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.forecastHint') + '</div></div>';
    }
    if (op === 'alert') {
        html += renderParamInput(nodeId, p, 'alert_period_col', 'settings.alertPeriodColumn', 'text', 'period');
        html += renderParamInput(nodeId, p, 'alert_index_col', 'settings.alertIndexColumn', 'text', 'sentiment_index');
        // Blank means "that half of the rule is not wanted", exactly like the 强度 column box on
        // 情感演化曲线, so these two start empty rather than pre-filled.
        html += renderParamInput(nodeId, p, 'alert_intensity_col', 'settings.alertIntensityColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'alert_volume_col', 'settings.alertVolumeColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'alert_streak', 'settings.alertStreak', 'number', 2);
        html += renderParamInput(nodeId, p, 'alert_swing', 'settings.alertSwing', 'number', 0.2);
        html += renderParamInput(nodeId, p, 'alert_heating', 'settings.alertHeating', 'number', 0.15);
        html += renderParamInput(nodeId, p, 'alert_volume_floor', 'settings.alertVolumeFloor', 'number', 0.6);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.alertHint') + '</div></div>';
    }
    if (op === 'sentiment_evolution') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'label_col', 'settings.labelColumn', 'text', 'sentiment');
        html += renderParamInput(nodeId, p, 'index_new_col', 'settings.newColumn', 'text', 'sentiment_index');
        html += renderParamInput(nodeId, p, 'label_positive', 'settings.labelPositive', 'text', 'positive');
        html += renderParamInput(nodeId, p, 'label_neutral', 'settings.labelNeutral', 'text', 'neutral');
        html += renderParamInput(nodeId, p, 'label_negative', 'settings.labelNegative', 'text', 'negative');
        html += renderParamInput(nodeId, p, 'score_col', 'settings.scoreColumn', 'text', 'score');
        html += renderParamInput(nodeId, p, 'evolution_order_col', 'settings.evolutionOrderColumn', 'text', '');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.evolutionHint') + '</div></div>';
    }
    if (op === 'fill_null') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.value') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.value || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value\',this.value)"></div>';
        /* A method and a literal value are different operations; leaving method
           empty means "fill with the value above". */
        html += renderParamSelect(nodeId, p, 'method', 'settings.fillMethod', '',
            [{ v: '', l: I18n.t('settings.fillMethodValue') }, { v: 'ffill', l: 'ffill' }, { v: 'bfill', l: 'bfill' }]);
    }
    if (op === 'filter_rows') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.filterOp') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'op\',this.value)">' +
            selectOptionTags(
                FILTER_OPS.map(function (o) {
                    return { value: o, label: o };
                }),
                p.op,
                'eq'
            ) +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.value') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.value || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value\',this.value)"></div>';
    }
    if (op === 'rename_columns') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.renameFrom') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.rename_from || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'rename_from\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.renameTo') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.rename_to || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'rename_to\',this.value)"></div>';
    }
    if (op === 'convert_type') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.dtype') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'dtype\',this.value)">' +
            selectOptionTags(
                CONVERT_TYPES.map(function (t) {
                    return { value: t, label: t };
                }),
                p.dtype,
                'str'
            ) +
            '</select></div>';
    }
    if (op === 'sort_rows') {
        html += renderParamInput(nodeId, p, 'column', 'settings.column', 'text', '');
        html += renderParamCheckbox(nodeId, p, 'ascending', 'settings.ascending', true);
    }
    if (op === 'sample_rows') {
        html += renderParamInput(nodeId, p, 'n', 'settings.n', 'number', '');
        html += renderParamInput(nodeId, p, 'frac', 'settings.frac', 'number', '');
        html += renderParamInput(nodeId, p, 'seed', 'settings.seed', 'number', '');
    }
    if (op === 'groupby_agg') {
        html += renderParamInput(nodeId, p, 'group_col', 'settings.groupCol', 'text', '');
        html += renderParamInput(nodeId, p, 'agg_col', 'settings.aggCol', 'text', '');
        html += renderParamSelect(nodeId, p, 'agg_func', 'settings.aggFunc', 'sum',
            [{ v: 'sum', l: 'Sum' }, { v: 'mean', l: 'Mean' }, { v: 'count', l: 'Count' }, { v: 'max', l: 'Max' }, { v: 'min', l: 'Min' }]);
        html += renderParamInput(nodeId, p, 'group_order_col', 'settings.groupOrderColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'agg_metrics', 'settings.aggMetrics', 'text', '');
    }
    if (op === 'join_tables') {
        /* The right table is the node's second incoming connection — the old
           "dataset id" box asked for an id the user had no way to obtain. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.joinHint') + '</div>';
        html += renderParamSelect(nodeId, p, 'join_how', 'settings.joinHow', 'left',
            [{ v: 'left', l: 'Left' }, { v: 'right', l: 'Right' }, { v: 'inner', l: 'Inner' }, { v: 'outer', l: 'Outer' }]);
        html += renderParamInput(nodeId, p, 'left_on', 'settings.leftOn', 'text', '');
        html += renderParamInput(nodeId, p, 'right_on', 'settings.rightOn', 'text', '');
    }
    if (op === 'column_calc') {
        html += renderParamInput(nodeId, p, 'new_col', 'settings.newCol', 'text', '');
        html += renderParamInput(nodeId, p, 'expr', 'settings.expr', 'text', '');
    }
    if (op === 'bin_column') {
        html += renderParamInput(nodeId, p, 'column', 'settings.column', 'text', '');
        html += renderParamInput(nodeId, p, 'bin_new_col', 'settings.binNewCol', 'text', '');
        /* One integer = that many equal-width buckets; a comma-separated list =
           those exact edges. The backend tells the two apart by shape. */
        html += renderParamInput(nodeId, p, 'bins', 'settings.binEdges', 'text', '4 或 0, 60, 80, 100');
        html += renderParamInput(nodeId, p, 'bin_labels', 'settings.binLabels', 'text', 'low, mid, high');
    }
    html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    return html;
}

