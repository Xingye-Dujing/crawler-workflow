"""知乎：搜索、创作者回答、站内热榜与评论采集。"""

from capabilities_kernel.platform import platform_manifest
from capabilities_kernel.platforms._fields import FULL_BODY, author_mode, comment_mode, hot_mode, posts_mode

#: How many rows zhihu's board really holds. Measured at 30 with every limit/offset combination
#: returning the SAME 30 and ``paging.next`` empty — so the target box is capped by the site, not by
#: us, and the handler says "the board holds 30" rather than looping or padding.
ZHIHU_HOT_ROWS = 30

MANIFEST = platform_manifest(
    'zhihu',
    order=10,
    modes=(
        posts_mode(FULL_BODY, collects='dom_scroll'),
        author_mode(
            placeholder='https://www.zhihu.com/people/<id>',
            hint_key='settings.authorHintZhihu',
            collects='dom_scroll',
        ),
        hot_mode(target=ZHIHU_HOT_ROWS, board=False),
        comment_mode('zhihu', 'https://www.zhihu.com/question/...', collects='dom_scroll', replies=True),
    ),
    crawler='crawlers.platforms.zhihu.crawler:ZhihuCrawler',
    summary='知乎：关键词搜索（可展开全文）、创作者回答、站内热榜、问题/回答评论（含楼中楼）。',
    when_to_use='要分析知乎的问答语料、某个作者的回答，或一个问题下的评论互动。',
    when_not_to_use=('热榜只有 30 条且需要登录；匿名浏览会被 401 拒绝。',),
    parallel_recommended=True,
)
