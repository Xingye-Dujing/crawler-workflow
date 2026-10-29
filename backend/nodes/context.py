"""The one call shape every node executor receives.

An executor is a plugin function ``run(node, call)``. Keeping the arguments in one object does two
things the if-chain could not: an executor declares exactly which pieces of the run it needs (and the
registry test can see that), and moving an executor into ``nodes/executors/<type>.py`` changes no
signature. ``app.py`` builds one ``NodeCall`` per node and every plugin reads the same fields.

The fields are deliberately the run loop's own vocabulary — ``current_input`` is the flattened fan-in,
``upstream`` is the (parent_id, result) pairs for nodes that need provenance, ``ctx`` is the durable
run context — not a general-purpose context bag. A new executor that needs a new fact adds a field
here with a reason, not an attribute reached off ``app``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NodeCall:
    """Everything a node executor may need besides its own node dict."""

    headless: bool
    current_input: list
    run_ctx: dict | None
    upstream: list | None
    ctx: dict | None
    platform_of: dict | None
    label_of: Any


#: ``(node, call) -> result``. ``result`` is a list of rows or a dict for the artifact nodes
#: (visualize/compile), exactly what the executor has always returned.
NodeExecutor = Callable[[dict, NodeCall], object]


def split_panel_columns(value) -> list[str]:
    """The settings box's column list, reading a Chinese comma as a separator too.

    ``core.refs.split_columns`` is the pipeline's gate on ``'a,b'``; the panels also accept
    ``'a，b'``, and the lineage view has always folded that second comma. Kept here (rather than
    widening ``split_columns``) so an executor that declares its own column contract can use the
    exact rule the settings box is written with, without changing what the gate accepts.
    """
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value or '').replace('，', ',').split(',') if p.strip()]


def node_operation(node: dict) -> str:
    """The operation a plugin was asked to run, from either shape the canvas writes.

    A node keeps ``operation`` beside the node itself or inside ``params`` depending on how it was
    built; the column contract keys on it either way.
    """
    return str(node.get('operation') or (node.get('params') or {}).get('operation') or '')


def node_params(node: dict) -> dict:
    return node.get('params') or {}


def columns_from_params(params: dict, names) -> list[str]:
    """The column names a plugin's declared params actually hold, skipping blanks.

    A plugin declares ``READ_PARAMS = ('text_column',)`` and the lineage view turns those
    parameter names into the columns the node will read. Each box holds ONE name (a comma inside
    it is part of the name, which is how the executor reads it too); a list-valued box is the
    plugin's own business, not this helper's.
    """
    found: list[str] = []
    for name in names:
        value = str(params.get(name) or '').strip()
        if value:
            found.append(value)
    return found
