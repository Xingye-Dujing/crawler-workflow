"""Translate the settings panel's flat fields into the kwargs each analysis step expects.

The panel stores everything as strings — a comma-separated column list, a text number, a
checkbox spelled ``'true'`` — while ``DataAnalysisService`` takes typed kwargs. This module is
the one translation layer; ``nodes/schema.py`` reads the same rules to say which columns
a step consumes, so a new field is declared once instead of in two shapes.
"""

from api.http import _float_with_default, _optional_float, _optional_int
from core.refs import as_bool
from core.refs import split_columns as _split_columns


def apply_topic_method(result: dict, params: dict) -> dict:
    """Forward the topic ``method`` (and its encoder) for every embedding-capable topic step —
    ``topic_model`` and the three view steps (``topic_map``/``topic_salience``/``topic_by_stage``)
    share this so the default and the refuse-by-name contract cannot drift apart.

    ``auto`` is the product default (STEP_PARAMS agrees): an untouched form becomes ``auto`` and the
    op resolves it to embedding-or-LDA by availability, PRINTING which one ran. An explicit ``lda``
    stays LDA and an explicit ``embedding`` stays embedding (and refuses by name downstream when the
    encoder is absent — a chosen model is never substituted). Saved canvases that used to MEAN
    LDA-by-absence carry an explicit ``topic_method='lda'``, so nothing here re-runs them.
    ``embedding_model`` is forwarded whenever one was typed, independent of the method, so the panel
    field is honest either way (the LDA branch simply ignores it).
    """
    method = str(params.get('topic_method') or 'auto').strip()
    result['method'] = method
    embedding_model = str(params.get('embedding_model') or '').strip()
    if embedding_model:
        result['embedding_model'] = embedding_model
    return result


# ─── Column contract (what each step writes, what it reads) ───
#: Steps that emit a NEW table with a fixed column set (the chart contracts live here:
#: topic_map / topic_salience are what the 主题距离图 / 显著词图 read).
STEP_REPLACE: dict[str, tuple[str, ...]] = {
    'topic_model': ('topic', 'rank', 'keyword', 'weight'),
    'topic_by_stage': (
        'stage',
        'stage_order',
        'topic',
        'feature_words',
        'weights',
        'doc_n',
        'perplexity',
        'sample_texts',
    ),
    'topic_map': ('topic', 'pc1', 'pc2', 'prevalence_pct', 'doc_n', 'feature_words'),
    'topic_salience': ('topic', 'rank', 'term', 'overall_freq', 'within_freq', 'relevance'),
    'suggest_stages': ('序号', '起点', '终点', '天数', '行数', '峰值日', '峰值计数', '依据'),
    'forecast': ('period', 'actual', 'predicted', 'lower', 'upper', 'horizon'),
    'alert': ('period', 'signal', 'value', 'threshold', 'reason'),
    'cooccur': ('source', 'target', 'value'),
    'reply_graph': ('src_author', 'dst_author', 'weight'),
    'topic_timeline': (
        'topic',
        'topic_words',
        'first_stage',
        'peak_stage',
        'last_stage',
        'stages_present',
        'stage_path',
        'size_total',
        'peak_size',
        'is_secondary',
    ),
    'topic_flow': (
        'source',
        'target',
        'source_topic',
        'target_topic',
        'similarity',
        'divergence',
        'from_stage',
        'to_stage',
        'source_words',
        'target_words',
    ),
    # ``compare_platform`` and ``sentiment_evolution`` also replace the table, but name a
    # column after what the user typed into a box — they are modelled in
    # :func:`replaced_columns`, never as a fixed tuple here.
}

#: Steps whose whole output is a fresh table whose names come from the node's own parameters.
STEP_DYNAMIC_REPLACE = ('compare_platform', 'sentiment_evolution', 'cluster_label')


