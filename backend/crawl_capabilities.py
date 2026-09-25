"""What every platform can actually crawl, declared once.

Before this file the answer lived in four places that could each be edited
alone: ``app.py::_execute_source_node`` picked the crawler call with
``if platform == 'wechat'`` branches, ``engine/workflow.py::validate`` guessed
which parameter a node must carry with a second copy of the same branches,
``canvas.js`` seeded a node's defaults, and the browser's Data Source panel
(``openSettings``) rebuilt the form out of ``if (p.platform === '…')`` chains.
Every new platform or crawl mode meant touching all four in lockstep, and one
missed branch is a node that validates cleanly and then runs something else.

The matrix below is now the only place that says which modes exist, what each
one asks the user for, and what the crawler method is called with. The backend
dispatches through it, validation checks required fields through it, and
``GET /api/capabilities`` hands the identical description to the browser, which
renders the panel from it instead of knowing any platform by name.

It sits at the backend root, beside ``i18n.py``, for the same reason that file
does: ``engine/workflow.py`` reads it and must not import the crawler package
(the Selenium import is heavy and the dependency would run the wrong way), while
``app.py`` and the crawler modules need the very same description.

Deliberately absent: result column names. Those are a property of the page a
crawler read, so a copy here would be an unchecked claim — the live-site tests
derive columns from real crawls instead.
"""

from dataclasses import dataclass, replace

from utils.helpers import as_bool, split_urls


def _int(raw, default, minimum=None, maximum=None) -> int:
    """A number field, clamped.

    The panel lets a person type anything, and a negative row budget turns into
    an instant "exhausted" crawl that reports success, so the matrix owns the
    floor and the ceiling rather than trusting the widget.
    """
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default if isinstance(default, int) else 0
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


@dataclass(frozen=True)
class Field:
    """One input of the Data Source panel, and one argument of the crawl.

    ``label_key``/``hint_key`` name *frontend* catalogue entries, so the payload
    travels as keys and the browser answers in whatever language the canvas is
    using. ``coerce`` is the one thing the executor needs beyond the widget type:
    how to turn a stored parameter into the argument the crawler expects.
    """

    key: str
    control: str  # text | textarea | number | checkbox | select
    label_key: str
    default: object = ''
    hint_key: str = ''
    options: tuple = ()  # ((value, label_key), …), for control='select'
    minimum: int | None = None
    maximum: int | None = None
    required: bool = False
    coerce: str = 'text'  # text | number | bool | urls
    links_of: str = ''  # set → every URL has to belong to that platform
    placeholder: str = ''
    #: The *backend* catalogue key naming this field. The console refuses a run
    #: in the run's own language, and the panel's label keys live in app.js, so
    #: a required-field message needs its own word for 'keyword' / 'article
    #: URLs' — one per language, next to every other console sentence.
    name_key: str = ''

    def is_link_list(self) -> bool:
        return self.coerce == 'urls'

    def value_from(self, params: dict):
        """The stored parameter, coerced.

        A missing key falls back to the declared default rather than to None:
        the crawler's own signature default is a second opinion on the same
        number and the parity test keeps them equal, so a node that never
        opened its panel runs with exactly the figures its panel showed.
        """
        raw = params.get(self.key)
        if raw is None or (self.coerce != 'text' and str(raw).strip() == ''):
            return self.default
        if self.coerce == 'number':
            return _int(raw, self.default, self.minimum, self.maximum)
        if self.coerce == 'bool':
            # NOT ``bool(raw)``: an unticked box can be stored as the text 'false'
            # (``renderParamCheckbox`` wrote exactly that until it started writing
            # ``this.checked``, and a hand-written or imported workflow still holds
            # either spelling), and ``bool('false')`` is True — which read "do not
            # keep the part files" as "keep them", and "do not re-crawl" as
            # "re-crawl everything this node already paid for".
            return as_bool(raw, bool(self.default))
        if self.coerce == 'urls':
            return split_urls(raw)
        return str(raw).strip()


