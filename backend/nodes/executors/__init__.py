"""Built-in node plugins.

Only the types still declared in ``nodes/catalog.py`` register here. A migrated type is registered
from its own manifest: ``nodes.registry.load_builtin_executors`` asks
``capabilities_kernel.registry.register_node_executors`` after importing this package, so
``capabilities_kernel/nodes/<id>/manifest.py`` is the one place that names the type AND its handler.

The registry loader imports this package once, from ``app`` — never from ``engine.workflow``, which
must stay light enough to parse a DAG without pandas and the analyzers.
"""

from nodes import registry
from nodes.executors import source

#: One line per type that has no manifest yet. Adding a migrated type does not touch this file.
_BUILTINS = (source,)

for _module in _BUILTINS:
    registry.register(_module.NODE_TYPE, _module.run)
