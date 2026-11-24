"""The shared vocabulary of the crawl matrix: field atoms and mode factories.

One ``Field`` per input a crawl can ask for — declared once, composed by each mode — so "which box
does this crawl show" has a single answer. The factories build the four shapes every platform reuses
(search posts, a creator's timeline, the site's own board, a comment walk) and take only the
platform's measured differences as arguments.

This lives in the kernel because each platform's manifest imports it, and a manifest may import only
the standard library and the kernel.
"""

from dataclasses import replace

from capabilities_kernel.platform import Field, Mode

# ─── The shared tail: how the rows leave the crawl ───────────────────────
# Every mode produces a table and every table can be streamed to numbered part files while the run
# is still going. Declared once so the block is not copied into each mode's form.
#: What tool crawls a source node. ``selenium`` is this app's own browser; ``catbus`` is an external
#: adapter whose rows arrive through a subprocess. The two pay for different logins, key different
#: ledger rows and resume differently, so the choice is part of a node's identity.
BACKEND_SELENIUM = 'selenium'
BACKEND_CATBUS = 'catbus'
BACKENDS = (BACKEND_SELENIUM, BACKEND_CATBUS)

FILE_FIELDS = (
    Field(
        key='part_size',
        control='number',
        label_key='settings.partSize',
        default=0,
        hint_key='settings.sourcePartSizeHint',
        minimum=0,
        coerce='number',
    ),
    Field(
        key='format',
        control='select',
        label_key='settings.format',
        name_key='field.format',
        default='csv',
        options=(('csv', 'format.csv'), ('json', 'format.json')),
    ),
    Field(key='keep_parts', control='checkbox', label_key='settings.keepParts', default=False, coerce='bool'),
    # Which RECORD wrote these shards, in their name, so a second pass over the same canvas does not
    # replace the first one's files. Executor-only like ``keep_parts``.
    Field(
        key='part_timestamp',
        control='checkbox',
        label_key='settings.partTimestamp',
        default=False,
        hint_key='settings.partTimestampHint',
        coerce='bool',
    ),
)

