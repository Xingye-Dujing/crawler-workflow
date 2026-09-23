"""Mechanics shared by every platform crawler.

This package holds *how* a crawl is done — scrolling, paging a cursor, reading a
number off a label, telling a login wall from an empty result, dismissing a
first-run dialog. A platform module under :mod:`crawlers.platforms` holds only
what is specific to its site: which selectors render a card, which endpoint
answers with the real figures, which column names to write.

The split is the point: with nine platforms and several crawl modes each, the
same loop used to be open-coded three times (zhihu/xhs scrolling, three copies of
万/千 parsing, two in-page fetchers, five variants of "wait until the list has
mounted"), and every new platform paid for another copy. Nothing here knows what
a 微博 or a 视频 is.
"""
