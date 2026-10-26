"""The executor registry: type → ``run(node, call)``.

The catalogue (``nodes/catalog.py``) says which types exist; this table says how they run. They are
pinned against each other by ``tests/unit/test_node_plugins.py``, so a type cannot be declared with
no executor, and an executor cannot be registered for a type nobody declared.

Two kinds of registration, on purpose:

- **Built-in plugins** (name/upload/resume/tokenize/accumulate/compile/biblio/fuse) live in
  ``nodes/executors/<type>.py`` and register themselves when ``nodes.executors`` is imported. They
  depend only on their arguments and the shared service modules — no ``app`` import, no cycle.
- **App-side executors** (source/comment/process/analysis/visualize/output) still live in ``app.py``
  and are registered by ``app`` once at import. Phase 1b of ``docs/refactor_plan.md`` moves them
  here one at a time, before ``source``/``comment`` (the browser and comment-engine paths) are moved
  last.

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
