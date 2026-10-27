"""Douyin: DOM-only, one video page opened per row, driven from the search bar.

``crawler.py`` has no ``search`` of its own beyond the bar walk (the site answers nothing queryable
off-page) and declares the trust-login prompt it has to clear; ``comments.py`` cuts the rendered
comment block by shape — body first, the site's own "time · region" line as the anchor, so a wrapped
comment keeps every line and a timestamp is never filed as the text.
"""
