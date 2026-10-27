"""The executor registry: type → ``run(node, call)``.

The catalogue (``nodes/catalog.py``) says which types exist; this table says how they run. They are
pinned against each other by ``tests/unit/test_node_plugins.py``, so a type cannot be declared with
no executor, and an executor cannot be registered for a type nobody declared.

Every node type is a plugin here: ``nodes/executors/<type>.py`` declares ``NODE_TYPE`` and
``run(node, call)``, and importing that package registers all of them. A plugin depends only on its
arguments and the shared service modules — never on ``app``, which would import Flask into the
worker and cycle back to this table (``tests/unit/test_node_plugins.py`` scans for that import).

``load_builtin_executors`` is explicit rather than automatic because importing ``nodes`` from the
engine (``engine/workflow``) would otherwise drag pandas, the analyzers and the biblio services into
every DAG parse. The heavy modules load in ``app`` where they already do.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping

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


def register_many(executors: Mapping[str, NodeExecutor]) -> None:
    for node_type, executor in executors.items():
        register(node_type, executor)


def executor_for(node_type: str) -> NodeExecutor | None:
    """The executor for *node_type*, or ``None`` — the caller decides how to refuse."""
    return _EXECUTORS.get(str(node_type or ''))


def registered_types() -> frozenset[str]:
    return frozenset(_EXECUTORS)


def load_builtin_executors() -> None:
    """Import ``nodes.executors`` once, registering the eight built-in plugins.

    Idempotent: ``app`` calls it at import, tests may call it again after resetting the registry.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    importlib.import_module('nodes.executors')
    _BUILTINS_LOADED = True


def reset_for_tests() -> None:
    """Drop every registration and the built-in flag; the next load starts from scratch."""
    global _BUILTINS_LOADED
    _EXECUTORS.clear()
    _BUILTINS_LOADED = False
