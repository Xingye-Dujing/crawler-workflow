"""Instagram: cookie capture only.

``LoginOnlyCrawler`` is the shape for a platform the panel can log into while nothing crawls it:
``supports_crawl = False`` makes the crawl matrix and the execute endpoint refuse **by name**, so the
login entry is offered and the crawl is not. The crawl itself is absent on purpose — it is the shape
Bilibili, Douyin, YouTube and X had before their walks were measured and written.
"""
