"""小红书：搜索（带评论预览）与评论采集。"""

from capabilities_kernel.platform import Field, platform_manifest
from capabilities_kernel.platforms._fields import comment_mode, posts_mode

MANIFEST = platform_manifest(
    'xiaohongshu',
    order=30,
    modes=(
        posts_mode(
            Field(
                key='comment_preview',
                control='number',
                label_key='settings.commentPreview',
                default=5,
                hint_key='settings.commentPreviewHint',
                minimum=0,
                coerce='number',
            ),
            collects='dom_scroll',
        ),
        comment_mode('xiaohongshu', 'https://www.xiaohongshu.com/explore/...', collects='dom_scroll', replies=True),
    ),
    crawler='crawlers.platforms.xiaohongshu.crawler:XiaohongshuCrawler',
    summary='小红书：关键词搜索笔记（可带前 N 条评论预览），或对笔记链接采集评论。',
    when_to_use='消费决策/种草类语料，或某篇笔记下的评论互动。',
    when_not_to_use=('搜索结果页会滚动，无头模式更容易被重定向到登录页。',),
    # Measured twice in one hour: search answered fine, then the same saved session was redirected
    # to the login page minutes later while the user's own browser was still logged in.
    profile_recommended=True,
)
