"""抖音：创作者视频、热榜与评论采集（无头会被验证码挡住）。"""

from capabilities_kernel.platform import platform_manifest
from capabilities_kernel.platforms._fields import author_mode, comment_mode, hot_mode

MANIFEST = platform_manifest(
    'douyin',
    order=60,
    modes=(
        author_mode(
            placeholder='https://www.douyin.com/user/<sec_uid>',
            hint_key='settings.authorHintDouyin',
            collects='modal_per_row',
        ),
        # One answer is the whole board (measured 51 rows) and the site publishes this one list. It
        # needs a session: a cookie-planted throwaway browser was answered the captcha interstitial
        # while the tool's own profile read the board.
        hot_mode(board=False),
        comment_mode('douyin', 'https://www.douyin.com/video/...', collects='dom_scroll', replies=True),
    ),
    crawler='crawlers.platforms.douyin.crawler:DouyinCrawler',
    summary='抖音：某个创作者的主页视频、热榜、视频评论（含楼中楼）。',
    when_to_use='短视频平台的热点与评论研究。',
    when_not_to_use=('无头的投递浏览器经常被验证码中间页挡住；用你自己的浏览器配置更可靠。',),
    # Measured 2026-09-26: a cookie-planted throwaway browser was answered 验证码中间页 in 8.8 s,
    # while the same keyword crawl through the platform's own profile returned rows in 24.8 s. The
    # board reads the other way (profile answered the captcha, throwaway served it), which is why
    # this is a recommendation and never a coercion.
    profile_recommended=True,
)
