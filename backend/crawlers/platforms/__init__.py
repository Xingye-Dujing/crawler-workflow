"""Crawl platform plugins — one directory per site.

`<id>/crawler.py` holds the crawler class plus everything that is a fact about *that* site:
selectors, endpoints, the column names a row is written with, the JS run inside the page.
`<id>/comments.py` holds the same for its comment panel. Nothing in here is shared between sites —
shared mechanics live in `crawlers/engine/` and `crawlers/core/`.

The directory name is the platform id the rest of the program uses (`crawl_capabilities`, the cookie
file, `core.refs.platform_for`), so a reader can go from a canvas node to its code in one step.
`crawlers/__init__.py` enumerates the crawler classes explicitly; there is no import-time scanning,
because a plugin that registers itself by being in a folder makes a misfiled directory a silent bug.
"""
