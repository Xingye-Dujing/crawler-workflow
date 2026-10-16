"""Static output-column model for lineage — what each node emits, WITHOUT a run.

Only producers whose full output set is fixed and knowable are modelled. Anything whose
shape depends on data the server has not seen — a crawl (each platform builds its own
``_row``), a comment parse, a resume replay, an author-derived ``bot`` table, a
switch-dependent ``keyword``/``ner``/``cluster``/bert output, a ``groupby_agg``/``join``
whose extra columns are named after their inputs — is UNKNOWN (``None``). A node
downstream of an unknown is unknown too, and an unknown never produces a
missing-column flag: the whole point is to never tell the user a column is absent when
we cannot actually see the table (AGENTS: refuse by name, never guess a shape).

``referenced_columns`` answers the other half: which columns a node will READ from its
input, taken straight from the params the user typed (a chart's ``x_field``, an analysis
step's ``column``). The frontend compares those against the upstream node's emitted
columns and flags a provable miss — the schema truth lives here, the wording lives there.
"""

from __future__ import annotations

from services.data_analysis import STEP_PARAMS

# process ops that ADD these columns and pass the rest through (verified against each
# analyzer's write site; see the matching unit test).
PROCESS_ADD_COLUMNS: dict[str, tuple[str, ...]] = {
    'clean': ('action', 'cleaned_text'),
    'emotion': ('emotion', 'confidence'),
    'tendency': ('tendency', 'tendency_confidence'),
    'sentiment': ('sentiment', 'score'),
    'aggression': ('aggression', 'aggression_score', 'aggression_hits'),
    'anomaly': ('anomaly_score', 'is_anomaly'),
}

# process ops that REPLACE the whole table with a fixed set (the analyzer returns a fresh
# frame; downstream can only read these).
PROCESS_REPLACE_COLUMNS: dict[str, tuple[str, ...]] = {
    'correlation': ('col1', 'col2', 'method', 'correlation', 'abs_correlation'),
    'significance': (
        'method',
        'group_column',
        'value_column',
        'statistic',
        'p_value',
        'n_groups',
        'group_sizes',
        'significant_005',
    ),
}

# tokenize replaces the table with a word list; the shape is fixed by output_mode.
TOKENIZE_OUTPUT: dict[str, tuple[str, ...]] = {
    'word_freq': ('word', 'frequency'),
    'words_only': ('word',),
    'csv_line': ('words',),
}

# analysis steps that emit a NEW table with a fixed column set (the chart contracts live
# here: topic_map / topic_salience are what the 主题距离图 / 显著词图 read).
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
    # :func:`_replaced_columns`, never as a fixed tuple here.
}

#: Ops whose whole output is a fresh table whose names come from the node's own parameters.
STEP_DYNAMIC_REPLACE = ('compare_platform', 'sentiment_evolution')


def _replaced_columns(op: str, step: dict) -> list[str] | None:
    """The columns a dynamic replace-step will write, taken from its resolved kwargs.

    Both of these name a column after a box the user filled, so the fixed tuple they used
    to carry was a lie in both directions: it promised a ``platform`` column a renamed 平台
    never produced (a false missing-column flag downstream) and hid the real aggregate
    column, while ``sentiment_evolution`` claimed ``intensity``/``score_n`` even when no
    score column was given — a chart would read those and only find out at run time.
    """
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


#: analysis steps that keep the upstream columns and add exactly one named column
#: (value = the executor's own param holding that name, plus its default). These are the
#: CANONICAL names — a panel's box (``phase_new_col``, ``label_summary_col``) is translated
#: to them by :func:`_steps_of` through the executor's own normalizer, so one rule lives in
#: one place and a renamed box can no longer hide the column it writes.
STEP_ADD_ONE: dict[str, tuple[str, str]] = {
    'bin_column': ('new_col', ''),  # blank answers f"{column}_bin", the executor's own rule
    'extract_time': ('new_col', '日期'),
    'bin_time': ('new_col', '阶段'),
    'column_calc': ('new_col', ''),
    'topic_label': ('summary_col', '主题概括'),
    'cluster_label': ('summary_col', '摘要'),
}

# analysis steps that may ALSO add a further column, only when its box is filled.
# ``bin_time`` is the case: 阶段序号列 is what lets 各阶段 tables and charts keep the
# lifecycle order across the node boundary that erases the categorical, so a canvas that
# names one has to show it in the lineage — declared otherwise the panel hid the very
# column its own downstream steps read, and an unselected box still stayed honest.
STEP_ADD_MAYBE: dict[str, tuple[tuple[str, str], ...]] = {
    'bin_time': (('order_new_col', ''),),
}

