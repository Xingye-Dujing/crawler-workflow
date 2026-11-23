"""The node-type catalogue: one declaration per plugin.

Before this module the set of node types lived in three places that could each be edited alone:
``engine/workflow.py`` held the engine's sets, ``app.py`` held the executor dispatch (an if-chain
whose last branch was the only thing noticing a type with no executor), and ``canvas.js`` held its
own ``_VALID_NODE_TYPES`` plus a labels map. Adding a type meant editing all three and hoping none
was forgotten; a contract test comparing them did not exist.

This is the backend half of the plugin seam: one ``NodePlugin`` per type declares what the type is
for, which shape it carries downstream, and whether its console lines are quiet. The engine derives
its sets from here, and the executor registry (``nodes/registry.py``) is pinned against the same
catalogue by a contract test, so a new type cannot be half-registered. The browser renders the
server's answer too (:func:`api.node_types.node_types` → ``static/js/node-types.js``) rather than
keeping a second list that can only be edited in parallel.

**Every type is declared in ``capabilities_kernel/nodes/<id>/manifest.py``.** This module is the
projection: the kernel entries are turned into ``NodePlugin`` values in the order their manifests
declare, so the served order and every downstream reader stay the same. Adding a type needs no edit
here.

Each plugin's **behaviour** lives beside its declaration: one module per type under
``backend/nodes/executors/``, behind the same ``(node, call)`` signature the registry calls. The
manifest names that module, so ``nodes.registry.load_builtin_executors`` can register a migrated
type without the catalogue growing another table.
"""

from __future__ import annotations

from dataclasses import dataclass

from capabilities_kernel import registry as capabilities


@dataclass(frozen=True)
class NodePlugin:
    """One node type, as the engine and the executor table see it."""

    type: str
    #: The frontend catalogue key for this node's word (``nodeType.<type>``); the backend uses it
    #: only in contract tests today, never to render a user-facing sentence.
    label_key: str
    #: A grouping for the palette / documentation. Not used for execution: the run graph is typed by
    #: ``rows`` and by the executor, never by a category.
    category: str
    rows: str = 'table'
    #: Whether the run console omits the generic "Executing/Node … completed" pair for this type.
    #: A console-noise decision, not a filtering hook: progress counters still count these and every
    #: fact they print still appears.
    quiet: bool = False
    #: Where a new node's defaults come from when they are not a frozen parameter list
    #: (``capabilities`` = the platform matrix). Empty means the manifest's own params.
    defaults_from: str = ''


#: The served catalogue: one entry per manifest, in the order the manifests declare. A duplicate id
#: is refused by ``capabilities_kernel.registry`` at discovery, so there is no literal to merge with
#: and no second answer to keep in step.
PLUGINS: dict[str, NodePlugin] = {
    entry['type']: NodePlugin(
        entry['type'],
        entry['label_key'],
        entry['category'],
        rows=entry['rows'],
        quiet=entry['quiet'],
        defaults_from=entry['defaults_from'],
    )
    for entry in capabilities.node_entries()
}

#: Every type the engine can execute. A hand-edited canvas can name a node anything; a type outside
#: this set has no executor, so validation refuses it by name instead of falling through to an empty
#: table that would settle DONE over nothing measured.
NODE_TYPES = frozenset(PLUGINS)

#: Node types whose result is a table of rows.
TABLE_NODE_TYPES = frozenset(plugin.type for plugin in PLUGINS.values() if plugin.rows == 'table')

#: Node types that carry a PDF-able artifact rather than a row table.
PDF_SOURCE_NODE_TYPES = frozenset(plugin.type for plugin in PLUGINS.values() if plugin.rows == 'pdf')

#: Types whose generic console pair is omitted.
QUIET_NODE_TYPES = frozenset(plugin.type for plugin in PLUGINS.values() if plugin.quiet)
