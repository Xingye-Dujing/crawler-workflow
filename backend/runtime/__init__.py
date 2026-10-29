"""Process-wide runtime wiring: the live run state, the store singletons and the policies over them.

Everything a route, a node executor and a test can reach without importing the Flask module or
the run orchestration. These five modules used to sit at the ``backend/`` root next to ``app.py``;
they are a layer of their own — ``app.py`` is the composition root, ``i18n.py`` the message
machinery, and this package is what a process *is* while it runs:

``state``      the in-place run state, console buffers, queue, dataset cache (never rebound);
``stores``     the lazily opened SQLite singletons and their test seam;
``settings``   the runtime-editable settings persisted to ``data/settings.json``;
``gate``       the same-platform crawl gate (one platform is one conversation);
``transport``  the cloud refusal for local-only model transports.

Unlike ``core/`` this layer *does* import domain packages (``sessions``/``services``): the objects
it publishes are built from them at import. It must not import ``app`` — the composition root
imports this package, not the other way round. ``tests/unit/gates/test_foundation_layering.py``
keeps ``core`` free of it, and ``tests/unit/gates/test_backend_root.py`` keeps the root free of
new modules.
"""