@dataclass(frozen=True)
class Mode:
    """One way of using a platform: an entry of the 采集模式 select and its form.

    ``handler`` names what the executor calls. ``'search'`` (and any other
    crawler method) is dispatched on the platform's crawler with the coerced
    fields; ``'comments'`` routes to the shared comment engine, which reads the
    same field names off the node and is why the two look-alike forms exist.

    ``collects`` is what the mode actually DOES on screen, and it is the only
    answer to "does a visible window show anything?": ``'fetch'`` loads a page and
    then reads JSON from inside it (nothing moves afterwards — measured 2026-09-25:
    the weibo and bilibili comment walks answer a HEADLESS browser with the same
    rows the window sees), ``'dom_read'`` reads a rendered page without scrolling,
    ``'dom_scroll'`` scrolls a feed that visibly moves, and ``'page_per_row'``
    opens one page per row. The panel's note and the comment engine's window
    decision read this field instead of each holding its own opinion — which is
    what the AGENTS rule 「a visible window must be doing something visible」 needs
    to be code rather than prose.
    """

    key: str
    label_key: str
    handler: str = 'search'
    fields: tuple = ()
    #: What a row is. Only wording needs it, but wording is what the user reads.
    rows: str = 'posts'
    note_key: str = ''  # a line the panel must show under this mode
    action_key: str = ''  # label of the optional button beside that line
    action_js: str = ''  # the browser function that button calls
    collects: str = 'dom_scroll'
    #: Whether this mode's crawl needs a logged-in session at all. The pre-run cookie
    #: probe works per PLATFORM, so without this field a mode that answers an anonymous
    #: browser (measured: weibo's ``ajax/side/hotSearch`` gives the same board with no
    #: cookie) is refused by a gate that was never about it. Default True: nearly every
    #: crawl here is a session crawl, and the exceptions are named by measurement.
    needs_session: bool = True


@dataclass(frozen=True)
class Capability:
    """A platform and everything it can be asked to collect."""

    platform: str
    modes: tuple
    #: Running in a throwaway browser is measurably punished on this platform — its
    #: session rotates or its risk control re-walls a replayed snapshot within
    #: minutes, while the user's own browser keeps working. The panel and the pre-run
    #: dialog read this; it is never a refusal, only a recommendation with evidence.
    profile_recommended: bool = False
    #: Which network this site answers from. Not decoration: with a VPN up, douyin
    #: answers 502 and refuses the crawl (measured by the user), and from inside China
    #: x.com is simply unreachable — so one canvas holding both regions cannot be run
    #: from either side, which is what the pre-run dialog warns about and what splits
    #: the live tier into ``live_cn`` and ``live_os``. The only answer to the question:
    #: the payload carries it to the browser, and the test tier reads it back off this
    #: module, so neither can hold a copy that drifts.
    region: str = 'cn'
    #: Crawls of this platform take turns **even when the user has 错峰 on**: one
    #: account paging two sessions at once is answered by the login wall — measured
    #: on weibo, where serial walks reach page 50 while parallel walks are bounced
    #: on their deeper requests (``docs/crawler_notes.md`` 2026-09-25). This is a
    #: property of the site, not a preference: the gate forces 真排队 for such a
    #: platform, and the pre-run dialog says so before the canvas pays for it.
    serial_only: bool = False


# ─── The shared tail: how the rows leave the crawl ───────────────────────
# Every mode produces a table and every table can be streamed to numbered part
# files while the run is still going. Declared once so the block is not copied
# into each mode's form, where one copy always falls behind.
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
)

