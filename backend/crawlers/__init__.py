import browser_profiles

from crawlers.overseas import InstagramCrawler
from crawlers.twitter import TwitterCrawler
from crawlers.video import BilibiliCrawler, DouyinCrawler
from crawlers.wechat import WechatCrawler
from crawlers.weibo import WeiboCrawler
from crawlers.xiaohongshu import XiaohongshuCrawler
from crawlers.youtube import YouTubeCrawler
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
    'youtube': YouTubeCrawler,
    'twitter': TwitterCrawler,
    # Cookie capture only: the panel can save a login session for this one while
    # its crawl is not built yet, so the canvas and the execute endpoint refuse
    # it (see crawlers/overseas.py) — and it stays out of the crawl matrix, which
    # is what the refusal is read from.
    'instagram': InstagramCrawler,
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


def get_crawler(
    platform: str,
    headless: bool = True,
    cookie_dir: str = None,
    for_login: bool = False,
    use_profile: bool = None,
    abort=None,
    refresh_cookies: bool = False,
):
    """Build the crawler for *platform*, in that platform's own browser profile.

    ``abort`` is the executor's "this run is over" check, forwarded to the
    profile wait: a stopped run must abandon the queue for a busy profile
    instead of buying a browser nobody asked for any more.

    ``use_profile`` decides *this browser* only: None follows the user's setting,
    False gives a throwaway profile. The choice travels with the run rather than
    being written to settings because a parallel canvas pays a different price for
    the same device than a single workflow does — one profile holds one browser, so
    two workflows crawling the same platform either take turns or give up the shared
    device. Only the user knows which of those they are buying this time, which is
    why the browser asks before starting (see ``_confirmProfileChoiceBeforeRun``).

    The cookie file is imported **once**, the first time a profile is used. After
    that the profile owns its session, because planting an old snapshot over a live
    one is how a rotating credential gets thrown away — measured on weibo, where a
    logged-in page load re-issues ``SUB``/``SUBP`` and the saved pair stops being
    accepted afterwards. A browser with no profile has nothing to overwrite, so it
    is planted from the saved file exactly as before the feature existed.

    ``refresh_cookies`` is the one exception, and it is only ever set by the user
    asking for it (``POST /api/cookies/refresh-profile``, the panel's
    「把 Cookie 更新进 Profile」 button): a re-taken session that cannot reach the
    profile it will be crawled from is a session the user paid to fetch for nothing.
    Nothing automatic opens this door, because *this function* runs at the start of
    every crawl.
    """
    cls = crawler_class(platform)
    if not cls:
        raise ValueError(f'Unknown platform: {platform}')
    profile = browser_profiles.profile_dir_for(platform, enabled=use_profile)
    saved = f'{cookie_dir}/{platform}_cookies.json' if cookie_dir else ''
    planting = bool(saved) and (not profile or not browser_profiles.is_used(platform) or refresh_cookies)
    crawler = cls(
        headless=headless,
        cookie_path=saved if planting else None,
        for_login=for_login,
        profile_dir=profile,
        abort=abort,
    )
    if profile:
        # The stamp is *which* file went in, so the panel can tell a saved-over cookie
        # from a profile that already holds the current one.
        browser_profiles.mark_used(platform, imported=planting, cookie_stamp=browser_profiles.file_stamp(saved))
    return crawler
