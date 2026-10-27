"""YouTube: the innertube JSON called from inside the page, not from the outside.

``crawler.py`` is ``YouTubeCrawler`` (search, a channel's videos, detail) over
``crawlers.engine.innertube`` — same-origin, unsigned, cookie-carrying, and measured at 0.68 s per
search page against seconds of scrolling; ``comments.py`` reads the ``commentEntityPayload`` items.
"""