# ─── The fields themselves ──────────────────────────────────────────────
_KEYWORD = Field(key='keyword', control='text', label_key='settings.keyword', name_key='field.keyword', required=True)
_TARGET = Field(
    key='target_count',
    control='number',
    label_key='settings.targetCount',
    # 50 everywhere, not each crawler's own signature default (zhihu and bilibili
    # say 200): this is the figure the panel previews and the one an untouched
    # node has always run with. A signature default now only reaches callers that
    # use a crawler directly — the live tests and the standalone scripts.
    default=50,
    minimum=1,
    coerce='number',
)
_RECOLLECT = Field(
    key='recrawl',
    control='checkbox',
    label_key='settings.recrawl',
    default=False,
    hint_key='settings.recrawlHint',
    coerce='bool',
)
_TIMES = (
    Field(key='start_time', control='text', label_key='settings.startTime', placeholder='2026-01-01'),
    Field(key='end_time', control='text', label_key='settings.endTime', placeholder='2026-12-31'),
)
_COMMENT_LIMIT = Field(
    key='comment_limit',
    control='number',
    label_key='settings.commentLimit',
    default=0,
    hint_key='settings.commentLimitHint',
    minimum=0,
    coerce='number',
)
_PER_ARTICLE = Field(
    key='per_article_file',
    control='checkbox',
    label_key='settings.perArticleFile',
    default=False,
    coerce='bool',
)
#: A creator's own posts: what the user types is an address, not a search term,
#: so the field is its own thing rather than a reuse of 关键词 (a keyword and a
#: handle that happen to match are different questions, and the panel must not
#: let one look like the other).
_AUTHOR = Field(
    key='author',
    control='text',
    label_key='settings.author',
    name_key='field.author',
    required=True,
    hint_key='settings.authorHint',
    placeholder='@handle',
)
#: The per-row detail call, offered rather than assumed: on YouTube and X one
#: extra request per row is what buys 点赞数 and the exact publish time, and a
#: user who only wants links and text can refuse to pay it.
_WITH_FACTS = Field(
    key='with_facts',
    control='checkbox',
    label_key='settings.withFacts',
    default=True,
    hint_key='settings.withFactsHint',
    coerce='bool',
)
#: The card's own 阅读全文 click. Not a nicety: zhihu's search list carries an **excerpt**
#: in the DOM (measured: 35–109 characters in a plain inline span, no CSS clamp, while the
#: same answer's page ran to 308), so a crawl that does not expand ships a truncated 正文
#: column and there is no way to recover the text from what was stored. Offered rather than
#: forced because it costs one wait per row and only reaches 回答 cards — clicking a column
#: card's control navigates away and detaches every remaining handle.
_FULL_BODY = Field(
    key='full_body',
    control='checkbox',
    label_key='settings.fullBody',
    default=True,
    hint_key='settings.fullBodyHint',
    coerce='bool',
)


#: Which list of the moment to read. On bilibili the two boards answer the *same*
#: item shape, so this is one mode with a choice inside it; two modes would be two
#: names for one crawl and two entries in the panel for one thing.
_BOARD = Field(
    key='board',
    control='select',
    label_key='settings.hotBoard',
    name_key='field.board',
    default='popular',
    options=(('popular', 'settings.hotBoardPopular'), ('ranking', 'settings.hotBoardRanking')),
)

#: How many rows zhihu's board really holds. Measured at 30 with ``limit=50``,
#: ``limit=100`` and ``offset=30`` all returning the SAME 30 (30/30 ids overlap) and
#: ``paging.next`` empty — so the target box is capped by the site, not by us, and the
#: handler says "the board holds 30" rather than looping or padding to a number the
#: site never offered.
_ZHIHU_HOT_ROWS = 30


def _hot_mode(
    *extra: Field,
    target: int = 50,
    collects: str = 'fetch',
    board: bool = True,
    needs_session: bool = True,
) -> Mode:
    """The site's own hot list — not a keyword's result page.

    No required field: what a hot list is about is chosen by the site, so the only
    choices offered are how many rows and, where the site really publishes more than
    one list, which board. ``board=False`` is for a site with exactly one board —
    offering a choice there is a control that changes nothing, and the handler would
    have to keep a parameter it cannot honour.

    Default ``collects='fetch'``: measured on bilibili, weibo and zhihu, a board is one
    JSON answer read from inside a loaded page, which is the mode that shows nothing in
    a window.
    """
    return Mode(
        key='hot',
        label_key='settings.collectHot',
        handler='hot',
        fields=(replace(_TARGET, default=target), *((_BOARD,) if board else ()), *extra, _RECOLLECT),
        # A board opens a page once then reads JSON: a visible window only sits there.
        # The note says so (and that 无头 saves nothing to watch) instead of the panel
        # holding its own opinion about which modes move the screen.
        note_key='settings.fetchQuietNote' if collects == 'fetch' else '',
        collects=collects,
        needs_session=needs_session,
    )


