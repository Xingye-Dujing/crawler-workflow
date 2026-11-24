"""微博：带时间窗的关键词搜索、UID 时间线、热搜与评论采集。"""

from capabilities_kernel.platform import platform_manifest
from capabilities_kernel.platforms._fields import TIMES, author_mode, comment_mode, hot_mode, posts_mode

MANIFEST = platform_manifest(
    'weibo',
    order=20,
    modes=(
        posts_mode(*TIMES),
        author_mode(
            placeholder='https://weibo.com/u/<UID>',
            hint_key='settings.authorHintWeibo',
            # The author timeline is one in-page JSON endpoint read from the profile page: a visible
            # window shows the profile and then nothing.
            collects='fetch',
            note_key='settings.fetchQuietNote',
        ),
        # Measured: `ajax/side/hotSearch` answers ~52 rows with an exact integer heat, repeats
        # cleanly, and answers in all three session shapes — planted cookie, profile and no cookie.
        # One board, so no choice; and because an anonymous browser is served too, this is the one
        # crawl in the matrix that must not make the canvas ask for a login.
        hot_mode(board=False, session_required=False),
        comment_mode('weibo', 'https://weibo.com/...', replies=True),
    ),
    crawler='crawlers.platforms.weibo.crawler:WeiboCrawler',
    summary='微博：关键词搜索（可限定起止时间）、某个 UID 的微博、热搜榜、微博评论（含楼中楼）。',
    when_to_use='舆情事件研究的主力语料：搜索 + 时间窗，或按账号追踪。',
    when_not_to_use=('热搜是匿名接口，不需要登录；其他模式必须用能保持登录态的浏览器。',),
    # Measured: a logged-in page load re-issues SUB/SUBP, so a saved pair is stale next time and the
    # rotated pair replanted into a fresh browser is bounced to /newlogin. Only the user's own
    # browser keeps its jar.
    profile_recommended=True,
    # Parallel windows share one SUB: each serial walk pages to the end while parallel walks are
    # bounced to passport on deeper requests. 错峰 cannot fix this — the collision is per account.
    serial_only=True,
)
