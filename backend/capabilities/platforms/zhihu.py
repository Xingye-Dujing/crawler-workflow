"""知乎: search, a creator's answers, the site's own board, and comment walks."""

from capabilities.fields import FULL_BODY, author_mode, comment_mode, hot_mode, posts_mode
from capabilities.model import Capability

#: How many rows zhihu's board really holds. Measured at 30 with ``limit=50``,
#: ``limit=100`` and ``offset=30`` all returning the SAME 30 (30/30 ids overlap) and
#: ``paging.next`` empty — so the target box is capped by the site, not by us, and the
#: handler says "the board holds 30" rather than looping or padding to a number the
#: site never offered.
ZHIHU_HOT_ROWS = 30

CAPABILITY = Capability(
    platform='zhihu',
    # Two sessions crawling zhihu at once have been watched to coexist (search pages
    # and either comment shape), so the advice panel calls parallel out by name
    # rather than leaving it as "not marked serial-only".
    parallel_recommended=True,
    modes=(
        posts_mode(FULL_BODY, collects='dom_scroll'),
        author_mode(
            placeholder='https://www.zhihu.com/people/<id>',
            hint_key='settings.authorHintZhihu',
            collects='dom_scroll',
        ),
        # Measured: `hot-lists/total` answers 30 rows with every field inline, in
        # both a visible and a headless window, but NOT anonymously (401), and it
        # ignores limit/offset/page/cursor — 30 is the whole board, so the target
        # box has a ceiling the handler states rather than loops against.
        hot_mode(target=ZHIHU_HOT_ROWS, board=False),
        comment_mode('zhihu', 'https://www.zhihu.com/question/...', collects='dom_scroll'),
    ),
)
