"""X (Twitter): a virtualized timeline, so only the visible window can be read.

``crawler.py`` holds the card extractor and the window-walk that keeps scrolling it (a node that
scrolled out of view no longer exists, which is why the read happens per step rather than at the
end); ``comments.py`` reuses that same extractor for reply rows instead of writing a second one.
"""
