"""X / Twitter：搜索、用户帖子与登录墙后的评论。"""

from capabilities_kernel.platform import platform_manifest
from capabilities_kernel.platforms._fields import author_mode, comment_mode, posts_mode

MANIFEST = platform_manifest(
    'twitter',
    order=100,
    modes=(
        posts_mode(),
        author_mode(),
        comment_mode('twitter', 'https://x.com/.../status/...', collects='dom_scroll'),
    ),
    crawler='crawlers.platforms.twitter.crawler:TwitterCrawler',
    summary='X / Twitter：关键词搜索、用户时间线、推文回复（需要登录）。',
    when_to_use='海外舆情、名人/机构账号的发言与回复。',
    when_not_to_use=('国内网络通常无法直接访问；评论需要登录会话。',),
    region='overseas',
)