def _comment_mode(platform: str, example: str, collects: str = 'fetch') -> Mode:
    """The 评论 form, which is the same on every platform except the link shape.

    The example URL is the only per-platform part besides the ownership rule, and
    both are data: the panel prints the example as the field's placeholder so a
    person sees one valid shape rather than three at once, and the engine refuses
    links that contradict the platform the node selected. ``collects`` is passed in
    per platform because the comment engine is where the platforms genuinely differ:
    weibo/bilibili/YouTube read a JSON answer (nothing on screen moves), while
    zhihu/xiaohongshu have to be scrolled and douyin/X are answered a captcha headless.
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
            ),
            _COMMENT_LIMIT,
            _PER_ARTICLE,
        ),
        # Two comment notes, chosen by ``collects`` so the panel never claims a window
        # that the executor will not open. The scrolled/captcha platforms
        # (``commentHint``) genuinely drive a visible browser even under 无头 — zhihu
        # refuses a headless content page, douyin/X answer a captcha — and that note
        # also carries the comment-specific 分片文件 sentence. The fetch platforms
        # (``commentFetchHint``) honour 无头 (measured 2026-09-25: weibo/bilibili
        # comment walks answer a headless browser with the same rows), so their note
        # must NOT claim a window; it keeps the same 分片文件 sentence.
        note_key='settings.commentHint' if collects != 'fetch' else 'settings.commentFetchHint',
        collects=collects,
    )


def _posts_mode(*extra: Field, target: int = 50, collects: str = 'dom_scroll', note_key: str = '') -> Mode:
    return Mode(
        key='posts',
        label_key='settings.collectPosts',
        fields=(_KEYWORD, replace(_TARGET, default=target), *extra, _RECOLLECT),
        note_key=note_key,
        collects=collects,
    )


def _author_mode(
    *extra: Field,
    target: int = 50,
    placeholder: str = '@handle',
    hint_key: str = 'settings.authorHint',
    collects: str = 'dom_scroll',
    note_key: str = '',
) -> Mode:
    """One creator's own posts — the same walk, addressed by author instead of by
    keyword, so it needs its own entry rather than a wider keyword box.

    What an author is *spelled* by differs per site (X and YouTube take a handle,
    zhihu only has a ``/people/<id>`` token), and the panel's placeholder and hint
    are the user's only notice of that, so both are per-entry rather than one
    global string.
    """
    author = replace(_AUTHOR, placeholder=placeholder, hint_key=hint_key)
    return Mode(
        key='author',
        label_key='settings.collectAuthor',
        handler='author',
        fields=(author, replace(_TARGET, default=target), *extra, _RECOLLECT),
        note_key=note_key,
        collects=collects,
    )


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        platform='zhihu',
        modes=(
            _posts_mode(_FULL_BODY, collects='dom_scroll'),
            _author_mode(
                placeholder='https://www.zhihu.com/people/<id>',
                hint_key='settings.authorHintZhihu',
                collects='dom_scroll',
            ),
            # Measured: `hot-lists/total` answers 30 rows with every field inline, in
            # both a visible and a headless window, but NOT anonymously (401), and it
            # ignores limit/offset/page/cursor — 30 is the whole board, so the target
            # box has a ceiling the handler states rather than loops against.
            _hot_mode(target=_ZHIHU_HOT_ROWS, board=False),
            _comment_mode('zhihu', 'https://www.zhihu.com/question/...', collects='dom_scroll'),
        ),
    ),
    Capability(
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
            _posts_mode(*_TIMES),
            _author_mode(
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
            _hot_mode(board=False, needs_session=False),
            _comment_mode('weibo', 'https://weibo.com/...'),
        ),
    ),
    Capability(
        platform='xiaohongshu',
        # Measured twice in one hour: search answered fine, then the same saved
        # session was redirected to the login page minutes later while the user's own
        # browser was still logged in and working.
        profile_recommended=True,
        modes=(
            _posts_mode(
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
            _comment_mode('xiaohongshu', 'https://www.xiaohongshu.com/explore/...', collects='dom_scroll'),
        ),
    ),
    Capability(
        platform='wechat',
        modes=(
            Mode(
                key='posts',
                label_key='settings.articleUrls',
                fields=(
                    Field(
                        key='urls',
                        control='textarea',
                        label_key='settings.urls',
                        name_key='field.urls',
                        required=True,
                        hint_key='settings.urlsHint',
                        coerce='urls',
                        placeholder='https://mp.weixin.qq.com/s/...',
                    ),
                ),
                note_key='settings.wechatLimitsNote',
                action_key='settings.wechatLimitsBtn',
                action_js='explainWechatLimits',
                collects='page_per_row',
            ),
        ),
    ),
    Capability(
        platform='bilibili',
        modes=(
            _posts_mode(collects='dom_read'),
            _author_mode(
                placeholder='https://space.bilibili.com/<UID>',
                hint_key='settings.authorHintBili',
            ),
            _hot_mode(),
            _comment_mode('bilibili', 'https://www.bilibili.com/video/BV...'),
        ),
    ),
    Capability(
        platform='douyin',
        modes=(
            _posts_mode(collects='page_per_row'),
            _author_mode(
                placeholder='https://www.douyin.com/user/<sec_uid>',
                hint_key='settings.authorHintDouyin',
                collects='page_per_row',
            ),
            _comment_mode('douyin', 'https://www.douyin.com/video/...', collects='dom_scroll'),
        ),
    ),
    # The overseas three come last on purpose: they are the newest entries and the
    # panel's order is this tuple's order, so the platforms a Chinese-language
    # user reaches for first stay at the top of the list.
    Capability(
        platform='youtube',
        region='overseas',
        modes=(
            _posts_mode(_WITH_FACTS, collects='fetch', note_key='settings.fetchQuietNote'),
            _author_mode(_WITH_FACTS, collects='fetch', note_key='settings.fetchQuietNote'),
            _comment_mode('youtube', 'https://www.youtube.com/watch?v=...'),
        ),
    ),
    Capability(
        platform='twitter',
        region='overseas',
        modes=(
            _posts_mode(),
            _author_mode(),
            _comment_mode('twitter', 'https://x.com/.../status/...', collects='dom_scroll'),
        ),
    ),
)


# ─── Queries used by the backend, the API and the panel ──────────────────

_BY_PLATFORM = {c.platform: c for c in CAPABILITIES}

#: The stored key that selects a mode. The canvas has written it as ``collect``
#: since the first release, and a saved workflow's mode is part of what its run
#: record and resume cursor refer to, so the name stays; ``mode`` is accepted
#: for a hand-written JSON that says the same thing in the obvious way.
MODE_KEY = 'collect'


def platform_ids() -> tuple[str, ...]:
    """Every platform the matrix describes, in panel order."""
    return tuple(_BY_PLATFORM)


def has_platform(platform: str) -> bool:
    return str(platform or '') in _BY_PLATFORM


def capability(platform: str) -> Capability | None:
    return _BY_PLATFORM.get(str(platform or ''))


#: The two egress networks a crawl can be run from. Names, not booleans: 「国内」 and
#: 「海外」 are the user's own words for them, and a platform is in exactly one.
REGIONS = ('cn', 'overseas')


def region_of(platform: str) -> str:
    """Which network *platform* answers from, or '' when nothing crawls it.

    The matrix is the only answer to this: the pre-run dialog, the live tier's
    ``live_cn`` / ``live_os`` split and the panel all read it here, because a second
    list of "which platforms are overseas" is exactly the copy that falls behind when
    a platform is added.
    """
    cap = capability(platform)
    return cap.region if cap else ''


def serial_only_of(platform: str) -> bool:
    """Whether *platform* must take turns whatever the 排队/错峰 setting says.

    Same rule as ``region_of``: one answer lives in the matrix, and the gate, the
    pre-run dialog and the tests all read it here rather than keeping their own
    list of the platform's name.
    """
    cap = capability(platform)
    return bool(cap and cap.serial_only)


#: The vocabulary of :attr:`Mode.collects`. One of these four on every mode, checked
#: by the tests so a mode cannot declare a word the panel and executor do not know.
COLLECT_KINDS = ('fetch', 'dom_read', 'dom_scroll', 'page_per_row')


def shows_nothing(platform: str, mode_key: str) -> bool:
    """Whether a visible window of this crawl would show nothing worth watching.

    True for the ``'fetch'`` kinds — a page loads and every row after that is read
    from inside it, so a window just sits on the homepage. The comment executor and
    the panel's note ask this rather than each holding their own opinion about which
    platforms need a screen; ``never_headless`` (the two sites that answer a headless
    browser with a captcha) is a separate, still-authoritative gate the executor
    keeps, so a fetch mode on douyin/X is never made headless by this answer.
    """
    mode = mode_for(platform, mode_key)
    return bool(mode and mode.collects == 'fetch')


def needs_session(platform: str, mode_key: str) -> bool:
    """Whether this crawl is a session crawl — the question the cookie gate asks.

    The gate probes per platform, so a canvas whose only node is weibo's 热搜 board
    would be refused for lacking a cookie the measured endpoint never wanted. Unknown
    platform or mode answers True: no answer is not evidence that a crawl is anonymous,
    and the gate staying on for something it cannot judge is the safe direction.
    """
    mode = mode_for(platform, mode_key)
    return True if mode is None else bool(mode.needs_session)


def split_regions(platforms) -> dict:
    """``{'cn': [...], 'overseas': [...]}`` for the platforms of one canvas.

    Order is the canvas's own, and a platform the matrix does not know is left out
    rather than guessed at: the caller is warning about a crawl, so an invented
    region is worse than a silent omission.
    """
    split = {region: [] for region in REGIONS}
    for platform in platforms or []:
        region = region_of(platform)
        if region in split and platform not in split[region]:
            split[region].append(platform)
    return split


def modes_for(platform: str) -> tuple[Mode, ...]:
    cap = capability(platform)
    return () if cap is None else cap.modes


def mode_keys_for(platform: str) -> tuple[str, ...]:
    return tuple(m.key for m in modes_for(platform))


def mode_for(platform: str, mode_key: str) -> Mode | None:
    """The declared mode, or the platform's first one for an unknown key.

    Falling back is what keeps an old canvas (which never heard of 评论采集 or
    renamed keys) opening a panel that matches what the executor will do,
    instead of refusing to render.
    """
    modes = modes_for(platform)
    if not modes:
        return None
    wanted = str(mode_key or '').strip()
    for mode in modes:
        if mode.key == wanted:
            return mode
    return modes[0]


def requested_mode_key(node: dict) -> str:
    """The mode key a stored node *asks for*, before any fallback.

    :func:`mode_for` answers an unknown key with the platform's first mode on
    purpose, so a canvas saved before the key existed (or a WeChat node still
    carrying a stale ``collect='comments'``, which is the article crawl as far as
    that platform is concerned) still renders and runs. That is the wrong answer for
    validation wherever the platform *does* offer a choice: on a two-mode platform,
    substituting its first mode for a mode it never had either runs a different
    crawl than the one that was asked for or reports 「缺少关键词」 about a field the
    panel never showed the user.
    """
    node = node or {}
    params = node.get('params') or {}
    return str(params.get('mode') or params.get(MODE_KEY) or '').strip()


def mode_of_node(node: dict) -> Mode | None:
    """The mode a stored node asks for, read the way the executor reads it."""
    node = node or {}
    params = node.get('params') or {}
    platform = str(node.get('platform') or params.get('platform') or '')
    return mode_for(platform, requested_mode_key(node))


def fields_for(platform: str, mode_key: str, with_files: bool = True) -> tuple[Field, ...]:
    mode = mode_for(platform, mode_key)
    if mode is None:
        return ()
    return tuple(mode.fields) + (FILE_FIELDS if with_files else ())


def crawler_fields(mode: Mode) -> tuple[Field, ...]:
    """The fields the crawl method is actually called with.

    ``recrawl`` belongs to the run, not to the crawler: it releases the
    already-collected ledger before the crawl starts, so the executor reads it
    straight off the node. Declaring it in the matrix (so the panel shows it in
    the right place) while keeping it out of the call is why this exists.
    """
    return tuple(f for f in mode.fields if f.key not in _NOT_ARGS)


_NOT_ARGS = frozenset({'recrawl'})


def crawl_kwargs(mode: Mode, params: dict) -> dict:
    """Coerce the node's stored parameters into crawler arguments."""
    return {f.key: f.value_from(params) for f in crawler_fields(mode)}


