"""What each node's output table holds: the evidence a consumer's reads are checked against.

A node declares the columns it reads (``Manifest.ports.read_columns``); validation compares that
list with what its upstream produces. Two sources can answer the second half, and they are NOT
equally strong:

* **what the producer really wrote** — ``node_schema`` rows, filed when a node settles. They are
  keyed by the node fingerprint, so a table produced by a different definition is never evidence
  about this one. This is the answer for a crawl, whose columns no static model can see.
* **what the producer's contract says** — ``nodes.schema.compute_columns``, which asks each
  plugin's ``emit_columns`` hook. This is the answer before the first run, and for a producer whose
  shape is fixed (an upload's dataset columns, a tokenizer's word/frequency).

Recorded wins: it is the table this node would actually receive. A node with neither answer stays
``None`` (unknown), and the engine then says nothing — a missing column is named only when the
table is provably known.

The engine itself never opens a database (``WorkflowEngine`` stays pure): this module is the caller
that reads the store and hands the mapping over. A store failure is answered as "no recorded shape"
and logged; the declared contract still applies, so a locked ``runs.db`` costs the extra evidence,
never the whole badge.
"""

from __future__ import annotations

import logging

from i18n import t

logger = logging.getLogger(__name__)


def _recorded(workflow: dict) -> dict[str, list]:
    """``{node_id: columns}`` from the newest settled run of the current definition."""
    from runtime.stores import get_run_store

    from services.runs.store.identity import fingerprints_for_workflow

    try:
        fingerprints = fingerprints_for_workflow(workflow)
        return get_run_store().schemas_for(fingerprints)
    except Exception:  # a locked/missing store costs the recorded half, never the badges
        logger.exception(t('run.schemaReadFailed'))
        return {}


def columns_for(workflow: dict) -> dict[str, list | None]:
    """``{node_id: columns | None}`` on the EFFECTIVE graph, recorded shape first.

    A ``None`` is a real answer ("this table is unknown") and must never be read as "no columns":
    the engine skips a consumer whose upstream is unknown rather than flagging every read.
    """
    from nodes.schema import compute_columns

    from engine.workflow import effective_workflow

    effective = effective_workflow(workflow)
    nodes = {
        str(node['id']): node for node in effective.get('nodes') or [] if isinstance(node, dict) and node.get('id')
    }
    declared = compute_columns(nodes, effective.get('connections') or [])
    recorded = _recorded(effective)
    return {nid: recorded.get(nid, columns) for nid, columns in declared.items()}
