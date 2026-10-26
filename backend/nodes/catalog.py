"""The node-type catalogue: one declaration per plugin.

Before this module the set of node types lived in three places that could each be edited alone:
``engine/workflow.py`` held the engine's sets, ``app.py`` held the executor dispatch (an if-chain
whose last branch was the only thing noticing a type with no executor), and ``canvas.js`` held its
own ``_VALID_NODE_TYPES`` plus a labels map. Adding a type meant editing all three and hoping none
was forgotten; a contract test comparing them did not exist.

This is the backend half of the plugin seam (the frontend still renders its own catalogue until
Phase 2 — see ``docs/refactor_plan.md``): one ``NodePlugin`` per type declares what the type is for,
which shape it carries downstream, and whether its console lines are quiet. The engine derives its
sets from here, and the executor table in ``app.py`` is pinned against it by a test, so a new type
cannot be half-registered.

The plugin's **behaviour** still lives in ``app.py`` today. Phase 2 of the plan moves each executor
body into ``backend/nodes/executors/<type>.py`` behind the same ``(node, call)`` signature; the
catalogue and the registry stay the same then, which is why this step is worth landing first.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Row shapes a node can carry downstream. ``table`` is the normal case; ``pdf`` is a LaTeX/PDF
#: artifact (``visualize`` emits a chart spec whose LaTeX a save node can compile, ``compile`` emits
#: the PDF itself); ``none`` is metadata only (``name``).
ROW_SHAPES = ('table', 'pdf', 'none')


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


PLUGINS: dict[str, NodePlugin] = {
    'name': NodePlugin('name', 'nodeType.name', 'meta', rows='none', quiet=True),
    'source': NodePlugin('source', 'nodeType.source', 'data'),
    'upload': NodePlugin('upload', 'nodeType.upload', 'data', quiet=True),
    'resume': NodePlugin('resume', 'nodeType.resume', 'data'),
    'comment': NodePlugin('comment', 'nodeType.comment', 'data'),
    'process': NodePlugin('process', 'nodeType.process', 'process'),
    'analysis': NodePlugin('analysis', 'nodeType.analysis', 'analysis'),
    'tokenize': NodePlugin('tokenize', 'nodeType.tokenize', 'process'),
    'biblio': NodePlugin('biblio', 'nodeType.biblio', 'biblio'),
    'fuse': NodePlugin('fuse', 'nodeType.fuse', 'biblio'),
    'accumulate': NodePlugin('accumulate', 'nodeType.accumulate', 'data'),
    'visualize': NodePlugin('visualize', 'nodeType.visualize', 'visualize', rows='pdf'),
    'compile': NodePlugin('compile', 'nodeType.compile', 'visualize', rows='pdf'),
    'output': NodePlugin('output', 'nodeType.output', 'output'),
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


def plugin_for(node_type: str) -> NodePlugin | None:
    """The declaration for *node_type*, or ``None`` — the caller decides how to refuse."""
    return PLUGINS.get(str(node_type or ''))


def types_in(category: str) -> tuple[str, ...]:
    """Types in one palette category, in catalogue order (for docs and a future palette)."""
    return tuple(plugin.type for plugin in PLUGINS.values() if plugin.category == category)