# analysis steps that pass the upstream columns through unchanged.
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

# steps whose output the server cannot enumerate without the data (unknown).
STEP_UNKNOWN = {'groupby_agg', 'join_tables', 'rename_columns', 'topic_coherence'}

# params that name a column the node reads from its input, per type.
_PROCESS_READ_PARAMS = {
    'clean': ('text_column',),
    'emotion': ('text_column',),
    'tendency': ('text_column',),
    'sentiment': ('text_column',),
    'aggression': ('text_column',),
    'ner': ('text_column',),
    'keyword': ('text_column',),
    'cluster': ('text_column',),
    'bot': ('text_column', 'author_column', 'time_column'),
    'anomaly': (),
    'correlation': (),
    'significance': ('group_column', 'value_column'),
}
_VISUALIZE_READ_PARAMS = ('x_field', 'y_field', 'y2_field', 'label_field', 'value_field')


def _split_columns(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value or '').replace('，', ',').split(',') if p.strip()]


def _normalized_kwargs(op: str, params: dict) -> dict:
    """The executor's own kwargs for one panel's flat params, or the params themselves.

    A canvas stores each field FLAT beside ``operation`` under the *panel's* name
    (``phase_new_col``, ``label_summary_col``); the executor reads a *canonical* name
    (``new_col``, ``summary_col``). app's single translator is the only authority on that
    mapping, so it is asked here rather than duplicated — the old ``[{'op': op}]`` threw
    every sibling away and the model computed the DEFAULT column name for a node the user
    had given a new one, hiding the very column downstream steps read. Import is lazy (this
    runs inside the request cycle, not module load) and a failure falls back to the raw
    params so a lineage preview never turns into a 500.
    """
    try:
        from app import _normalize_analysis_params

        normalized = _normalize_analysis_params(op, params)
    except Exception:  # a preview must degrade to "read what is there", never crash
        normalized = {}
    return {**params, **normalized} if isinstance(normalized, dict) else dict(params)


def _step_kwargs(step: dict) -> dict:
    """One entry of a ``steps`` list, with its column kwargs resolved to canonical names.

    A step already carrying a ``params`` dict is an executor-shaped step (``/api/analysis``
    hands these) and its names are canonical; a flat step is panel-shaped and goes through
    the same translator.
    """
    nested = step.get('params')
    if isinstance(nested, dict):
        return {**step, **nested}
    op = str(step.get('op') or step.get('operation') or '')
    if not op:
        return dict(step)
    return _normalized_kwargs(op, step)


def _steps_of(params: dict) -> list[dict]:
    """The (op, canonical kwargs) pairs one analysis node will run, in order.

    Two shapes reach this function: the canvas's single flat ``operation`` with its panel
    fields beside it, and an API caller's ``steps`` list. Each is normalised through the
    executor's own translator so the column model below can key on canonical names.
    """
    steps = params.get('steps')
    if isinstance(steps, list):
        return [_step_kwargs(s) for s in steps if isinstance(s, dict)]
    op = params.get('operation')
    if not op:
        return []
    return [{'op': op, **_normalized_kwargs(str(op), params)}]


def _node_operation(node: dict) -> str:
    return str(node.get('operation') or (node.get('params') or {}).get('operation') or '')


def _dataset_columns(node: dict) -> list[str] | None:
    dataset_id = (node.get('params') or {}).get('dataset_id')
    if not dataset_id:
        return None
    try:
        from stores import get_dataset_store

        meta = get_dataset_store().meta(dataset_id)
    except Exception:  # a store read must never turn a preview into a 500
        return None
    if not meta:
        return None
    cols = meta.get('columns')
    return list(cols) if cols else None


