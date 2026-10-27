"""Hongguo short dramas: four boards read from the router payload, comments heard not asked.

``crawler.py`` is ``HongguoCrawler`` (board names are the single list pinned against the crawl
matrix; search and detail refuse by name because the site gives no such page).

``harvest.py`` and ``addon.py`` are the comment path, and they are the project's only Windows-desktop
capability: a mitmproxy side-channel plus a UIA walk of the local player, because the player behind
the proxy is the only place the comment protocol appears. ``addon.py`` runs in the mitmdump process —
a different interpreter — so it imports nothing from this project. Both refuse by name when the
machine cannot run them; neither pretends an empty table is a result.
"""