# ─── The fields themselves ──────────────────────────────────────────────
KEYWORD = Field(key='keyword', control='text', label_key='settings.keyword', name_key='field.keyword', required=True)
TARGET = Field(
    key='target_count',
    control='number',
    label_key='settings.targetCount',
    # 50 everywhere, not each crawler's own signature default (zhihu and bilibili say 200): this is
    # the figure the panel previews and the one an untouched node has always run with.
    default=50,
    minimum=1,
    coerce='number',
)
RECOLLECT = Field(
    key='recrawl',
    control='checkbox',
    label_key='settings.recrawl',
    default=False,
    hint_key='settings.recrawlHint',
    coerce='bool',
)
#: Which saved login (and therefore which browser device) a session crawl uses. Executor-only: it
#: never reaches the crawler method — the executor reads it to pick the cookie file and profile.
ACCOUNT = Field(
    key='account',
    control='select',
    label_key='field.account',
    name_key='field.account',
    default='default',
    options=(('default', 'cookies.accountDefault'),),
)
#: Which tool crawls this node, and which CatBus account it crawls as. Declared on the shared mode
#: builders like every other field, and filtered by ``GET /api/capabilities`` against what this
#: machine can actually run. Executor-only (see the registry's ``_NOT_ARGS``).
BACKEND_FIELDS = (
    Field(
        key='backend',
        control='select',
        label_key='field.backend',
        name_key='field.backend',
        default=BACKEND_SELENIUM,
        hint_key='settings.backendHint',
        options=((BACKEND_SELENIUM, 'settings.backendSelenium'), (BACKEND_CATBUS, 'settings.backendCatbus')),
    ),
    Field(
        key='catbus_account',
        control='text',
        label_key='field.catbusAccount',
        name_key='field.catbusAccount',
        default='',
        hint_key='settings.catbusAccountHint',
    ),
)
#: The name of the upstream table's column to read row by row as a link list mode's link field (see
#: ``Field.fed_by``). Free text for the same reason the process and tokenize panels type their column
#: names by hand. Executor-only, but it CHOOSES DATA, so it stays in the node fingerprint.
INPUT_COLUMN = Field(
    key='input_column',
    control='text',
    label_key='settings.inputColumn',
    hint_key='settings.inputColumnHint',
    default='',
)
TIMES = (
    Field(key='start_time', control='text', label_key='settings.startTime', placeholder='2026-01-01'),
    Field(key='end_time', control='text', label_key='settings.endTime', placeholder='2026-12-31'),
)
COMMENT_LIMIT = Field(
    key='comment_limit',
    control='number',
    label_key='settings.commentLimit',
    default=0,
    hint_key='settings.commentLimitHint',
    minimum=0,
    coerce='number',
)
#: Whether a comment walk also opens each comment's 楼中楼 (nested replies).
#:
#: A shared SWITCH, never a shared platform rule: which platforms really have replies to take is
#: decided by that platform's own manifest (``replies=True`` where its walk can file them). Offering
#: it where the table can never hold a reply would be a control that changes nothing. It chooses
#: DATA, so it stays in the node fingerprint (unlike `recrawl`/file switches).
INCLUDE_REPLIES = Field(
    key='include_replies',
    control='checkbox',
    label_key='settings.includeReplies',
    default=True,
    hint_key='settings.includeRepliesHint',
    coerce='bool',
)
#: A table-side range over 评论时间, run after the comments are crawled — deliberately NOT the crawl
#: node's ``start_time``/``end_time`` (which decide how far back to CRAWL).
COMMENT_TIMES = (
    Field(key='comment_start', control='text', label_key='settings.commentStart', placeholder='2026-01-01'),
    Field(
        key='comment_end',
        control='text',
        label_key='settings.commentEnd',
        placeholder='2026-12-31',
        hint_key='settings.commentTimeHint',
    ),
)
PER_ARTICLE = Field(
    key='per_article_file',
    control='checkbox',
    label_key='settings.perArticleFile',
    default=False,
    coerce='bool',
)
#: A creator's own posts: what the user types is an address, not a search term, so the field is its
#: own thing rather than a reuse of 关键词.
AUTHOR = Field(
    key='author',
    control='text',
    label_key='settings.author',
    name_key='field.author',
    required=True,
    hint_key='settings.authorHint',
    placeholder='@handle',
)
#: The per-row detail call, offered rather than assumed: on YouTube and X one extra request per row
#: is what buys 点赞数 and the exact publish time.
WITH_FACTS = Field(
    key='with_facts',
    control='checkbox',
    label_key='settings.withFacts',
    default=True,
    hint_key='settings.withFactsHint',
    coerce='bool',
)
#: The card's own 阅读全文 click. zhihu's search list carries an **excerpt** in the DOM (measured:
#: 35–109 characters while the same answer's page ran to 308), so a crawl that does not expand ships
#: a truncated 正文 column. Offered rather than forced because it costs one wait per row.
FULL_BODY = Field(
    key='full_body',
    control='checkbox',
    label_key='settings.fullBody',
    default=True,
    hint_key='settings.fullBodyHint',
    coerce='bool',
)

#: Which list of the moment to read. On bilibili the two boards answer the *same* item shape, so
#: this is one mode with a choice inside it; two modes would be two names for one crawl.
BOARD = Field(
    key='board',
    control='select',
    label_key='settings.hotBoard',
    name_key='field.board',
    default='popular',
    options=(('popular', 'settings.hotBoardPopular'), ('ranking', 'settings.hotBoardRanking')),
)


