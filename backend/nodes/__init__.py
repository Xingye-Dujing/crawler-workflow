"""Node plugins: one declaration per node type, one executor module for the built-in ones.

Two layers, deliberately separate:

- ``nodes.catalog`` — the catalogue the engine and the executor table are pinned against (type, row
  shape, category, console quietness, label key). Light enough for ``engine.workflow`` to import.
- ``nodes.registry`` — type → ``run(node, call)``; built-in plugins self-register from
  ``nodes.executors``, and ``app`` registers the executors that still live there.

Modules here are imported by their explicit path (``from nodes import registry``); this package
re-exports nothing, so there is no second name for anything a module already owns.
"""
