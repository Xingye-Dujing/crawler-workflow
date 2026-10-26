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
