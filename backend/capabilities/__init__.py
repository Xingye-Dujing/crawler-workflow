"""The declaration layer: what each platform can collect, and what that needs — no crawling code.

This package answers "can this platform do this, in this mode, on this engine?" without importing
Selenium, pandas or the application, so the panel and the pre-run gate can ask it at page load.
``registry`` is the matrix and its queries today; the next slice splits it into ``model`` /
``requirements`` / ``platforms/<id>`` / ``catbus`` and folds the per-platform facts that currently
live under ``crawlers/engine/`` (wall/popup vocabulary) in here, so one platform is declared once.

The package ``__init__`` imports nothing: callers name ``capabilities.registry`` (or import the
names they need from it), which keeps import order explicit and the package free of barrels.
"""
