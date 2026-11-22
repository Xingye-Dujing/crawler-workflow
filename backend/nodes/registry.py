"""The executor registry: type → ``run(node, call)``.

The catalogue (``nodes/catalog.py``) says which types exist; this table says how they run. They are
pinned against each other by ``tests/unit/analysis/test_node_plugins.py``, so a type cannot be declared with
no executor, and an executor cannot be registered for a type nobody declared.

Every node type is a plugin here. The handler is ``run(node, call)`` in
``nodes/executors/<type>.py``; each manifest names that function, so a type's name is declared once
(``identity.id``) and its behavior once (``execution.handler``). This module asks the kernel registry
for every handler and registers it, so there is no second list here. A plugin depends only on its
arguments and the shared service modules — never on ``app``, which would import Flask into the
worker and cycle back to this table (``tests/unit/analysis/test_node_plugins.py`` scans for that
import).

``load_builtin_executors`` is explicit rather than automatic because importing ``nodes`` from the
engine (``engine/workflow``) would otherwise drag pandas, the analyzers and the biblio services into
every DAG parse. The heavy modules load in ``app`` where they already do.
"""

from __future__ import annotations

from nodes.context import NodeExecutor

_EXECUTORS: dict[str, NodeExecutor] = {}
_BUILTINS_LOADED = False


def register(node_type: str, executor: NodeExecutor) -> None:
    """Bind one type to its executor. A duplicate is refused, never silently overwritten."""
    key = str(node_type or '').strip()
    if not key:
        raise ValueError('a node executor needs a type')
    if key in _EXECUTORS and _EXECUTORS[key] is not executor:
        raise ValueError(f'node type {key} already has an executor')
    _EXECUTORS[key] = executor


def executor_for(node_type: str) -> NodeExecutor | None:
    """The executor for *node_type*, or ``None`` — the caller decides how to refuse."""
    return _EXECUTORS.get(str(node_type or ''))


def registered_types() -> frozenset[str]:
    return frozenset(_EXECUTORS)


def load_builtin_executors() -> None:
    """Register every built-in plugin from its manifest, once.

    Idempotent: ``app`` calls it at import, tests may call it again after resetting the registry.
    The kernel resolves each manifest's ``module:function`` handler (importing that executor
    module on the spot) and registers it in this table, so there is no second list to keep.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    from capabilities_kernel import registry as capabilities

    capabilities.register_node_executors()
    _BUILTINS_LOADED = True


def reset_for_tests() -> None:
    """Drop every registration and the built-in flag; the next load starts from scratch."""
    global _BUILTINS_LOADED
    _EXECUTORS.clear()
    _BUILTINS_LOADED = False
