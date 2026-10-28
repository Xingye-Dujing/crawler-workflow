"""The declaration layer: what each platform can collect, and what that needs — no crawling code.

This package answers "can this platform do this, in this mode, on this engine?" without importing
Selenium, pandas or the application, so the panel and the pre-run gate can ask it at page load.
``platforms/<id>`` declares one platform each (panel order pinned by ``platforms/__init__``),
``fields`` the shared atoms and mode factories, ``catbus`` the second engine's own vocabulary,
``model``/``requirements`` the dataclasses and machine gates, and ``registry`` the queries over
all of it. One platform is declared once — the engine/crawler side imports these declarations
rather than keeping a copy.

The package ``__init__`` imports nothing: callers name ``capabilities.registry`` (or import the
names they need from it), which keeps import order explicit and the package free of barrels.
"""