def declared_defaults(platform: str) -> dict:
    """Every parameter the platform's modes mention, at its declared default.

    Two consumers, one source: the canvas seeds a new node from this, and the
    executor reads a node that never opened its panel as
    ``params.get(key, declared_default)`` — so a widget's preview and the run's
    figure cannot drift apart.
    """
    out: dict = {}
    for mode in modes_for(platform):
        for f in mode.fields + FILE_FIELDS:
            out.setdefault(f.key, f.default)
    return out


def required_missing(mode: Mode, params: dict) -> list[Field]:
    """Required fields the node leaves empty — the whole of source validation."""
    out = []
    for f in mode.fields:
        if not f.required:
            continue
        value = f.value_from(params)
        empty = not value if f.is_link_list() else not str(value or '').strip()
        if empty:
            out.append(f)
    return out


def unoffered_selections(mode: Mode, params: dict, with_files: bool = True) -> list[tuple[Field, str]]:
    """Select fields whose stored value names an option the matrix does not declare.

    A select is a choice from a fixed list, so a value off that list is not a variant
    of an answer — it is no answer at all. Every reader here treats "anything except
    the one value I special-case" as the default (`board`: only ``'ranking'`` is
    checked, so ``'Popular'``, ``'rank'`` or a typo walks 热门; `format`: only
    ``'json'`` is checked, so ``'Json'`` or ``'jsonl'`` writes CSV), which is how a
    hand-written or externally generated workflow silently crawls or saves something
    else. Refusing it by name is the same rule :func:`requested_mode_key` enforces for
    the mode selector, extended to the choices inside a mode.

    A blank is not a mistake but "never chose", which the declared default answers —
    so it is skipped, exactly as an empty mode key is. Case is deliberately **not**
    folded: an option value is a storage key, and the user has to see what they wrote
    rather than have a near miss guessed into a different crawl.
    """
    out: list[tuple[Field, str]] = []
    for field in list(mode.fields) + (list(FILE_FIELDS) if with_files else []):
        if field.control != 'select' or not field.options:
            continue
        raw = params.get(field.key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value or value in {stored for stored, _label in field.options}:
            continue
        out.append((field, value))
    return out


def link_fields(mode: Mode) -> list[Field]:
    """The link fields whose ownership validation can actually decide.

    ``links_of`` is filled from the comment router's domain table, so a mode
    without a comment adapter (WeChat's article list) declares no owner and is
    left to its own crawler, which names the article it could not read instead
    of a design-time rule guessing what an article is.
    """
    return [f for f in mode.fields if f.is_link_list() and f.links_of]


def as_dict() -> dict:
    """The whole matrix, ready for ``GET /api/capabilities``.

    Keys are camelCased because the browser reads them directly, and labels
    stay keys for the same reason: the payload has no language.
    """
    platforms = []
    for cap in CAPABILITIES:
        platforms.append(
            {
                'platform': cap.platform,
                'modes': [_mode_as_dict(m) for m in cap.modes],
                'profileRecommended': bool(cap.profile_recommended),
                'region': cap.region,
                'serialOnly': bool(cap.serial_only),
            }
        )
    return {'platforms': platforms, 'fileFields': [_field_as_dict(f) for f in FILE_FIELDS]}


def _mode_as_dict(mode: Mode) -> dict:
    return {
        'key': mode.key,
        'labelKey': mode.label_key,
        'handler': mode.handler,
        'rows': mode.rows,
        'noteKey': mode.note_key,
        'actionKey': mode.action_key,
        'actionJs': mode.action_js,
        'collects': mode.collects,
        'needsSession': bool(mode.needs_session),
        'fields': [_field_as_dict(f) for f in mode.fields],
    }


def _field_as_dict(f: Field) -> dict:
    return {
        'key': f.key,
        'control': f.control,
        'labelKey': f.label_key,
        'default': f.default,
        'hintKey': f.hint_key,
        'options': [{'value': v, 'labelKey': k} for v, k in f.options],
        'minimum': f.minimum,
        'maximum': f.maximum,
        'required': f.required,
        'coerce': f.coerce,
        'linksOf': f.links_of,
        'placeholder': f.placeholder,
    }
