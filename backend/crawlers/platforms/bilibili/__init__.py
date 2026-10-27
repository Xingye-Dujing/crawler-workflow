"""Bilibili: paged search resolved through the site's own JSON, an author walk and the hot boards.

``crawler.py`` extends ``crawlers.core.video.VideoCrawler`` (a row is a video); ``comments.py`` maps
``reply/main`` payloads into rows, including the nested replies flattened, and carries the per-code
verdict table that tells a dead video from a rate-limited session.
"""
