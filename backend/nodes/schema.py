"""Static output-column model for lineage — what each node emits, WITHOUT a run.

Only producers whose full output set is fixed and knowable are modelled. Anything whose
shape depends on data the server has not seen — a crawl (each platform builds its own
``_row``), a comment parse, a resume replay, an author-derived ``bot`` table, a
switch-dependent ``keyword``/``ner``/``cluster``/bert output, a ``groupby_agg``/``join``
whose extra columns are named after their inputs — is UNKNOWN (``None``). A node
downstream of an unknown is unknown too, and an unknown never produces a
missing-column flag: the whole point is to never tell the user a column is absent when
we cannot actually see the table (AGENTS: refuse by name, never guess a shape).

The per-op tables live beside the code that owns them now: process ops declare theirs in
``services/process_params.py``, analysis steps in ``services/analysis_params.py``, and the
tokenize/visualize read lists in their own plugins. This module only aggregates them.

``referenced_columns`` answers the other half: which columns a node will READ from its
input, taken straight from the params the user typed (a chart's ``x_field``, an analysis
step's ``column``). The frontend compares those against the upstream node's emitted
columns and flags a provable miss — the schema truth lives here, the wording lives there.
"""

from __future__ import annotations

from services.analysis_params import (
    STEP_ADD_MAYBE,
    STEP_ADD_ONE,
    STEP_DYNAMIC_REPLACE,
    STEP_PASSTHROUGH,
    STEP_REPLACE,
    STEP_UNKNOWN,
    normalize_analysis_params,
    replaced_columns,
)
from services.biblio.fuse import OUTPUT_COLUMNS as FUSE_OUTPUT_COLUMNS
from services.biblio.fuse import ROLE_PARAMS as FUSE_ROLE_PARAMS
from services.biblio.schema import CITATION_TYPES, COUPLING_TYPES
from services.biblio.schema import output_columns as biblio_output_columns
from services.biblio.schema import read_columns as biblio_read_columns
from services.chart_contracts import BIBLIO_CHART_READS
from services.data_analysis import STEP_PARAMS
from services.process_params import OUTPUT_ADD_COLUMNS, OUTPUT_REPLACE_COLUMNS
from services.process_params import READ_PARAMS as PROCESS_READ_PARAMS


def _tokenize_contract():
    """The tokenize plugin's output table and read list, imported lazily.

    Importing ``nodes.executors`` runs its package initializer (which registers every
    executor and therefore pulls the analyzers); the lineage view is requested long after
    boot, so the import belongs at use time rather than at module load.
    """
    from nodes.executors import tokenize

    return tokenize.OUTPUT_COLUMNS, tokenize.READ_PARAMS


def _visualize_read_params():
    from nodes.executors import visualize

    return visualize.READ_PARAMS


def _split_columns(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value or '').replace('，', ',').split(',') if p.strip()]


def _normalized_kwargs(op: str, params: dict) -> dict:
    """The executor's own kwargs for one panel's flat params, or the params themselves.

    A canvas stores each field FLAT beside ``operation`` under the *panel's* name
    (``phase_new_col``, ``label_summary_col``); the executor reads a *canonical* name
    (``new_col``, ``summary_col``). ``services.analysis_params`` is the only authority on that
    mapping, so it is asked here rather than duplicated — the old ``[{'op': op}]`` threw
    every sibling away and the model computed the DEFAULT column name for a node the user
    had given a new one, hiding the very column downstream steps read.
    """
    try:
        normalized = normalize_analysis_params(op, params)
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
            derived = replaced_columns(op, step)
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
            tokenize_output, _reads = _tokenize_contract()
            out[nid] = list(tokenize_output.get(str(params.get('output_mode') or 'word_freq'), ()))
        elif ntype == 'process':
            op = _node_operation(node)
            if op in OUTPUT_REPLACE_COLUMNS:
                out[nid] = list(OUTPUT_REPLACE_COLUMNS[op])
            elif op in OUTPUT_ADD_COLUMNS:
                out[nid] = None if merged is None else merged + [c for c in OUTPUT_ADD_COLUMNS[op] if c not in merged]
            else:
                out[nid] = None  # keyword/ner/cluster/bot/bert/…: data-dependent
        elif ntype == 'analysis':
            out[nid] = _analysis_output(params, merged)
        elif ntype == 'biblio':
            out[nid] = biblio_output_columns(params, merged or [])
        elif ntype == 'fuse':
            # A fusion node's output is a fixed contract, not a projection of its inputs: that
            # is the whole point — downstream reads canonical names whatever the sources called
            # their columns.
            out[nid] = list(FUSE_OUTPUT_COLUMNS)
        elif ntype == 'accumulate':
            # It appends rows and passes the union through, so the schema is exactly the
            # upstream schema (unknown when the upstream is unknown).
            out[nid] = merged
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
            for p in PROCESS_READ_PARAMS.get(_node_operation(node), ()):
                v = str(params.get(p) or '').strip()
                if v:
                    found.append(v)
        elif ntype == 'tokenize':
            _output, tokenize_reads = _tokenize_contract()
            for p in tokenize_reads:
                v = str(params.get(p) or '').strip()
                if v:
                    found.append(v)
        elif ntype == 'visualize':
            for p in _visualize_read_params():
                v = str(params.get(p) or '').strip()
                if v:
                    found.append(v)
            found += _split_columns(params.get('stack_fields'))
            chart = str(params.get('chart_type') or '')
            found += list(BIBLIO_CHART_READS.get(chart, ()))
        elif ntype == 'fuse':
            # Every candidate column, because which one a given parent answers with is data-
            # dependent; diagnostics flags a candidate only when NO parent can supply it.
            for key in FUSE_ROLE_PARAMS:
                found += _split_columns(params.get(key))
        elif ntype == 'biblio':
            entity = str(params.get('entity_type') or 'keyword')
            columns = biblio_read_columns(params)
            if entity in CITATION_TYPES or entity in COUPLING_TYPES:
                found += [columns['reference'], columns['year']]
                if entity in ('document', 'bibliographic_coupling'):
                    found.append(columns['title'])
                if entity == 'journal':
                    found.append(columns['entity'])
            elif entity == 'term':
                found.append(columns['year'])
            else:
                found += [columns['entity'], columns['year']]
            if str(params.get('min_tc') or '').strip():
                found.append(columns['tc'])
            if str(params.get('min_usage') or '').strip():
                found.append(columns['usage'])
            for key in ('sentiment_column', 'topic_column'):
                value = str(params.get(key) or '').strip()
                if value:
                    found.append(value)
            # An explicit label source is a hard read; ``all`` is the lenient historical mix and
            # asks nothing (a table without 摘要 still labels from its keywords).
            source = str(params.get('label_source') or 'all')
            if source == 'title':
                found.append(columns['title'])
            elif source == 'abstract':
                found.append(columns['abstract'])
            elif source == 'keywords':
                found.append(columns['entity'] if entity == 'keyword' else '关键词')
            elif source == 'author':
                found.append(columns['entity'] if entity == 'author' else '作者')
            if str(params.get('output_shape') or '') == 'dual_map':
                found += ['参考文献', '来源期刊', '学科', '年份']
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