def replaced_columns(op: str, step: dict) -> list[str] | None:
    """The columns a dynamic replace-step will write, taken from its resolved kwargs.

    Both of these name a column after a box the user filled, so the fixed tuple they used
    to carry was a lie in both directions: it promised a ``platform`` column a renamed 平台
    never produced (a false missing-column flag downstream) and hid the real aggregate
    column, while ``sentiment_evolution`` claimed ``intensity``/``score_n`` even when no
    score column was given — a chart would read those and only find out at run time.
    """
    if op == 'cluster_label':
        # The summariser REDUCES the table: one row per cluster, three columns. Declaring it as
        # "upstream columns + 摘要" promised every input column downstream, so a chart fed by it
        # was told 节点/频次 would be there and found only cluster/n_docs/摘要 at run time.
        group_col = str(step.get('group_col') or 'cluster').strip()
        summary_col = str(step.get('summary_col') or '摘要').strip()
        if not group_col or not summary_col:
            return None
        return [group_col, 'n_docs', summary_col]
    if op == 'compare_platform':
        platform_col = str(step.get('platform_col') or 'platform').strip()
        cols = [platform_col, 'n']
        value_col = str(step.get('value_col') or '').strip()
        if value_col:
            agg = str(step.get('agg') or 'mean').strip()
            cols.append(f'{value_col}_{agg}')
        return cols
    if op == 'sentiment_evolution':
        # The step ALWAYS renames its period column to 'period' (data_analysis.py:3178) regardless of
        # the input name, so naming the OUTPUT after the box the user filled was a lie: a chart that
        # reads 'period' (the produced name, and the downstream default) was flagged as a provable
        # miss on a canvas that runs. The lineage must equal what the producer emits.
        index_col = str(step.get('new_col') or 'sentiment_index').strip()
        cols = ['period', index_col]
        cols += ['positive_n', 'neutral_n', 'negative_n', 'total', 'other_n']
        cols += ['positive_pct', 'neutral_pct', 'negative_pct', 'volume_pct']
        if str(step.get('score_col') or '').strip():
            cols += ['score_n', 'intensity']
        return cols
    return None


#: Steps that keep the upstream columns and add exactly one named column
#: (value = the executor's own param holding that name, plus its default). These are the
#: CANONICAL names — a panel's box (``phase_new_col``, ``label_summary_col``) is translated
#: to them by the lineage model through this module's own normalizer, so one rule lives in
#: one place and a renamed box can no longer hide the column it writes.
STEP_ADD_ONE: dict[str, tuple[str, str]] = {
    'bin_column': ('new_col', ''),  # blank answers f"{column}_bin", the executor's own rule
    'extract_time': ('new_col', '日期'),
    'bin_time': ('new_col', '阶段'),
    'column_calc': ('new_col', ''),
    'topic_label': ('summary_col', '主题概括'),
}

#: Steps that may ALSO add a further column, only when its box is filled.
#: ``bin_time`` is the case: 阶段序号列 is what lets 各阶段 tables and charts keep the
#: lifecycle order across the node boundary that erases the categorical, so a canvas that
#: names one has to show it in the lineage — declared otherwise the panel hid the very
#: column its own downstream steps read, and an unselected box still stayed honest.
STEP_ADD_MAYBE: dict[str, tuple[tuple[str, str], ...]] = {
    'bin_time': (('order_new_col', ''),),
}

#: Steps that pass the upstream columns through unchanged.
STEP_PASSTHROUGH = {
    'drop_null',
    'fill_null',
    'drop_duplicates',
    'dedupe_similar',
    'strip_whitespace',
    'filter_rows',
    'sort_rows',
    'sample_rows',
    'convert_type',
}

#: Steps whose output the server cannot enumerate without the data (unknown).
#: ``cluster_review`` is here on purpose: its 年份跨度 cell only exists when the table carries
#: years, so a fixed tuple would promise a column some runs never write.
STEP_UNKNOWN = {'groupby_agg', 'join_tables', 'rename_columns', 'topic_coherence', 'cluster_review'}