def hot_mode(
    *extra: Field,
    target: int = 50,
    collects: str = 'fetch',
    board: bool = True,
    session_required: bool = True,
) -> Mode:
    """The site's own hot list — not a keyword's result page.

    No required field: what a hot list is about is chosen by the site, so the only choices offered
    are how many rows and, where the site really publishes more than one list, which board.
    ``board=False`` is for a site with exactly one board — offering a choice there is a control that
    changes nothing.

    Default ``collects='fetch'``: measured on bilibili, weibo and zhihu, a board is one JSON answer
    read from inside a loaded page, which is the mode that shows nothing in a window.
    """
    return Mode(
        key='hot',
        label_key='settings.collectHot',
        handler='hot',
        fields=(
            replace(TARGET, default=target),
            *((BOARD,) if board else ()),
            *extra,
            # A board is chosen by the site, but reading it can still be logged in — only when it is
            # (measured: zhihu's hot list 401s anonymously) does the node get an account to pick.
            *BACKEND_FIELDS,
            *((ACCOUNT,) if session_required else ()),
            RECOLLECT,
        ),
        note_key='settings.fetchQuietNote' if collects == 'fetch' else '',
        collects=collects,
        needs_session=session_required,
    )


def comment_mode(platform: str, example: str, collects: str = 'fetch', replies: bool = False) -> Mode:
    """The 评论 form, which is the same on every platform except the link shape.

    The example URL is the only per-platform part besides the ownership rule, and both are data: the
    panel prints the example as the field's placeholder so a person sees one valid shape rather than
    three at once, and the engine refuses links that contradict the platform the node selected.
    ``collects`` is passed in per platform because the comment engine is where the platforms
    genuinely differ: weibo/bilibili/YouTube read a JSON answer, while zhihu/xiaohongshu have to be
    scrolled and douyin/X are answered a captcha headless.

    ``replies`` says this platform's comment table can hold 楼中楼 rows, so the form offers the
    爬楼中楼 switch. Each platform answers that from its own walk.
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
                label_key='settings.commentUrls',
                name_key='field.urls',
                required=True,
                coerce='urls',
                links_of=platform,
                placeholder=example,
                fed_by='input_column',
            ),
            INPUT_COLUMN,
            COMMENT_LIMIT,
            *((INCLUDE_REPLIES,) if replies else ()),
            *COMMENT_TIMES,
            PER_ARTICLE,
            # The comment walk keeps the same ledger a source crawl does, so the switch that releases
            # it belongs here too: a crawl that silently dedupes with no way back reads as "the site
            # has no more comments".
            *BACKEND_FIELDS,
            ACCOUNT,
            RECOLLECT,
        ),
        # Two comment notes, chosen by ``collects`` so the panel never claims a window that the
        # executor will not open.
        note_key='settings.commentHint' if collects != 'fetch' else 'settings.commentFetchHint',
        collects=collects,
    )


def posts_mode(
    *extra: Field,
    target: int = 50,
    label_key: str = 'settings.collectPosts',
    collects: str = 'dom_scroll',
    note_key: str = '',
) -> Mode:
    return Mode(
        key='posts',
        label_key=label_key,
        fields=(KEYWORD, replace(TARGET, default=target), *extra, *BACKEND_FIELDS, ACCOUNT, RECOLLECT),
        note_key=note_key,
        collects=collects,
    )


def author_mode(
    *extra: Field,
    target: int = 50,
    placeholder: str = '@handle',
    hint_key: str = 'settings.authorHint',
    collects: str = 'dom_scroll',
    note_key: str = '',
) -> Mode:
    """One creator's own posts — the same walk, addressed by author instead of by keyword.

    What an author is *spelled* by differs per site (X and YouTube take a handle, zhihu only has a
    ``/people/<id>`` token), and the panel's placeholder and hint are the user's only notice of that.
    """
    author = replace(AUTHOR, placeholder=placeholder, hint_key=hint_key)
    return Mode(
        key='author',
        label_key='settings.collectAuthor',
        handler='author',
        fields=(author, replace(TARGET, default=target), *extra, *BACKEND_FIELDS, ACCOUNT, RECOLLECT),
        note_key=note_key,
        collects=collects,
    )
