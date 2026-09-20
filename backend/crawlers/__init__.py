from crawlers.wechat import WechatCrawler
from crawlers.weibo import WeiboCrawler
from crawlers.xiaohongshu import XiaohongshuCrawler
from crawlers.zhihu import ZhihuCrawler


def get_crawler(platform: str, headless: bool = True, cookie_dir: str = None):
    crawlers = {
        'zhihu': ZhihuCrawler,
        'weibo': WeiboCrawler,
        'xiaohongshu': XiaohongshuCrawler,
        'wechat': WechatCrawler,
    }
    cls = crawlers.get(platform)
    if not cls:
        raise ValueError(f'Unknown platform: {platform}')
    cookie_path = f'{cookie_dir}/{platform}_cookies.json' if cookie_dir else None
    return cls(headless=headless, cookie_path=cookie_path)
