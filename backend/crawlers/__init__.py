from crawlers.overseas import InstagramCrawler, TwitterCrawler, YouTubeCrawler
from crawlers.video import BilibiliCrawler, DouyinCrawler
from crawlers.wechat import WechatCrawler
from crawlers.weibo import WeiboCrawler
from crawlers.xiaohongshu import XiaohongshuCrawler
from crawlers.zhihu import ZhihuCrawler

# The registry, not just the factory: the cookie panel needs each platform's
# host list and login page to explain itself, and reaching those through
# ``get_crawler`` would boot a real Chrome browser to read a class attribute.
CRAWLERS = {
    'zhihu': ZhihuCrawler,
    'weibo': WeiboCrawler,
    'xiaohongshu': XiaohongshuCrawler,
    'wechat': WechatCrawler,
    'bilibili': BilibiliCrawler,
    'douyin': DouyinCrawler,
    # Cookie capture only: the panel can save a login session for these three
    # while their crawl is not built yet, so the canvas and the execute endpoint
    # refuse them (see crawlers/overseas.py).
    'twitter': TwitterCrawler,
    'instagram': InstagramCrawler,
    'youtube': YouTubeCrawler,
}


def is_crawlable(platform: str) -> bool:
    """Whether *platform* can be used as a data source (not just logged into)."""
    cls = crawler_class(platform)
    return bool(cls) and bool(getattr(cls, 'supports_crawl', True))


def crawler_class(platform: str):
    """The crawler class for *platform*, or None when nothing crawls it."""
    return CRAWLERS.get(str(platform or ''))


def cookie_hosts(platform: str) -> tuple:
    """Every host a saved cookie for *platform* has to be valid on.

    Read off the class, so the panel's "paste a link from this site" can never
    drift from what the crawler actually plants cookies on.
    """
    cls = crawler_class(platform)
    if cls is None:
        return ()
    return tuple(host for host in (cls.domain, *cls.cookie_domains) if host)


def get_crawler(platform: str, headless: bool = True, cookie_dir: str = None):
    cls = crawler_class(platform)
    if not cls:
        raise ValueError(f'Unknown platform: {platform}')
    cookie_path = f'{cookie_dir}/{platform}_cookies.json' if cookie_dir else None
    return cls(headless=headless, cookie_path=cookie_path)
