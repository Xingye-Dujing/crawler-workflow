"""YouTube：搜索、频道视频与评论，每条可带详情字段。"""

from capabilities_kernel.platform import platform_manifest
from capabilities_kernel.platforms._fields import WITH_FACTS, author_mode, comment_mode, posts_mode

MANIFEST = platform_manifest(
    'youtube',
    order=90,
    modes=(
        posts_mode(WITH_FACTS, collects='fetch', note_key='settings.fetchQuietNote'),
        author_mode(WITH_FACTS, collects='fetch', note_key='settings.fetchQuietNote'),
        comment_mode('youtube', 'https://www.youtube.com/watch?v=...'),
    ),
    crawler='crawlers.platforms.youtube.crawler:YouTubeCrawler',
    summary='YouTube：关键词搜索、频道视频、视频评论；每条可额外请求点赞数与发布时间。',
    when_to_use='海外平台的视频语料与评论研究。',
    when_not_to_use=('国内网络通常无法直接访问；需要海外出口。',),
    region='overseas',
)
