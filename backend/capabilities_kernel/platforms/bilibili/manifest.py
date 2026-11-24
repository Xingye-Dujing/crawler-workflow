"""哔哩哔哩：搜索视频、UP 主时间线、热门/排行与评论。"""

from capabilities_kernel.platform import platform_manifest
from capabilities_kernel.platforms._fields import author_mode, comment_mode, hot_mode, posts_mode

MANIFEST = platform_manifest(
    'bilibili',
    order=50,
    modes=(
        posts_mode(label_key='settings.collectVideos', collects='dom_read'),
        author_mode(placeholder='https://space.bilibili.com/<UID>', hint_key='settings.authorHintBili'),
        hot_mode(),
        comment_mode('bilibili', 'https://www.bilibili.com/video/BV...', replies=True),
    ),
    crawler='crawlers.platforms.bilibili.crawler:BilibiliCrawler',
    summary='哔哩哔哩：关键词搜索视频、UP 主的投稿、热门/排行榜、视频评论（含楼中楼）。',
    when_to_use='以视频为载体的舆情或创作者研究；评论来自 reply API，结构稳定。',
    when_not_to_use=('热门与排行是同一模式里的一个选择，不是两种采集。',),
    # Paged search reads one account's pages independently and comments come from a reply API that
    # tolerates two sessions crawling at once (measured), so parallel is the recommended shape.
    parallel_recommended=True,
)
