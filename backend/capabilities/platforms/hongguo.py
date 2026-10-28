"""红果短剧: four anonymous boards, and the Windows-only client comment harvest."""

from capabilities.fields import COMMENT_LIMIT, COMMENT_TIMES, INPUT_COLUMN, PER_ARTICLE, RECOLLECT, hot_mode
from capabilities.model import Capability, Field, Mode

#: 红果短剧's four boards. Same shape as bilibili's choice (one board, one row shape), so it
#: is the same field key and the same refusal path; the stored values are identifiers because
#: they are what a node holds, and the order here is the order the panel offers them (pinned
#: against ``crawlers.platforms.hongguo.crawler.BOARDS`` by ``tests/unit/crawlers/test_hongguo_crawler.py``).
HONGGUO_BOARD = Field(
    key='board',
    control='select',
    label_key='settings.hotBoard',
    name_key='field.board',
    default='hot_drama',
    options=(
        ('hot_drama', 'settings.hotBoardHongguoDrama'),
        ('hot_real_drama', 'settings.hotBoardHongguoReal'),
        ('hot_ai_drama', 'settings.hotBoardHongguoAi'),
        ('hot_comic_drama', 'settings.hotBoardHongguoComic'),
    ),
)

#: How many of a drama's EPISODES the 红果 comment harvest walks. Comments hang on one
#: episode each (a ``group_id`` per episode — measured in the player's own traffic), so
#: "all comments of a drama" is a per-episode walk, and the walk's depth is a cost
#: decision the user makes: each extra episode is one player episode-switch and its
#: comment page(s). The floor is 1 (one episode is a whole question); the ceiling is
#: generous because the site's own boards carry 200+ episode dramas nobody should be
#: forced to slice by hand.
HONGGUO_EPISODES = Field(
    key='episode_count',
    control='number',
    label_key='settings.hgEpisodeCount',
    default=10,
    minimum=1,
    maximum=200,
    hint_key='settings.hgEpisodeCountHint',
    coerce='number',
)
#: Whether each comment's children (``reply/list``) are fetched too. Default ON: the
#: drawer shows them inline and an analysis of 互动 without replies reads a half
#: conversation as a whole one. Turning it off halves the UIA walking, which is the
#: only reason to refuse.
HONGGUO_REPLIES = Field(
    key='include_replies',
    control='checkbox',
    label_key='settings.hgIncludeReplies',
    default=True,
    hint_key='settings.hgIncludeRepliesHint',
    coerce='bool',
)
#: How long one episode's comment page may take to ARRIVE before the walk names it.
#: A per-node data choice (how much patience this crawl buys), not a settings key.
HONGGUO_WAIT = Field(
    key='harvest_timeout',
    control='number',
    label_key='settings.hgHarvestTimeout',
    default=90,
    minimum=10,
    maximum=600,
    hint_key='settings.hgHarvestTimeoutHint',
    coerce='number',
)


def hongguo_comment_mode() -> Mode:
    """红果短剧's comment form: the shared shape minus the account, plus the walk's depth.

    It cannot reuse :func:`_comment_mode` for two measured reasons. There is no
    account to pick — the session is the desktop player's own login, which this tool
    neither holds nor asks about (``needs_session=False``, the same exemption the
    boards carry). And the crawl is a per-EPISODE walk (comments hang on ``group_id``s,
    one per episode), so the form must ask how deep to walk, whether replies ride
    along, and how long one episode's page may take — none of which exist on the
    link-in/rows-out browser platforms.
    """
    return Mode(
        key='comments',
        label_key='settings.collectComments',
        handler='comments',
        rows='comments',
        fields=(
            Field(
                key='urls',
                control='textarea',
                label_key='settings.hgCommentUrls',
                name_key='field.urls',
                required=True,
                coerce='urls',
                links_of='hongguo',
                # The walk happens INSIDE the client, and the client's own 排行榜 is the
                # only ranking it can answer to — so a drama title is a first-class input
                # here, not a malformed link.
                accepts_names=True,
                placeholder='https://hongguoduanju.com/detail?series_id=…（或每行一个剧名）',
                hint_key='settings.hgCommentUrlsHint',
                fed_by='input_column',
            ),
            INPUT_COLUMN,
            COMMENT_LIMIT,
            *COMMENT_TIMES,
            HONGGUO_EPISODES,
            HONGGUO_REPLIES,
            HONGGUO_WAIT,
            PER_ARTICLE,
            RECOLLECT,
        ),
        note_key='settings.hgCommentNote',
        collects='external_app',
        needs_session=False,
        # The one mode in the matrix that is not a browser crawl: it drives a desktop player behind our
        # own proxy, so a Linux server and a Mac have nothing to drive (``_ensure_stack`` refuses it by
        # name at run time, and this is what keeps the panel from offering it at all).
        requires='windows_desktop',
    )


CAPABILITY = Capability(
    platform='hongguo',
    modes=(
        # 红果短剧's four 热播 boards each come back 20 works a page, five pages, all four
        # in one measured shape — so this is one mode with a choice inside it, the same
        # shape bilibili's board takes. Anonymous on purpose: measured 2026-10, every
        # board is served to a fresh browser with no cookie, which is why the node
        # carries no account field and the pre-run gate asks it no session question.
        hot_mode(HONGGUO_BOARD, board=False, session_required=False),
        # Comments exist only in the app protocol; the crawl drives the desktop
        # player behind our own proxy and reads what it legitimately fetched
        # (docs/crawler_notes.md 红果短剧 for the whole measurement chain).
        hongguo_comment_mode(),
    ),
)
