"""微博: keyword search with a time window, a UID's timeline, 热搜, comment walks."""

from capabilities.fields import TIMES, author_mode, comment_mode, hot_mode, posts_mode
from capabilities.model import Capability

CAPABILITY = Capability(
    platform='weibo',
    # Measured: a logged-in page load re-issues SUB/SUBP, so the saved pair is
    # already stale the next time it is replayed, and the rotated pair replanted
    # into a fresh browser is bounced to /newlogin. Only a browser that keeps its
    # own jar stays in.
    profile_recommended=True,
    # Parallel windows share one SUB: each serial walk pages to the pager's own
    # end, while parallel walks are bounced to passport on their deeper requests
    # (docs/crawler_notes.md). 错峰 cannot fix this — the collision is per account.
    serial_only=True,
    modes=(
        posts_mode(*TIMES),
        author_mode(
            placeholder='https://weibo.com/u/<UID>',
            hint_key='settings.authorHintWeibo',
            # The author timeline is one in-page JSON endpoint read from the
            # profile page: a visible window shows the profile and then nothing.
            collects='fetch',
            note_key='settings.fetchQuietNote',
        ),
        # Measured: `ajax/side/hotSearch` answers ~52 rows with an exact integer
        # heat (`num`), repeats cleanly, and answers in all three session shapes —
        # planted cookie, profile and no cookie at all. One board, so no choice;
        # and because an anonymous browser is served too, this is the one crawl in
        # the matrix that must not make the canvas ask for a login.
        hot_mode(board=False, session_required=False),
        comment_mode('weibo', 'https://weibo.com/...'),
    ),
)