def _analysis_output(params: dict, upstream: list[str] | None) -> list[str] | None:
    cols = upstream
    for step in _steps_of(params):
        op = str(step.get('op') or '')
        if op in STEP_UNKNOWN:
            return None
        if op in STEP_DYNAMIC_REPLACE:
            derived = _replaced_columns(op, step)
            if derived is None:
                return None
            cols = derived
            continue
        if op in STEP_REPLACE:
            cols = list(STEP_REPLACE[op])
            continue
        if op == 'select_columns':
            chosen = _split_columns(step.get('columns'))
            cols = chosen or cols
            continue
        if op in STEP_ADD_ONE:
            if cols is None:
                return None
            param, default = STEP_ADD_ONE[op]
            new_col = str(step.get(param) or default or '').strip()
            if not new_col and op == 'bin_column':
                # The executor writes f"{column}_bin" when the name box is blank, so the
                # lineage has to say the same thing rather than drop the column entirely.
                column = str(step.get('column') or '').strip()
                new_col = f'{column}_bin' if column else ''
            if new_col:
                cols = cols + [new_col]
            # `bin_time` is the one step that may add a SECOND column; every other single-add
            # step ends here, so the extra read below is skipped rather than falling through
            # (falling through would reach `return None` and call a known op unknown).
            if op not in STEP_ADD_MAYBE:
                continue
        if op in STEP_ADD_MAYBE:
            if cols is None:
                return None
            for param, default in STEP_ADD_MAYBE[op]:
                added = str(step.get(param) or default or '').strip()
                if added and added not in cols:
                    cols = cols + [added]
            continue
        if op in STEP_PASSTHROUGH:
            continue
        return None  # an op the model has not enumerated → unknown, never a guess
    return cols


def compute_columns(nodes: dict, connections: list) -> dict:
    """{node_id: [columns] | None} in topological order; None means unknown."""
    upstream: dict[str, list[str]] = {}
    for conn in connections:
        src, dst = conn.get('from'), conn.get('to')
        if src in nodes and dst in nodes:
            upstream.setdefault(dst, []).append(src)

    out: dict[str, list[str] | None] = {}
    order = _topo_ids(nodes, connections)
    for nid in order:
        node = nodes[nid]
        ntype = node.get('type')
        params = node.get('params') or {}
        parents = upstream.get(nid, [])
        parent_cols = [out.get(p) for p in parents]
        if any(c is None for c in parent_cols):
            merged = None
        elif parent_cols:
            merged = []
            for c in parent_cols:
                merged += [x for x in c if x not in merged]
        else:
            merged = []
        if ntype == 'name':
            out[nid] = []
        elif ntype == 'upload':
            out[nid] = _dataset_columns(node)
        elif ntype == 'tokenize':
            out[nid] = list(TOKENIZE_OUTPUT.get(str(params.get('output_mode') or 'word_freq'), ()))
        elif ntype == 'process':
            op = _node_operation(node)
            if op in PROCESS_REPLACE_COLUMNS:
                out[nid] = list(PROCESS_REPLACE_COLUMNS[op])
            elif op in PROCESS_ADD_COLUMNS:
                out[nid] = None if merged is None else merged + [c for c in PROCESS_ADD_COLUMNS[op] if c not in merged]
            else:
                out[nid] = None  # keyword/ner/cluster/bot/bert/…: data-dependent
        elif ntype == 'analysis':
            out[nid] = _analysis_output(params, merged)
        else:
            out[nid] = None  # source/comment/resume/visualize/output/compile: unknown or non-tabular
    return out


def referenced_columns(nodes: dict) -> dict:
    """{node_id: [column names this node will read from its input]}."""
    reads: dict[str, list[str]] = {}
    for nid, node in nodes.items():
        ntype = node.get('type')
        params = node.get('params') or {}
        found: list[str] = []
        if ntype == 'process':
            for p in _PROCESS_READ_PARAMS.get(_node_operation(node), ()):
                v = str(params.get(p) or '').strip()
                if v:
                    found.append(v)
        elif ntype == 'tokenize':
            v = str(params.get('text_column') or '').strip()
            if v:
                found.append(v)
        elif ntype == 'visualize':
            for p in _VISUALIZE_READ_PARAMS:
                v = str(params.get(p) or '').strip()
                if v:
                    found.append(v)
            found += _split_columns(params.get('stack_fields'))
        elif ntype == 'analysis':
            for step in _steps_of(params):
                spec = STEP_PARAMS.get(str(step.get('op') or ''), {})
                for key in ('one', 'some'):
                    for pname in spec.get(key, ()):
                        found += _split_columns(step.get(pname))
        reads[nid] = [c for c in found if c]
    return reads


def _topo_ids(nodes: dict, connections: list) -> list[str]:
    indeg = {nid: 0 for nid in nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for conn in connections:
        src, dst = conn.get('from'), conn.get('to')
        if src in nodes and dst in nodes:
            adj[src].append(dst)
            indeg[dst] += 1
    queue = [n for n, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    for nid in nodes:  # a cycle: append the rest so every node still gets an entry
        if nid not in order:
            order.append(nid)
    return order
