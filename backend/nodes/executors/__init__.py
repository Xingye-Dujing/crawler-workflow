"""Built-in node plugins.

Importing this package registers each module's ``run(node, call)`` in ``nodes.registry``. The
registry loader (``nodes.registry.load_builtin_executors``) imports it once, from ``app`` — never from
``engine.workflow``, which must stay light enough to parse a DAG without pandas and the analyzers.

Adding a built-in node type: a module here with ``NODE_TYPE`` and ``run``, one line in this package,
one catalogue entry in ``nodes/catalog.py``. ``tests/unit/test_node_plugins.py`` pins the three
against each other.
"""

from nodes import registry
from nodes.executors import accumulate, biblio, fuse, name, output, resume, tokenize, upload, visualize
from nodes.executors import compile as compile_plugin

_BUILTINS = (name, upload, resume, tokenize, accumulate, compile_plugin, biblio, fuse, output, visualize)

for _module in _BUILTINS:
    registry.register(_module.NODE_TYPE, _module.run)
