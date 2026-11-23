"""The preflight's rows: what a node's upstream last produced, for validation to judge.

A capability may declare ``preflight='module:function'`` (the ADR's ``preflight(node, sample)``) —
a check that needs DATA, not just the graph: does the chart's value column hold any number, is the
column it names in the table at all. The sample is up to 200 rows of the node's upstream output
from the newest stored run, and it is offered ONLY when that run's recorded node fingerprint equals
the current graph's: a table from a different configuration is not evidence about this one.

Two properties matter more than the check itself:

* **the engine stays pure.** ``WorkflowEngine`` never opens a database; this module hands it a
  mapping and the caller (the diagnostics/validate routes and the run gate) owns the read.
* **the read is cached.** Diagnostics runs on every edit debounce; a sample is keyed by
  ``(runs.db, node id, fingerprint)`` and kept for ``SAMPLE_TTL`` seconds, bounded in count. A run
  that finishes after a read appears within the TTL — the answer is a hint on a canvas being
  edited, never a durable verdict.

A missing sample is answered as "no sample" and the preflight is not called: the canvas says what
it knows, never a guess. Nothing here raises into a route; the caller wraps it.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

#: Rows one preflight may look at. Enough to prove "this column holds no number", small enough
#: that a 100k-row crawl costs one indexed LIMIT query.
SAMPLE_LIMIT = 200

#: How long a cached sample is trusted. The edit-time badge may lag a finished run by this much;
#: it never lags a row that did not exist when it was read.
SAMPLE_TTL = 30.0

#: Samples kept at once (per account's db, node and fingerprint). 32 × 200 rows is a few MB,
#: and the oldest is dropped first.
SAMPLE_CACHE_MAX = 32

_CACHE: OrderedDict[tuple[str, str, str], tuple[float, tuple[str, list]]] = OrderedDict()
_LOCK = threading.Lock()


def clear_cache() -> None:
    """Forget every cached sample (tests, and an account switch that reuses a path)."""
    with _LOCK:
        _CACHE.clear()


def _data_root() -> str:
    from runtime import paths

    # The per-account runs.db: two accounts can hold the same node id and fingerprint, and their
    # rows must never answer for each other. Resolved at CALL time (paths.active()).
    return str(paths.active().runs_db)


def _sample(store, node_id: str, fingerprint: str, limit: int) -> tuple[str, list]:
    """One node's stored sample, from the cache when fresh.

    A cache hit returns a fresh list of shallow-copied rows: a preflight is free to read a row, and
    two callers must never share one dict (the cache would remember the mutation).
    """
    root = _data_root()
    key = (root, str(node_id), str(fingerprint))
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and now - hit[0] < SAMPLE_TTL:
            _CACHE.move_to_end(key)
            return hit[1][0], [dict(row) for row in hit[1][1]]
    found = store.sample_rows(node_id, fingerprint, limit)
    with _LOCK:
        _CACHE[key] = (now, found)
        while len(_CACHE) > SAMPLE_CACHE_MAX:
            _CACHE.popitem(last=False)
    return found[0], [dict(row) for row in found[1]]


def samples_for(workflow: dict, limit: int = SAMPLE_LIMIT) -> dict[str, list]:
    """``{node_id: rows}`` for every node whose capability declares a preflight.

    A node's sample is the flattened fan-in of its DATA parents — the same table the run would hand
    its executor. A parent with no stored run under the current fingerprint makes the whole sample
    unknown (that node is left out); a parent whose stored run really produced zero rows
    contributes nothing, which is a sample of zero rows rather than no sample.

    A name node is metadata, not data: it never occupies a parent slot (the engine's own
    ``data_inputs`` rule).
    """
    from capabilities_kernel import registry as kernel_registry

    from services.runs.store.identity import fingerprints_for_workflow

    if not isinstance(workflow, dict):
        return {}
    from engine.workflow import effective_workflow

    effective = effective_workflow(workflow)
    nodes = {
        str(node['id']): node for node in effective.get('nodes') or [] if isinstance(node, dict) and node.get('id')
    }
    wanted = {}
    for nid, node in nodes.items():
        manifest = kernel_registry.manifest_for_node(node.get('type'))
        if manifest is not None and manifest.preflight:
            wanted[nid] = node
    if not wanted:
        return {}

    parents: dict[str, list[str]] = {}
    for conn in effective.get('connections') or []:
        if not isinstance(conn, dict):
            continue
        src, dst = str(conn.get('from')), str(conn.get('to'))
        if dst in wanted and src in nodes:
            parents.setdefault(dst, []).append(src)

    fingerprints = fingerprints_for_workflow(effective)
    from runtime.stores import get_run_store

    store = get_run_store()
    samples: dict[str, list] = {}
    for nid in wanted:
        parts: list[list] | None = []
        for pid in parents.get(nid, []):
            if nodes.get(pid, {}).get('type') == 'name':
                continue
            fingerprint = str(fingerprints.get(pid) or '')
            if not fingerprint:
                parts = None
                break
            run_id, rows = _sample(store, pid, fingerprint, limit)
            if not run_id:
                parts = None
                break
            parts.append(rows)
        if parts is None or not parts:
            continue
        samples[nid] = [row for part in parts for row in part]
    return samples
