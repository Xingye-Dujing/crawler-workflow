"""Crawl backends — the second way a row can arrive.

``catbus.py`` drives the CatBus adapter as a subprocess and presents the same ``Crawler`` surface the
browser path does (sink, cursor, watermark, end reason), so the node executor stays backend-agnostic
and 继续 resumes either way. Which platforms and modes exist here, what columns a row has and which
column is its identity are read out of the adapter's own ``capabilities`` manifest — never copied
into a Python table — and every failure names the missing part instead of answering with an empty
table a node would settle DONE on.

The Selenium path is not a file in here: it is ``crawlers/platforms/`` plus ``crawlers/core/``.
"""
