"""Weibo: server-rendered paged search on ``s.weibo.com``, plus hot search and an author walk.

``crawler.py`` issues no in-page script at all (the HTML is already rendered — measured, and the
reason it does not scroll); ``comments.py`` reads the ``buildComments`` JSON and keeps an emoji-only
comment's text, which the naive tag-strip lost.
"""
