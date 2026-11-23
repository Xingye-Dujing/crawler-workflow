"""Static output-column model for lineage — what each node emits, WITHOUT a run.

Only producers whose full output set is fixed and knowable are modelled. Anything whose
shape depends on data the server has not seen — a crawl (each platform builds its own
``_row``), a comment parse, a resume replay, an author-derived ``bot`` table, a
switch-dependent ``keyword``/``ner``/``cluster``/bert output, a ``groupby_agg``/``join``
whose extra columns are named after their inputs — is UNKNOWN (``None``). A node
downstream of an unknown is unknown too, and an unknown never produces a
missing-column flag: the whole point is to never tell the user a column is absent when
we cannot actually see the table (AGENTS: refuse by name, never guess a shape).

**A node type's column rule lives with the node type.** A plugin in ``nodes/executors/<type>.py``
may declare ``emit_columns(node, merged)``; this module walks the graph, folds the fan-in and asks.
A plugin that declares nothing is unknown — that is the answer, not a gap: ``source``, ``comment``,
``resume``, ``output``, ``compile`` and ``visualize`` are exactly the nodes whose table no static
view can see. The old shape (one 340-line module holding eighteen ``elif ntype == …`` branches,
with the process/analysis/biblio/fuse/upload rules written inside it) meant a new node type
silently answered "unknown" from a chain nobody had edited.

A consumer's declared reads are its manifest's ``ports.read_columns``; ``services.validation``
checks them against the producer's recorded or declared shape, so this module holds no second
copy of the missing-column rule.
"""

from __future__ import annotations

import importlib

from nodes import registry


def _plugin(node_type: str):
    """The executor module that owns *node_type*, or ``None`` when nothing is registered for it.

    The registry is asked rather than ``importlib.import_module('nodes.executors.' + type)``
    because the registry is the one place that knows which plugin serves which type (``compile``
    is imported under a different module name precisely because it shadows a builtin). Nothing is
    memoised here: ``nodes.registry.reset_for_tests`` exists, and a cache keyed by node type would
    outlive a swapped-out plugin and answer from the old one.

    Importing the executor package runs every plugin's module body — pandas, the analyzers, the
    services — so this happens at use time, never at module load: parsing a DAG must not become a
    crawler import.
    """
    registry.load_builtin_executors()
    executor = registry.executor_for(str(node_type or ''))
    if executor is None:
        return None
    return importlib.import_module(executor.__module__)


def _hook(node_type: str, name: str):
    plugin = _plugin(node_type)
    return getattr(plugin, name, None) if plugin is not None else None


def _merged_columns(out: dict, parents: list[str]) -> list[str] | None:
    """The parents' union in edge order, or None when any parent is unknown."""
    parent_cols = [out.get(parent_id) for parent_id in parents]
    if any(cols is None for cols in parent_cols):
        return None
    merged: list[str] = []
    for cols in parent_cols:
        merged += [column for column in (cols or []) if column not in merged]
    return merged


def compute_columns(nodes: dict, connections: list) -> dict:
    """{node_id: [columns] | None} in topological order; None means unknown."""
    upstream: dict[str, list[str]] = {}
    for conn in connections:
        src, dst = conn.get('from'), conn.get('to')
        if src in nodes and dst in nodes:
            upstream.setdefault(dst, []).append(src)

    out: dict[str, list[str] | None] = {}
    for nid in _topo_ids(nodes, connections):
        node = nodes[nid]
        emit = _hook(node.get('type'), 'emit_columns')
        if emit is None:
            out[nid] = None  # no declared contract: unknown, never a guess
        else:
            out[nid] = emit(node, _merged_columns(out, upstream.get(nid, [])))
    return out


def param_errors(nodes: dict) -> dict:
    """{node_id: [problem...]} — parameter problems a plugin answers WITHOUT a run.

    A problem is data (``code`` + the parameter/box it is about), never a sentence: the canvas
    badge words it from the browser catalogue. A plugin that declares no ``param_errors`` hook
    answers ``[]`` — a type with nothing to check is not a gap to guess at.
    """
    problems: dict[str, list[dict]] = {}
    for nid, node in nodes.items():
        hook = _hook(node.get('type'), 'param_errors')
        problems[nid] = list(hook(node) or []) if hook is not None else []
    return problems


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
