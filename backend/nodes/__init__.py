"""Node plugins: one declaration per node type, and (Phase 2) one executor module each.

``catalog`` is the catalogue the engine and the executor table are pinned against. See
``docs/refactor_plan.md`` for the full target and the migration phases.
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

__all__ = [
    'NODE_TYPES',
    'PDF_SOURCE_NODE_TYPES',
    'PLUGINS',
    'QUIET_NODE_TYPES',
    'TABLE_NODE_TYPES',
    'NodePlugin',
    'plugin_for',
    'types_in',
]