def normalize_analysis_params(op: str, params: dict) -> dict:
    """The Settings panel stores everything as flat strings (e.g. a
    comma-separated 'columns' field). Translate that into the exact kwargs
    each DataAnalysisService method expects."""
    if op in ('drop_null', 'strip_whitespace', 'select_columns'):
        result = {'columns': _split_columns(params.get('columns'))}
        if op == 'drop_null':
            # ``how`` decides whether one empty cell drops a row or all of them
            # do; the panel had no field for it and the normalizer dropped it, so
            # every "any column is null" choice silently became "all columns".
            result['how'] = params.get('how') or 'any'
        return result
    if op == 'fill_null':
        result = {'columns': _split_columns(params.get('columns')), 'value': params.get('value')}
        method = str(params.get('method') or '').strip()
        if method:
            # Forward/backward fill and a literal value are different operations;
            # an empty method means "use value", which the service already does.
            result['method'] = method
        return result
    if op == 'drop_duplicates':
        # ``mode`` is passed explicitly rather than left to the method's signature: the
        # stored value is what the user chose, and a bad spelling has to reach
        # ``validate_step`` and be refused by name instead of quietly becoming 'exact'.
        return {
            'columns': _split_columns(params.get('columns')) or None,
            'mode': params.get('mode') or 'exact',
        }
    if op == 'dedupe_similar':
        result = {'column': params.get('column', '')}
        distance = _optional_int(params.get('max_distance'))
        if distance is not None:
            result['max_distance'] = distance
        return result
    if op == 'filter_rows':
        return {'column': params.get('column', ''), 'op': params.get('op', 'eq'), 'value': params.get('value')}
    if op == 'rename_columns':
        mapping = {}
        if params.get('rename_from'):
            mapping[params['rename_from']] = params.get('rename_to', '')
        return {'mapping': mapping}
    if op == 'convert_type':
        return {'column': params.get('column', ''), 'dtype': params.get('dtype', 'str')}
    if op == 'sort_rows':
        # Both spellings of a switch are in the saved files: the panel used to store
        # the text 'true'/'false' and a hand-written or exported workflow stores the
        # boolean. Comparing against one of them inverted 升序 into 降序 for the other.
        return {'column': params.get('column', ''), 'ascending': as_bool(params.get('ascending'), True)}
    if op == 'sample_rows':
        result = {'n': _optional_int(params.get('n')), 'frac': _optional_float(params.get('frac'))}
        seed = _optional_int(params.get('seed'))
        if seed is not None:
            result['seed'] = seed
        return result
    if op == 'groupby_agg':
        result = {
            'group_col': params.get('group_col', ''),
            'agg_col': params.get('agg_col', ''),
            'agg_func': params.get('agg_func', 'sum'),
        }
        # Read like ``score_col``: a blank box means "sort the groups by their own name", the
        # behaviour every saved pipeline already relies on, so the key is not sent.
        order_column = str(params.get('group_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        # Each "column:func" in agg_metrics adds one more aggregate beside the primary one; the
        # primary output column keeps agg_col's own name so existing charts are unaffected.
        pairs = []
        for chunk in str(params.get('agg_metrics') or '').split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            column, _, func = chunk.partition(':')
            column = column.strip()
            if column:
                pairs.append((column, func.strip() or 'sum'))
        if pairs:
            result['agg_metrics'] = pairs
        return result
    if op == 'join_tables':
        return {
            'how': params.get('join_how', 'left'),
            'left_on': params.get('left_on', ''),
            'right_on': params.get('right_on', ''),
        }
    if op == 'column_calc':
        return {
            'new_col': params.get('new_col', ''),
            'expr': params.get('expr', ''),
        }
    if op == 'bin_column':
        result = {
            'column': params.get('column', ''),
            'new_col': params.get('bin_new_col', ''),
        }
        # ``bins`` is overloaded the way pandas overloads it: a single integer
        # means "this many equal-width buckets" and a comma-separated list means
        # "these exact edges". Both are useful and only one parser can tell them
        # apart, so the distinction lives here rather than in the panel.
        edges = _split_columns(params.get('bins'))
        if len(edges) > 1:
            numbers = [_optional_float(edge) for edge in edges]
            result['bins'] = [number for number in numbers if number is not None]
        else:
            count = _optional_int(params.get('bins'))
            if count:
                result['bins'] = count
        labels = _split_columns(params.get('bin_labels'))
        if labels:
            result['labels'] = labels
        return result
    # ── the event-study steps ──
    if op == 'extract_time':
        return {
            'column': params.get('column', ''),
            'new_col': params.get('time_new_col') or '日期',
            'part': params.get('time_part') or 'date',
        }
    if op == 'bin_time':
        # The boundaries and the names are two parallel lists, so both are parsed here and
        # their lengths are checked by the step itself — that check is a refusal with a
        # reason, which is where a mismatched pair belongs.
        result = {
            'column': params.get('column', ''),
            'new_col': params.get('phase_new_col') or '阶段',
            'edges': _split_columns(params.get('phase_edges')),
            'labels': _split_columns(params.get('phase_labels')),
        }
        # Like ``score_col``: a blank box means "no order column", which is the step's own
        # default. The number is what lets 各阶段 tables and charts keep the lifecycle order
        # across the node boundary that erases the categorical.
        order_column = str(params.get('phase_order_col') or '').strip()
        if order_column:
            result['order_new_col'] = order_column
        return result
    if op == 'suggest_stages':
        # Every number here has a declared default in the step, so a blank or a junk box is
        # left to that default instead of reaching the curve as 0 or as a float('inf').
        result = {'column': params.get('column', '')}
        min_days = _optional_int(params.get('stages_min_days'))
        if min_days:
            result['min_days'] = min_days
        max_windows = _optional_int(params.get('stages_max_windows'))
        if max_windows:
            result['max_windows'] = max_windows
        ratio = _optional_float(params.get('stages_peak_ratio'))
        if ratio is not None:
            result['peak_ratio'] = ratio
        return result
    if op == 'topic_by_stage':
        result = {
            'column': params.get('column', ''),
            # The panel leaves this blank to mean the column 按时间划分阶段 writes, which is
            # also the step's own default; the gate must not refuse a box nobody typed in.
            'stage_col': str(params.get('stage_col') or '阶段').strip(),
            'topics': _split_columns(params.get('stage_topic_counts')),
            'topn': _optional_int(params.get('topic_topn')) or 10,
            'word_source': params.get('word_source') or 'tfidf',
            'sample_n': _optional_int(params.get('topic_sample_n')) or 5,
        }
        # Omitted when blank, like ``label_col``: "sort the phases by this time column" is a
        # choice the user makes, and an empty string is not a column to sort by.
        order_column = str(params.get('stage_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return apply_topic_method(result, params)
    if op == 'topic_map':
        result = {
            'column': params.get('column', ''),
            'n_topics': _optional_int(params.get('n_topics')) or 5,
            'topn': _optional_int(params.get('topic_topn')) or 6,
        }
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return apply_topic_method(result, params)
    if op == 'topic_salience':
        result = {
            'column': params.get('column', ''),
            'n_topics': _optional_int(params.get('n_topics')) or 5,
            'topn': _optional_int(params.get('topic_topn')) or 30,
        }
        # λ is read as a float and only forwarded when a number was written: 0 is a real answer
        # here (rank by over-representation only), so the ``or`` idiom used for counts would
        # turn the most interesting setting into the default.
        lam = _optional_float(params.get('topic_lambda'))
        if lam is not None:
            result['relevance'] = lam
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return apply_topic_method(result, params)
    if op == 'topic_model':
        result = {
            'column': params.get('column', ''),
            'n_topics': _optional_int(params.get('n_topics')) or 5,
            'topn': _optional_int(params.get('topic_topn')) or 10,
        }
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return apply_topic_method(result, params)
    if op == 'topic_timeline':
        # The four column names default to what 分阶段 LDA writes, so an untouched form is the
        # pipeline's own hand-off. The step still refuses when this table does not hold them.
        result = {
            'stage_col': str(params.get('timeline_stage_col') or 'stage').strip(),
            'words_col': str(params.get('timeline_words_col') or 'feature_words').strip(),
            'size_col': str(params.get('timeline_size_col') or 'doc_n').strip(),
            'topic_col': str(params.get('timeline_topic_col') or 'topic').strip(),
        }
        # Blank means "the phases are still ordered as the categorical left them", which is a
        # different answer from "sort them by this column", so it is omitted rather than sent.
        order_column = str(params.get('timeline_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        # 0 is refused by the step (no overlap at all would put every row in its own family),
        # so it is forwarded as the wrong answer it is instead of swallowed by ``or``.
        overlap = _optional_float(params.get('timeline_overlap'))
        if overlap is not None:
            result['min_overlap'] = overlap
        return result
    if op == 'topic_flow':
        result = {
            'stage_col': str(params.get('flow_stage_col') or 'stage').strip(),
            'topic_col': str(params.get('flow_topic_col') or 'topic').strip(),
            'words_col': str(params.get('flow_words_col') or 'feature_words').strip(),
            'weights_col': str(params.get('flow_weights_col') or 'weights').strip(),
            # A similarity threshold, not a count: 0 means "draw every edge", which the step either
            # honours or refuses by name — so forward a typed 0 like ``timeline_overlap``/λ, never
            # swallow it into the default the way a count would.
            'min_similarity': _float_with_default(params.get('flow_min_similarity'), 0.5),
        }
        order_column = str(params.get('flow_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        # Read like ``score_col``: blank means the sankey keeps drawing bare row labels, and a
        # named column (表 1's 主题概括) is what makes the figure readable.
        label_column = str(params.get('flow_label_col') or '').strip()
        if label_column:
            result['label_col'] = label_column
        return result
    if op == 'topic_coherence':
        result = {
            'column': params.get('column', ''),
            'topn': _optional_int(params.get('topic_topn')) or 10,
        }
        # The sweep's two ends are forwarded whenever a number was written, including a 0: an
        # impossible end is refused by the step with the range in the message, which is truer
        # than quietly raising it to the default the user just overrode.
        for key, source in (
            ('min_topics', 'coherence_min_topics'),
            ('max_topics', 'coherence_max_topics'),
            ('max_documents', 'coherence_max_documents'),
        ):
            number = _optional_int(params.get(source))
            if number is not None:
                result[key] = number
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return result
    if op == 'cooccur':
        result = {
            'column': params.get('column', ''),
            'topn': _optional_int(params.get('cooccur_topn')) or 30,
        }
        floor = _optional_int(params.get('cooccur_min_count'))
        if floor is not None:
            result['min_count'] = floor
        # A window of 0 is the whole document, which is the answer the panel's empty box means —
        # so it has to reach the step as 0, not be read as "not configured".
        window = _optional_int(params.get('cooccur_window'))
        if window is not None:
            result['window'] = window
        return result
    if op == 'forecast':
        result = {
            # The panel leaves the period box blank to mean "the column 情感演化曲线 writes",
            # which is also the step's own default.
            'column': str(params.get('forecast_period_col') or 'period').strip(),
            'value_col': str(params.get('forecast_value_col') or 'sentiment_index').strip(),
            'method': params.get('forecast_method') or 'moving_average',
            'horizon': _optional_int(params.get('forecast_horizon')) or 3,
            'window': _optional_int(params.get('forecast_window')) or 3,
            'min_periods': _optional_int(params.get('forecast_min_periods')) or 4,
        }
        # The smoothing factors are forwarded whenever a number was written (alpha/beta for
        # Holt and Holt-Winters, gamma for Holt-Winters' seasonal): 0 is refused by the step as
        # the degenerate setting it is, and swallowing it into the default would answer a
        # question the user did not ask. `season` is the cycle length the seasonal methods need.
        for key, source in (('alpha', 'forecast_alpha'), ('beta', 'forecast_beta'), ('gamma', 'forecast_gamma')):
            number = _optional_float(params.get(source))
            if number is not None:
                result[key] = number
        season = _optional_int(params.get('forecast_season'))
        if season is not None:
            result['season'] = season
        return result
    if op == 'alert':
        result = {
            'column': str(params.get('alert_period_col') or 'period').strip(),
            'index_col': str(params.get('alert_index_col') or 'sentiment_index').strip(),
            'streak': _optional_int(params.get('alert_streak')) or 2,
            # streak is a count (0 consecutive steps is "not configured", so default 2). These three
            # are thresholds: a typed 0 is a real rule ("flag any movement / any heating"), forwarded
            # to the step which honours or refuses it — never swallowed into the default like a count.
            'swing': _float_with_default(params.get('alert_swing'), 0.2),
            'heating': _float_with_default(params.get('alert_heating'), 0.15),
            'volume_floor': _float_with_default(params.get('alert_volume_floor'), 0.6),
        }
        # The two optional signals are read exactly like ``score_col`` on 情感演化曲线: a blank
        # box means that half of the rule is not wanted, so the key is not sent and the step's own
        # '' answers. A name that is typed but missing IS refused, by the step.
        for key, source in (('intensity_col', 'alert_intensity_col'), ('volume_col', 'alert_volume_col')):
            value = str(params.get(source) or '').strip()
            if value:
                result[key] = value
        return result
    if op == 'topic_label':
        # Every field falls back to the column 分阶段 LDA writes, so an untouched form is the
        # pipeline's own hand-off rather than a missing parameter; the step still refuses when
        # the table does not actually hold that column.
        return {
            'words_col': str(params.get('label_words_col') or 'feature_words').strip(),
            'summary_col': str(params.get('label_summary_col') or '主题概括').strip(),
            'samples_col': str(params.get('label_samples_col') or 'sample_texts').strip(),
            'on_fail': params.get('label_on_fail') or 'abort',
            'max_topics': _optional_int(params.get('label_max_topics')) or 30,
        }
    if op == 'cluster_label':
        # Same shape as ``topic_label``: untouched fields default to the columns the cluster op
        # writes and the corpus's text, and the two numbers fall back to their declared defaults
        # (an empty or junk box is "use the default", never a crash and never a paid call storm).
        return {
            'group_col': str(params.get('cluster_group_col') or 'cluster').strip(),
            'text_col': str(params.get('cluster_text_col') or '正文').strip(),
            'summary_col': str(params.get('cluster_summary_col') or '摘要').strip(),
            'on_fail': params.get('cluster_on_fail') or 'abort',
            'max_groups': _optional_int(params.get('cluster_max_groups')) or 60,
            'sample_n': _optional_int(params.get('cluster_sample_n')) or 8,
        }
    if op == 'cluster_review':
        # The bibliometric sibling of ``cluster_label``: the columns default to what a ``biblio``
        # node writes (聚类 / 聚类标签 / 节点 / 频次 / 首年 / 末年), so an untouched form reviews
        # the knowledge-map clusters rather than guessing at whichever columns came first.
        return {
            'group_col': str(params.get('review_group_col') or '聚类').strip(),
            'label_col': str(params.get('review_label_col') or '聚类标签').strip(),
            'name_col': str(params.get('review_name_col') or '节点').strip(),
            'freq_col': str(params.get('review_freq_col') or '频次').strip(),
            'first_col': str(params.get('review_first_col') or '首年').strip(),
            'last_col': str(params.get('review_last_col') or '末年').strip(),
            'summary_col': str(params.get('review_summary_col') or '簇综述').strip(),
            'members': _optional_int(params.get('review_members')) or 12,
            'on_fail': params.get('review_on_fail') or 'abort',
            'max_groups': _optional_int(params.get('review_max_groups')) or 60,
        }
    if op == 'reply_graph':
        # Three column names, each defaulting to what a comment crawl writes, so an untouched
        # form reads the crawl's own reply relation. They go through `or` (blank = the default),
        # which is why the panel/normalizer contract lists them as re-shaped, not pass-through.
        return {
            'author_col': str(params.get('reply_author_col') or '评论者').strip(),
            'floor_col': str(params.get('reply_floor_col') or '楼层').strip(),
            'parent_floor_col': str(params.get('reply_parent_col') or '父楼层').strip(),
        }
    if op == 'compare_platform':
        # Platform + aggregate default to the merge-stamped column and the mean; the value column
        # is deliberately blank-by-default ("counts only"), so it is forwarded as written and an
        # empty box means "no value column", which the step handles.
        return {
            'platform_col': str(params.get('compare_platform_col') or 'platform').strip(),
            'value_col': str(params.get('compare_value_col') or '').strip(),
            'agg': str(params.get('compare_agg') or 'mean').strip(),
        }
    if op == 'sentiment_evolution':
        result = {'column': params.get('column', '')}
        label_col = str(params.get('label_col') or '').strip()
        if label_col:
            result['label_col'] = label_col
        # The three label spellings are only passed when the user actually typed one: the
        # step's own defaults are the polarity node's verbs, and an empty string is not a
        # spelling to filter by.
        for key, source in (
            ('positive', 'label_positive'),
            ('neutral', 'label_neutral'),
            ('negative', 'label_negative'),
        ):
            value = str(params.get(source) or '').strip()
            if value:
                result[key] = value
        # Same rule as ``label_col``: a blank 强度 column means "the curve has no intensity
        # line", which is the step's own default. Sending ``score_col=''`` would be the same
        # answer, and sending the literal text of a cleared box would refuse the node for a
        # feature the user never asked for.
        score_column = str(params.get('score_col') or '').strip()
        if score_column:
            result['score_col'] = score_column
        # Read like ``score_col``: blank means "sort the periods by their own name", which is
        # right for days and wrong for Chinese phase labels once the categorical is gone —
        # the number 划分阶段's 阶段序号 writes is what restores the lifecycle order.
        order_column = str(params.get('evolution_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        if str(params.get('index_new_col') or '').strip():
            result['new_col'] = str(params['index_new_col']).strip()
        return result
    return {}
