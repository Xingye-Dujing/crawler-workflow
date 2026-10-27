"""WeChat public-account articles: read by URL, with no session to want.

``crawler.py`` scrapes ``mp.weixin.qq.com`` article bodies one link at a time. The platform
deliberately declares no ``login_url`` — the article body is served anonymously, so a cookie question
here would be a made-up requirement (and ``sessions.preflight`` refuses to ask one).
"""
