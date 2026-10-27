"""Zhihu: infinite-scroll search results, an author profile walk and the hot-board API.

``crawler.py`` is ``ZhihuCrawler`` (selectors, the hot-board endpoint, how a profile tab is walked);
``comments.py`` turns the tuples read out of a comment panel into rows — the in-page script lives on
the ``CommentSession`` side, because that is where the live browser is.
"""
