"""Node plugins: one declaration per node type, one executor module for the built-in ones.

Two layers, deliberately separate:

- ``nodes.catalog`` — the catalogue the engine and the executor table are pinned against (type, row
  shape, category, console quietness, label key). Light enough for ``engine.workflow`` to import.
- ``nodes.registry`` — type → ``run(node, call)``; built-in plugins self-register from
  ``nodes.executors``, and ``app`` registers the executors that still live there.

See ``docs/archive/refactor_plan_2026-10.md`` for the full target and the migration phases.
"""

from nodes.catalog import (
    NODE_TYPES,
    PDF_SOURCE_NODE_TYPES,
    PLUGINS,
    QUIET_NODE_TYPES,
    TABLE_NODE_TYPES,
    NodePlugin,
    plugin_for,
    types_in,
)
from nodes.context import NodeCall, NodeExecutor

__all__ = [
    'NODE_TYPES',
    'PDF_SOURCE_NODE_TYPES',
    'PLUGINS',
    'QUIET_NODE_TYPES',
    'TABLE_NODE_TYPES',
    'NodeCall',
    'NodeExecutor',
    'NodePlugin',
    'plugin_for',
    'types_in',
]
