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

import re
from dataclasses import dataclass, replace

from core import machine
from core.refs import as_bool, split_urls

from i18n import t

#: A machine requirement a crawl mode can carry, by name. The token is deliberately not a sentence:
#: it goes to the browser, which says it in whichever language the canvas is reading
#: (``cap.requires.<token>``), and the server answers whether THIS machine meets it.
#:
#: ``windows_desktop`` is the one that exists because the app was written on Windows and deployed on a
#: Linux server: 红果评论 drives the desktop player through a proxy whose CA we install into the Windows
#: certificate store, so it needs a window, that store, and a machine nobody else is sharing.
REQUIREMENTS = ('windows_desktop',)

#: The words for each requirement, spelled out as literal catalogue keys (a computed ``f'cap.requires.{t}'``
# is how a refusal ends up printing its own key — the reachability scan can only ask about names it sees).
#: Public because the contract test walks it against :data:`REQUIREMENTS` and against the JS copy.
REQUIREMENT_LABELS = {'windows_desktop': 'cap.requiresWindowsDesktop'}


def requirement_met(token: str, system: str | None = None, cloud: bool | None = None) -> bool:
    """Whether this machine can run a mode that asks for ``token``.

    An unknown token answers YES: refusing a mode because a name was mis-typed would hide a working
    feature, and the mode's own executor still refuses by name when its real dependency is missing.
    """
    if token == 'windows_desktop':
        return machine.is_windows(system) and not (cloud_is() if cloud is None else cloud)
    return True


def cloud_is() -> bool:
    """The cloud switch, read late so an import of this matrix never drags ``config`` in."""
    from config import Config

    return bool(Config.CLOUD_MODE)


def machine_requirements(system: str | None = None, cloud: bool | None = None) -> dict:
    """Every requirement, answered for the machine running this server.

    One payload, one answer: the panel greys a mode out of it and the pre-run gate refuses from the same
    numbers, so the two cannot disagree about whether the user's click has any chance.
    """
    return {token: requirement_met(token, system, cloud) for token in REQUIREMENTS}


def requirement_label_key(token: str) -> str:
    """The catalogue key naming a requirement — a literal per token, never a computed one.

    Computed keys are how a refusal prints ``cap.requires.windows``: the reachability scan only asks
    about keys it can see spelled out, so the spelling lives here and the test walks
    :data:`REQUIREMENTS` against it.
    """
    return REQUIREMENT_LABELS.get(token, '')


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
    #: Set → this list field can be **fed from an upstream table column** instead
    #: of the pasted value: its value names a sibling parameter on the same mode
    #: that carries the column name (``input_column``). One declaration drives
    #: panel (disable the textarea), validation (waive the pasted requiredness)
    #: and executor (inject the column's values) — the matrix stays the only
    #: answer to "which modes accept a feed", so no file can hold its own opinion.
    #: A mode is feedable iff one of its fields sets this.
    fed_by: str = ''

    #: Set → a line of this link list may also be a plain NAME. Declared for 红果's
    #: comment form, whose crawl runs inside the desktop client: the web board and the
    #: client's 排行榜 are two different rankings, so the input the client can actually
    #: answer is the drama's title, and a comment router that sorts every line by DOMAIN
    #: would otherwise throw those names away as "unsupported links". Panel, validation
    #: and executor all read this one declaration.
    accepts_names: bool = False

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
    ``'dom_scroll'`` scrolls a feed that visibly moves, ``'modal_per_row'`` scrolls a
    grid and opens an in-page overlay on each row (a visible move per row, but NO
    navigation — the document is the one already loaded), and ``'page_per_row'``
    opens one whole page per row. The panel's note and the comment engine's window
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
    #: A machine requirement, by name, from :data:`REQUIREMENTS` — '' when any machine that runs the
    #: server can run this mode. This is not a warning: 红果评论 drives a desktop player through a proxy
    #: we install as a system certificate authority, so on a Linux server, on a Mac, and in cloud mode
    #: there is nothing to drive. ``GET /api/capabilities`` answers whether THIS machine satisfies it,
    #: and the panel refuses to offer a mode it knows cannot run — a user should not pay a node start
    #: for an answer the server already had at page load.
    requires: str = ''


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
    #: Which side of the world this site's content and account live on: ``cn`` or
    #: ``overseas``. Not decoration, and not a reachability claim — from inside China
    #: x.com and YouTube do not load at all, so a canvas holding one needs the VPN and the
    #: crawl can be started without it and quietly return nothing. Measured 2026-09-26 the
    #: other way round as well: a Chinese platform crawled normally from an overseas exit,
    #: which is why the interface asks about the VPN once (``ask_overseas_network``) instead
    #: of warning about "mixed" canvases, and why the live tier splits into ``live_cn`` and
    #: ``live_os`` while nothing splits a user's run. The only answer to the question:
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
    #: The opposite advice to ``serial_only``, and derived from its own measurements,
    #: not from the absence of a warning: on these platforms two sessions crawling at
    #: once have been watched to coexist (zhihu search/comments, bilibili pages) while a
    #: single account stays inside the site's tolerance, so the 建议弹窗 can say "并行推荐"
    #: with evidence rather than leaving the user to infer it from what is NOT serial-only.
    parallel_recommended: bool = False


# ─── The shared tail: how the rows leave the crawl ───────────────────────
# Every mode produces a table and every table can be streamed to numbered part
# files while the run is still going. Declared once so the block is not copied
# into each mode's form, where one copy always falls behind.
#: What tool crawls a source node. ``selenium`` is this app's own browser; ``catbus`` is an
# external adapter whose rows arrive through a subprocess. The two pay for different logins, key
# different ledger rows and resume differently, so the choice is part of a node's identity — and it
# is answered here once, because a second opinion in ``app.py`` or in JS is how a node crawls as one
# thing while its rows are filed as another.
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
    # Which RECORD wrote these shards, in their name, so a second pass over the same
    # canvas does not replace the first one's files. Executor-only like ``keep_parts``:
    # it decides a filename, never what the crawler collects.
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
#: Which saved login (and therefore which browser device) a session crawl uses. Like
#: ``recrawl`` it is an executor-only field: it never reaches the crawler method — the
#: executor reads it to pick the cookie file and the profile directory (see
#: ``get_crawler(account=…)``) — but unlike ``recrawl`` it DOES choose data, so it is
#: deliberately not volatile in the run fingerprint. Declared with only the blank
#: option so the select is never empty; ``GET /api/capabilities`` appends the accounts
#: that really have a saved file (in creation order) and moves ``default`` onto the
#: first of them, which is why a node added today logs in as the login that exists
#: rather than as an empty string. Whether the chosen account can actually carry a
#: session is refused at validation — see :func:`unoffered_selections`' note on the
#: account field.
_ACCOUNT = Field(
    key='account',
    control='select',
    label_key='field.account',
    name_key='field.account',
    # The default login has a name like every other account, so the field declares it rather
    # than declaring "nothing chosen": a select whose first row is a blank is a select whose
    # stored value is nothing, and an empty account on a node used to be indistinguishable
    # from a node that never had the field. Both spellings mean this account — the fold is in
    # ``CookieManager.key``, so a workflow saved before the name still runs unchanged.
    default='default',
    options=(('default', 'cookies.accountDefault'),),
)
#: Which tool crawls this node, and which CatBus account it crawls as. Declared on the shared mode
#: builders like every other field, and **filtered by** ``GET /api/capabilities`` against what this
#: machine can actually run: a box without Node, or a 平台 × 模式 the adapter's own manifest does not
#: offer, gets the field back out of its payload — the entry disappears rather than refusing after
#: the user paid for a node start. Executor-only (see ``_NOT_ARGS``): this selects the session, never
#: an argument of the crawl.
#:
#: ``catbus_account`` is a *text* field, not a select, because the candidate list lives in CatBus'
#: own account directory (``~/.catbus/``) and this app neither reads nor writes it. Blank means
#: "whatever account CatBus currently has selected", which is the honest default rather than a guess
#: at a name.
_BACKEND_FIELDS = (
    Field(
        key='backend',
        control='select',
        label_key='field.backend',
        name_key='field.backend',
        default=BACKEND_SELENIUM,
        hint_key='settings.backendHint',
        # ``settings.*`` rather than a new namespace: the payload-shape test holds every select to
        # labels the browser's own catalogue can answer, and a prefix it has never seen is a word the
        # panel would print as its own key.
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
#: The name of the upstream table's column to read row by row as a link list mode's
#: link field (see ``Field.fed_by``). Free text for the same reason the process and
#: tokenize panels type their column names by hand: the browser holds no parent
#: table schema, so any dropdown would be a second opinion the frontend must not
#: have. Executor-only (it is in ``_NOT_ARGS`` — the crawl method still receives its
#: own field), but it CHOOSES DATA, so unlike ``recrawl`` it stays in the node
#: fingerprint: renaming the fed column is a different input set, not a relabel.
_INPUT_COLUMN = Field(
    key='input_column',
    control='text',
    label_key='settings.inputColumn',
    hint_key='settings.inputColumnHint',
    default='',
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
#: A table-side range over 评论时间, run by ``_filter_comments_by_time`` after the
#: comments are crawled — deliberately NOT the crawl node's ``start_time``/``end_time``
#: (which decide how far back to CRAWL). The comment node reads ``comment_start`` /
#: ``comment_end`` so the two meanings never share a name; both ends or neither, which
#: the filter refuses by name and this hint states.
_COMMENT_TIMES = (
    Field(key='comment_start', control='text', label_key='settings.commentStart', placeholder='2026-01-01'),
    Field(
        key='comment_end',
        control='text',
        label_key='settings.commentEnd',
        placeholder='2026-12-31',
        hint_key='settings.commentTimeHint',
    ),
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

# ─── CatBus 独有模式的字段 ──────────────────────────────────────────────
# CatBus 清单只声明参数名（``room``/``folder``/``series``…），按钮长什么样是采析绘的事：
# 控件、标签、校验都在这里；服务端与面板读同一份。共享模式（posts/author/hot/comments）
# 复用 Selenium 的表单，不在这里重复声明。
_CATBUS_URLS = Field(
    key='urls',
    control='textarea',
    label_key='settings.urls',
    name_key='field.urls',
    required=True,
    coerce='urls',
    fed_by='input_column',
    placeholder='https://…',
    hint_key='settings.catbusUrlsHint',
)
_CATBUS_ROOM = Field(
    key='room', control='text', label_key='settings.catbusRoom', name_key='field.catbusRoom', required=True
)
_CATBUS_FOLDER = Field(
    key='folder', control='text', label_key='settings.catbusFolder', name_key='field.catbusFolder', required=True
)
_CATBUS_SERIES = Field(
    key='series', control='text', label_key='settings.catbusSeries', name_key='field.catbusSeries', required=True
)
_CATBUS_CONVERSATION = Field(
    key='conversation',
    control='text',
    label_key='settings.catbusConversation',
    name_key='field.catbusConversation',
    required=True,
)
_CATBUS_PRODUCT = Field(
    key='product',
    control='text',
    label_key='settings.catbusProduct',
    name_key='field.catbusProduct',
    required=True,
)
_CATBUS_COMMENT_ID = Field(
    key='comment_id',
    control='text',
    label_key='settings.catbusCommentId',
    name_key='field.catbusCommentId',
    required=True,
)
_CATBUS_ACCOUNT = _BACKEND_FIELDS[1]

#: 参数名 → 字段模板。清单里出现的参数都必须在这里有模板；没有就说明适配器加了新参数而
#: 采析绘还没有对应的框，模式会被拒绝而不是画一个填不了的输入。
_CATBUS_FIELD_TEMPLATES = {
    'keyword': _KEYWORD,
    'target_count': _TARGET,
    'catbus_account': _CATBUS_ACCOUNT,
    'author': _AUTHOR,
    'urls': _CATBUS_URLS,
    'comment_limit': _COMMENT_LIMIT,
    'board': _BOARD,
    'room': _CATBUS_ROOM,
    'folder': _CATBUS_FOLDER,
    'series': _CATBUS_SERIES,
    'conversation': _CATBUS_CONVERSATION,
    'product': _CATBUS_PRODUCT,
    'comment_id': _CATBUS_COMMENT_ID,
}

#: CatBus 模式键 → 面板词。共享模式复用 Selenium 的词；独有模式各有自己的名字。
#: 拼出来的键是审计盲区（可达性扫描只问它看得见的键），所以这里逐个写全，并有契约测试
#: 用真实清单的每个模式键核对「有名字」。
CATBUS_MODE_LABELS = {
    'posts': 'settings.collectPosts',
    'author': 'settings.collectAuthor',
    'hot': 'settings.collectHot',
    'comments': 'settings.collectComments',
    'user.get': 'catbus.mode.userGet',
    'user.search': 'catbus.mode.userSearch',
    'user.followers': 'catbus.mode.userFollowers',
    'user.following': 'catbus.mode.userFollowing',
    'user.likes': 'catbus.mode.userLikes',
    'user.collects': 'catbus.mode.userCollects',
    'user.reposts': 'catbus.mode.userReposts',
    'item.get': 'catbus.mode.itemGet',
    'item.search': 'catbus.mode.itemSearch',
    'item.related': 'catbus.mode.itemRelated',
    'item.list': 'catbus.mode.itemList',
    'item.media': 'catbus.mode.itemMedia',
    'item.categories': 'catbus.mode.itemCategories',
    'comment.list': 'catbus.mode.commentList',
    'comment.replies': 'catbus.mode.commentReplies',
    'live.get': 'catbus.mode.liveGet',
    'live.list': 'catbus.mode.liveList',
    'live.search': 'catbus.mode.liveSearch',
    'live.categories': 'catbus.mode.liveCategories',
    'live.gifts': 'catbus.mode.liveGifts',
    'live.products': 'catbus.mode.liveProducts',
    'live.media': 'catbus.mode.liveMedia',
    'live.rank': 'catbus.mode.liveRank',
    'live.replays': 'catbus.mode.liveReplays',
    'keyword.hot': 'catbus.mode.keywordHot',
    'keyword.suggest': 'catbus.mode.keywordSuggest',
    'feed.list': 'catbus.mode.feedList',
    'feed.categories': 'catbus.mode.feedCategories',
    'folder.list': 'catbus.mode.folderList',
    'folder.items': 'catbus.mode.folderItems',
    'series.list': 'catbus.mode.seriesList',
    'series.items': 'catbus.mode.seriesItems',
    'history.list': 'catbus.mode.historyList',
    'topic.search': 'catbus.mode.topicSearch',
    'poi.search': 'catbus.mode.poiSearch',
    'notice.list': 'catbus.mode.noticeList',
    'product.get': 'catbus.mode.productGet',
    'danmaku.list': 'catbus.mode.danmakuList',
}

#: 只有 CatBus 能爬、采析绘没有 Selenium 版的平台，以及它们的词。
#: 平台是否真的出现、有哪些功能仍由适配器清单决定；这里只负责在清单不可用时也能
#: 把面板上的这一行画出来并说明「引擎不可用」，而不是让已保存的画布变成一个不存在的平台。
CATBUS_ONLY_PLATFORMS = {
    'kuaishou': 'platform.kuaishou',
    'tiktok': 'platform.tiktok',
    'jd': 'platform.jd',
    'taobao': 'platform.taobao',
    'xianyu': 'platform.xianyu',
}

#: 只有 CatBus 能爬的平台各自的内容来自哪里（网络分组，不是可用性）。
CATBUS_ONLY_REGIONS = {
    'kuaishou': 'cn',
    'tiktok': 'overseas',
    'jd': 'cn',
    'taobao': 'cn',
    'xianyu': 'cn',
}

#: 红果短剧's four boards. Same shape as bilibili's choice (one board, one row shape), so it
#: is the same field key and the same refusal path; the stored values are identifiers because
#: they are what a node holds, and the order here is the order the panel offers them (pinned
#: against ``crawlers.platforms.hongguo.crawler.BOARDS`` by ``tests/unit/test_hongguo_crawler.py``).
_HONGGUO_BOARD = Field(
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
_HONGGUO_EPISODES = Field(
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
_HONGGUO_REPLIES = Field(
    key='include_replies',
    control='checkbox',
    label_key='settings.hgIncludeReplies',
    default=True,
    hint_key='settings.hgIncludeRepliesHint',
    coerce='bool',
)
#: How long one episode's comment page may take to ARRIVE before the walk names it.
#: A per-node data choice (how much patience this crawl buys), not a settings key.
_HONGGUO_WAIT = Field(
    key='harvest_timeout',
    control='number',
    label_key='settings.hgHarvestTimeout',
    default=90,
    minimum=10,
    maximum=600,
    hint_key='settings.hgHarvestTimeoutHint',
    coerce='number',
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
    session_required: bool = True,
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
        fields=(
            replace(_TARGET, default=target),
            *((_BOARD,) if board else ()),
            *extra,
            # A board is chosen by the site, but reading it can still be logged in —
            # only when it is (measured: zhihu's hot list 401s anonymously) does the
            # node get an account to pick; weibo's 热搜 answers anyone and keeps no
            # choice it cannot honour. The parameter is ``session_required``, not
            # ``needs_session``: the module-level ``needs_session()`` is the question the
            # cookie gate asks, and shadowing it in here made this builder unable to call it.
            *_BACKEND_FIELDS,
            *((_ACCOUNT,) if session_required else ()),
            _RECOLLECT,
        ),
        # A board opens a page once then reads JSON: a visible window only sits there.
        # The note says so (and that 无头 saves nothing to watch) instead of the panel
        # holding its own opinion about which modes move the screen.
        note_key='settings.fetchQuietNote' if collects == 'fetch' else '',
        collects=collects,
        needs_session=session_required,
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
                fed_by='input_column',
            ),
            _INPUT_COLUMN,
            _COMMENT_LIMIT,
            *_COMMENT_TIMES,
            _PER_ARTICLE,
            # The comment walk keeps the same ledger a source crawl does — an
            # already-stored comment is skipped, never re-fetched — so the switch that
            # releases it belongs here too. It was missing on **every** platform's
            # comment node (user-reported 2026-09-26, weibo first), which is the hole
            # ``test_every_mode_that_skips_rows_offers_to_forget_them`` now refuses:
            # a crawl that silently dedupes with no way back reads as "the site has no
            # more comments", and 重新采集 was the only repair.
            #
            # Comments are read as a logged-in reader on every platform that offers
            # this form, so the account selector belongs here as well as on the source
            # walks: the wall a comment crawl hits is the *account's* rate limit.
            *_BACKEND_FIELDS,
            _ACCOUNT,
            _RECOLLECT,
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


def _hongguo_comment_mode() -> Mode:
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
            _INPUT_COLUMN,
            _COMMENT_LIMIT,
            *_COMMENT_TIMES,
            _HONGGUO_EPISODES,
            _HONGGUO_REPLIES,
            _HONGGUO_WAIT,
            _PER_ARTICLE,
            _RECOLLECT,
        ),
        note_key='settings.hgCommentNote',
        collects='external_app',
        needs_session=False,
        # The one mode in the matrix that is not a browser crawl: it drives a desktop player behind our
        # own proxy, so a Linux server and a Mac have nothing to drive (``_ensure_stack`` refuses it by
        # name at run time, and this is what keeps the panel from offering it at all).
        requires='windows_desktop',
    )


def _posts_mode(
    *extra: Field,
    target: int = 50,
    label_key: str = 'settings.collectPosts',
    collects: str = 'dom_scroll',
    note_key: str = '',
) -> Mode:
    return Mode(
        key='posts',
        label_key=label_key,
        fields=(_KEYWORD, replace(_TARGET, default=target), *extra, *_BACKEND_FIELDS, _ACCOUNT, _RECOLLECT),
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
        fields=(author, replace(_TARGET, default=target), *extra, *_BACKEND_FIELDS, _ACCOUNT, _RECOLLECT),
        note_key=note_key,
        collects=collects,
    )


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        platform='zhihu',
        # Two sessions crawling zhihu at once have been watched to coexist (search pages
        # and either comment shape), so the advice panel calls parallel out by name
        # rather than leaving it as "not marked serial-only".
        parallel_recommended=True,
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
            _hot_mode(board=False, session_required=False),
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
                # The article bodies are served anonymously by mp.weixin.qq.com (the crawler says
                # so, and wechat has never been in ``CookieManager.PLATFORMS``, so the panel holds no
                # row for it): there is no login this crawl can be asked for. Leaving the flag True
                # made the pre-run gate buy a browser to test a session that does not exist and then
                # refuse a crawl that needs no cookie at all.
                needs_session=False,
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
                        fed_by='input_column',
                    ),
                    _INPUT_COLUMN,
                    # An article URL already collected is skipped here too — the ledger is
                    # the source path's, not a per-platform choice — so the way back has to
                    # be on this form as well. It was missing because this mode is the one
                    # that does not come from ``_posts_mode``, which is how a rule that
                    # looks "shared" ends up holding for 26 of 27 forms; the matrix test
                    # ``test_every_crawl_mode_offers_to_forget_what_it_deduped`` now walks
                    # all of them instead of the helpers.
                    _RECOLLECT,
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
        # Paged search reads one account's pages independently and comments come from a
        # reply API that tolerates two sessions crawling at once (measured), so parallel
        # is the recommended shape here, named as such rather than inferred.
        parallel_recommended=True,
        modes=(
            _posts_mode(label_key='settings.collectVideos', collects='dom_read'),
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
        # Measured 2026-09-26, one network and one account, the session shape the only variable:
        # a cookie-planted throwaway browser was answered 验证码中间页 in 8.8 s (and refused to
        # file an empty table), while the same keyword ``IU`` crawl run through the platform's own
        # profile returned 5 rows in 24.8 s. That is the same "a copied login is a second device"
        # behaviour already written down for weibo, so douyin gets the recommendation too: the
        # visible window is necessary but not sufficient — the jar has to be the one the site
        # rotated. **One mode reads the other way**: the 热榜 board was answered the captcha BY
        # the profile and served by the throwaway browser (measured 2026-09-25, note on
        # ``_hot_mode`` below), which is why the recommendation is a warning and never a coercion,
        # and why #142 keeps the question open instead of resolving it into one sentence.
        profile_recommended=True,
        modes=(
            _author_mode(
                placeholder='https://www.douyin.com/user/<sec_uid>',
                hint_key='settings.authorHintDouyin',
                collects='modal_per_row',
            ),
            # One answer is the whole board (measured 51 rows), and it needs no board
            # choice: douyin publishes this one list. It does need a session — measured
            # on the same day, the tool's own douyin profile was answered the captcha
            # interstitial while a cookie-planted throwaway browser read the board, so
            # 需要登录 here is the truth rather than a hedge.
            _hot_mode(board=False),
            _comment_mode('douyin', 'https://www.douyin.com/video/...', collects='dom_scroll'),
        ),
    ),
    Capability(
        platform='hongguo',
        modes=(
            # 红果短剧's four 热播 boards each come back 20 works a page, five pages, all four
            # in one measured shape — so this is one mode with a choice inside it, the same
            # shape bilibili's board takes. Anonymous on purpose: measured 2026-10, every
            # board is served to a fresh browser with no cookie, which is why the node
            # carries no account field and the pre-run gate asks it no session question.
            _hot_mode(_HONGGUO_BOARD, board=False, session_required=False),
            # Comments exist only in the app protocol; the crawl drives the desktop
            # player behind our own proxy and reads what it legitimately fetched
            # (docs/crawler_notes.md 红果短剧 for the whole measurement chain).
            _hongguo_comment_mode(),
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


def backend_of(params) -> str:
    """The backend a node asks for, defaulted to the one that has always been there.

    A blank means Selenium — canvases written before this switch existed carry no key at all, and
    the executor reads a node that never opened its panel. An unknown spelling is not silently
    treated as Selenium: ``unoffered_selections`` refuses it by name at validation time.
    """
    return str((params or {}).get('backend') or BACKEND_SELENIUM).strip().lower()


def is_catbus(params) -> bool:
    """Whether *params* asks to crawl through CatBus rather than through a browser."""
    return backend_of(params) == BACKEND_CATBUS


def platform_ids() -> tuple[str, ...]:
    """Every platform the matrix describes, in panel order."""
    return tuple(_BY_PLATFORM)


def has_platform(platform: str) -> bool:
    return str(platform or '') in _BY_PLATFORM


# ─── The engine dimension: 平台 × 引擎 × 功能 ────────────────────────────
# The Selenium matrix above stays the browser half. CatBus is never copied into it: which modes a
# platform has under CatBus, their columns, their parameters and their availability are read out of
# the adapter's own manifest on every request (cached by the bridge). A mode that exists only on
# CatBus (user.followers, keyword.hot …) is materialised here as an ordinary ``Mode`` so the panel,
# validation and the executor keep speaking one language.


def _catbus_status() -> dict:
    from services import catbus_bridge

    return catbus_bridge.status_payload()


def _catbus_platforms() -> dict:
    from services import catbus_bridge

    return catbus_bridge.manifest_platforms()


def catbus_platform_ids() -> tuple[str, ...]:
    """Platforms the adapter offers at all — the CatBus-only entries among them."""
    return tuple(_catbus_platforms())


def can_crawl_platform(platform: str, params: dict | None = None) -> bool:
    """Whether any engine can crawl *platform* for this node.

    A CatBus-only platform (快手/TikTok/京东/淘宝/闲鱼) is crawlable **through CatBus** even though no
    Selenium crawler class exists for it. ``params`` decides which engine the node asks for; without
    it, either registry knowing the name is enough (the cookie panel's question).
    """
    if has_platform(platform):
        return True
    if params is None or is_catbus(params):
        return str(platform or '') in catbus_platform_ids()
    return False


def engine_default(platform: str) -> str:
    """Which engine a brand-new node of this platform starts on.

    The browser when this platform has one — every saved canvas and every live-site rule is written
    around it — and CatBus only where it is the only engine that exists.
    """
    return BACKEND_SELENIUM if has_platform(platform) else BACKEND_CATBUS


def engine_state(platform: str, backend: str) -> tuple[bool, str]:
    """``(available, reason_key_or_sentence)`` for one engine on one platform.

    The payload wants a catalogue key (the browser translates it), while validation wants the
    adapter's own sentence. Callers get the key here and ask :func:`catbus_run_errors` for the run-time
    wording; the two cannot disagree because both read the same probe.
    """
    if backend == BACKEND_SELENIUM:
        return has_platform(platform), ('' if has_platform(platform) else 'settings.backendNoSelenium')
    if backend != BACKEND_CATBUS:
        return False, 'settings.backendUnknown'
    status = _catbus_status()
    if not status.get('available'):
        return False, str(status.get('panelKey') or 'settings.backendProbeFailed')
    entry = _catbus_platforms().get(platform)
    if not entry:
        return False, 'settings.backendNoPlatform'
    modes = entry.get('modes') or {}
    if not any(str((cell or {}).get('status')) in ('available', 'partial') for cell in modes.values()):
        return False, 'settings.backendNoRunnable'
    return True, ''


def engines_for(platform: str) -> tuple[dict, ...]:
    """Every engine this platform offers, in the order the panel shows them.

    Selenium first (the long-standing default), CatBus second. Only engines that exist for the
    platform are listed: a CatBus-only platform has no browser entry to grey out, because there is
    no browser crawl to wait for.
    """
    out: list[dict] = []
    cap = capability(platform)
    if cap is not None:
        out.append(
            {
                'key': BACKEND_SELENIUM,
                'labelKey': 'settings.backendSelenium',
                'available': True,
                'reasonKey': '',
                'reason': '',
                'modes': [m.key for m in cap.modes],
            }
        )
    # Every platform carries the CatBus entry, even one the adapter does not list: the engine is a
    # first-class choice, and 「CatBus 不提供这个平台」 is an answer the panel can show. Hiding the
    # engine would make a saved CatBus node look like it had chosen Selenium.
    available, reason_key = engine_state(platform, BACKEND_CATBUS)
    entry = _catbus_platforms().get(platform) or {}
    out.append(
        {
            'key': BACKEND_CATBUS,
            'labelKey': 'settings.backendCatbus',
            'available': available,
            'reasonKey': reason_key,
            'reason': '',
            'modes': list((entry.get('modes') or {}).keys()),
        }
    )
    return tuple(out)


def _selenium_mode(platform: str, mode_key: str) -> Mode | None:
    cap = capability(platform)
    if cap is None:
        return None
    for mode in cap.modes:
        if mode.key == mode_key:
            return mode
    return None


def _catbus_mode_fields(cell: dict) -> tuple[Field, ...] | None:
    """The form for a CatBus-only mode, from the manifest's declared parameters.

    Returns ``None`` when the adapter declares a parameter this build has no input for: the panel
    must not show a form missing a required box, so that mode is not offered until 采析绘 catches up.
    """
    params = [str(p) for p in (cell.get('params') or [])]
    args = [str(a) for a in (cell.get('args') or [])]
    optional = dict(cell.get('optional') or {})
    required = {params[i] for i, arg in enumerate(args) if i < len(params) and arg not in optional}
    fields: list[Field] = []
    for name in params:
        template = _CATBUS_FIELD_TEMPLATES.get(name)
        if template is None:
            return None
        fields.append(
            replace(template, required=name in required) if template.required != (name in required) else template
        )
    if _RECOLLECT not in fields:
        fields.append(_RECOLLECT)
    return tuple(fields)


def _catbus_mode(mode_key: str, cell: dict) -> Mode | None:
    """Materialise one CatBus-only mode as an ordinary ``Mode`` for the panel/validation/executor."""
    fields = _catbus_mode_fields(cell)
    if fields is None:
        return None
    output = str(cell.get('output') or '')
    return Mode(
        key=mode_key,
        label_key=CATBUS_MODE_LABELS.get(mode_key, ''),
        handler='catbus',
        fields=fields,
        rows='comments' if output == 'Comment' else 'posts',
        note_key='settings.catbusModeNote',
        collects='fetch',
        # CatBus keeps its own account files; the browser pre-run gate is not the one to ask.
        needs_session=False,
    )


def catbus_mode_objects(platform: str) -> tuple[Mode, ...]:
    """Every mode the adapter offers for *platform*, shared keys reusing the Selenium declaration.

    Reusing the Selenium ``Mode`` for posts/author/hot/comments keeps one form (keyword/target/board/
    urls/account) for both engines; a CatBus-only key gets a form built from the manifest's parameters.
    """
    entry = _catbus_platforms().get(platform) or {}
    out: list[Mode] = []
    for mode_key, cell in (entry.get('modes') or {}).items():
        existing = _selenium_mode(platform, mode_key)
        mode = existing or _catbus_mode(mode_key, dict(cell or {}))
        if mode is not None:
            out.append(mode)
    return tuple(out)


def catbus_run_errors(platform: str, mode_key: str) -> list[str]:
    """Why a CatBus run of this cell cannot start, as the detail of a refusal ('' when it can).

    Asked before the run claims the slot. The adapter would refuse too, but a refusal after a browser,
    an LLM step or a queue turn has been paid for is a refusal that cost the user the run. The caller
    wraps each detail in ``engine.source_catbus`` so the node is named once, not twice.
    """
    from services import catbus_bridge

    info = catbus_bridge.probe()
    if not info.available:
        return [t(info.reason_key, **info.reason_params)]
    state, why = catbus_bridge.mode_state(platform, mode_key)
    if state in ('available', 'partial'):
        return []
    label = str((_catbus_platforms().get(platform) or {}).get('label') or platform)
    return [why or t('catbus.noRunnableCell', platform=label)]


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
    if cap is not None:
        return cap.region
    return CATBUS_ONLY_REGIONS.get(str(platform or ''), '')


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
COLLECT_KINDS = ('fetch', 'dom_read', 'dom_scroll', 'modal_per_row', 'page_per_row', 'external_app')


def needs_session(platform: str, mode_key: str, backend: str = BACKEND_SELENIUM) -> bool:
    """Whether this crawl is a session crawl — the question the cookie gate asks.

    The gate probes per platform, so a canvas whose only node is weibo's 热搜 board
    would be refused for lacking a cookie the measured endpoint never wanted. Unknown
    platform or mode answers True: no answer is not evidence that a crawl is anonymous,
    and the gate staying on for something it cannot judge is the safe direction.

    The engine is part of the question: a CatBus mode reads CatBus' own account files, and its
    login gate is answered by the adapter's preflight, not by this matrix.
    """
    backend = str(backend or BACKEND_SELENIUM).strip().lower()
    if backend == BACKEND_CATBUS:
        from services import catbus_bridge

        return catbus_bridge.needs_session(platform, mode_key)
    mode = mode_for(platform, mode_key, backend)
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


def modes_for(platform: str, backend: str = BACKEND_SELENIUM) -> tuple[Mode, ...]:
    """The modes one engine offers on one platform.

    ``selenium`` is the static matrix; ``catbus`` is materialised from the adapter's manifest. A
    caller that does not name an engine keeps the browser answer, which is what every pre-engine
    caller meant.
    """
    backend = str(backend or BACKEND_SELENIUM).strip().lower()
    if backend == BACKEND_CATBUS:
        return catbus_mode_objects(platform)
    cap = capability(platform)
    return () if cap is None else cap.modes


def mode_keys_for(platform: str, backend: str = BACKEND_SELENIUM) -> tuple[str, ...]:
    return tuple(m.key for m in modes_for(platform, backend))


def mode_for(platform: str, mode_key: str, backend: str = BACKEND_SELENIUM) -> Mode | None:
    """The declared mode for one engine, or that engine's first runnable mode on an unknown key.

    Falling back is what keeps an old canvas (which never heard of 评论采集 or renamed keys) opening a
    panel that matches what the executor will do, instead of refusing to render. The fallback is
    engine-aware: a CatBus node whose stored key the adapter does not offer falls to the first cell
    CatBus can actually crawl, never to a browser-only mode the CatBus adapter has no handler for.

    When the adapter itself is unavailable, the browser declaration is used as the *shape* so
    validation can reach :func:`catbus_run_errors` and name the engine's reason — reporting
    「unknown platform」 for a node whose only problem is an uninstalled adapter would send the user
    looking for the wrong thing.
    """
    backend = str(backend or BACKEND_SELENIUM).strip().lower()
    modes = modes_for(platform, backend)
    if not modes and backend == BACKEND_CATBUS:
        modes = modes_for(platform, BACKEND_SELENIUM)
    if not modes:
        return None
    wanted = str(mode_key or '').strip()
    for mode in modes:
        if mode.key == wanted:
            return mode
    if backend == BACKEND_CATBUS:
        for mode in modes:
            if _catbus_runnable(platform, mode.key):
                return mode
    return modes[0]


def _catbus_runnable(platform: str, mode_key: str) -> bool:
    from services import catbus_bridge

    return catbus_bridge.supports(platform, mode_key)


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
    """The mode a stored node asks for, read the way the executor reads it.

    The engine is part of the reading: the same 平台 × 功能 can be a different form (and a different
    handler) under CatBus, and a node's stored ``backend`` is what decides which one this run gets.
    """
    node = node or {}
    params = node.get('params') or {}
    platform = str(node.get('platform') or params.get('platform') or '')
    return mode_for(platform, requested_mode_key(node), backend_of(params))


def mode_blocker(mode: Mode | None, system: str | None = None, cloud: bool | None = None) -> str:
    """Why this machine cannot run ``mode`` ('' when it can), as a catalogue key.

    Asked at validation and not only inside the node: the answer is known when the page loads, and a
    user should not pay for a run start — a browser, the single run slot, whatever LLM steps sit
    downstream — to learn it. The node's own executor still refuses; this only moves the refusal
    earlier, where it costs a line instead of a run.
    """
    if mode is None or not mode.requires:
        return ''
    if requirement_met(mode.requires, system, cloud):
        return ''
    return requirement_label_key(mode.requires)


def fields_for(
    platform: str, mode_key: str, with_files: bool = True, backend: str = BACKEND_SELENIUM
) -> tuple[Field, ...]:
    mode = mode_for(platform, mode_key, backend)
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


_NOT_ARGS = frozenset({'recrawl', 'account', 'input_column', 'backend', 'catbus_account'})


def crawl_kwargs(mode: Mode, params: dict) -> dict:
    """Coerce the node's stored parameters into crawler arguments.

    A CatBus-only mode tells the executor *which* manifest cell to run through the ``mode_key``
    argument, because its handler (``CatbusCrawler.catbus``) is one method for every read command —
    the command itself is the mode, not a platform-specific method name.
    """
    out = {f.key: f.value_from(params) for f in crawler_fields(mode)}
    if mode.handler == 'catbus':
        out['mode_key'] = mode.key
    return out


def declared_defaults(platform: str) -> dict:
    """Every parameter the platform's modes mention, at its declared default.

    Two consumers, one source: the canvas seeds a new node from this, and the
    executor reads a node that never opened its panel as
    ``params.get(key, declared_default)`` — so a widget's preview and the run's
    figure cannot drift apart. Both engines are included: the panel switches forms
    without re-seeding, and a CatBus-only field must already be at its default when
    the user picks CatBus.
    """
    out: dict = {}
    for backend in BACKENDS:
        for mode in modes_for(platform, backend):
            for f in mode.fields + FILE_FIELDS:
                out.setdefault(f.key, f.default)
    if out or has_platform(platform) or str(platform or '') in CATBUS_ONLY_PLATFORMS:
        out.setdefault('backend', engine_default(platform))
    return out


def feed_of(mode: Mode) -> list[tuple[Field, str]]:
    """(feedable field, its column param key) pairs this mode declares.

    The single answer to "can this form be fed from an upstream table": a mode is
    feedable iff this list is non-empty. Panel, validation and executor all read
    it, so none of them can disagree about which modes accept a feed.
    """
    return [(f, f.fed_by) for f in mode.fields if f.fed_by]


def fed_keys(mode: Mode, has_data_input: bool) -> frozenset[str]:
    """Field keys whose pasted value a wired-in parent table REPLACES.

    Without a data-bearing parent the pasted value rules exactly as before. A wired
    node is feed-expected even before it named the column: naming a missing column
    is a separate refusal in validation, never a silent fall back to the textarea —
    the user who wired a table means the table.
    """
    if not has_data_input:
        return frozenset()
    return frozenset(f.key for f, _col in feed_of(mode))


def required_missing(mode: Mode, params: dict, fed: frozenset[str] = frozenset()) -> list[Field]:
    """Required fields the node leaves empty — the whole of source validation.

    A field fed from an upstream column is not "empty" because its textarea is:
    the values arrive at execution time, so its pasted requiredness is waived.
    """
    out = []
    for f in mode.fields:
        if not f.required or f.key in fed:
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

    The 账号 selector is deliberately **not** decided here, because "is this account a
    valid choice" has a stronger and completely different answer: it is not a member of
    a declared list but a session this machine either has or does not. That question is
    asked once, against the cookie file and the profile together, in
    ``engine.workflow._source_errors`` — and this function must not answer it as well, or
    one missing login prints two console lines about one failure.

    A blank is not a mistake but "never chose", which the declared default answers —
    so it is skipped, exactly as an empty mode key is. Case is deliberately **not**
    folded: an option value is a storage key, and the user has to see what they wrote
    rather than have a near miss guessed into a different crawl.
    """
    out: list[tuple[Field, str]] = []
    for field in list(mode.fields) + (list(FILE_FIELDS) if with_files else []):
        if field.control != 'select' or not field.options or field.key == 'account':
            continue
        raw = params.get(field.key)
        if raw is None:
            continue
        value = str(raw).strip()
        offered = {stored for stored, _label in field.options}
        if not value or value in offered:
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


def names_also_accepted(mode: Mode | None) -> bool:
    """Does this mode's link list also take plain names? (See :attr:`Field.accepts_names`.)"""
    return bool(mode) and any(f.accepts_names for f in mode.fields if f.is_link_list())


def is_url_cell(cell) -> bool:
    """Does this input line look like a link at all (rather than a name)?

    The one question the router needs to route a line, and deliberately not a URL parser:
    a 红果 drama title never parses, and a bare ``series_id=…`` link the user pasted without
    its scheme still has to route by domain. Anything holding a scheme or a query is a
    link; everything else is the name the client's own board is searched with.

    The query test spells its word class as ``[A-Za-z0-9_]``, not a shorthand one: ``static/js/
    workflow.js`` answers the SAME question for the panel (``field.acceptsNames``) with a
    JavaScript word class, which is ASCII-only while Python's covers Chinese. One shared
    spelling of one rule — a title holding a Chinese character is a NAME in both, never a link
    the panel blesses and the engine then refuses. Pinned by
    ``test_a_name_the_panel_agrees_is_a_name``.
    """
    text = str(cell or '').strip()
    return '://' in text or bool(re.search(r'[?&][A-Za-z0-9_]+=', text))


def as_dict(catbus_status: dict | None = None) -> dict:
    """The whole matrix, ready for ``GET /api/capabilities``.

    Three dimensions in one payload: every platform carries its **engines** (which tools can crawl it,
    and whether THIS machine can start each), every mode names the engines that offer it, and every
    mode × engine pair carries the **cell** answer (runnable, the adapter's own reason, columns and
    identity). The browser renders from these; it never keeps a list of which platform or mode exists.

    A CatBus-only platform (快手/TikTok/京东/淘宝/闲鱼) is appended with no browser engine. It is
    listed even when the adapter is unavailable so the panel can say why nothing can run, instead of
    silently omitting a platform the user's saved canvas may name.
    """
    status = catbus_status if catbus_status is not None else _catbus_status()
    cells = dict(status.get('cells') or {})
    manifest = _catbus_platforms()
    platforms: list[dict] = []

    for cap in CAPABILITIES:
        modes: list[dict] = []
        seen: set[str] = set()
        for mode in cap.modes:
            cell = _cell_payload(cells.get(f'{cap.platform}.{mode.key}'), status)
            engines = [BACKEND_SELENIUM]
            if cell['status'] != 'absent':
                engines.append(BACKEND_CATBUS)
            modes.append(
                _mode_as_dict(
                    mode,
                    engines=engines,
                    cells={BACKEND_SELENIUM: _available_cell(), BACKEND_CATBUS: cell},
                )
            )
            seen.add(mode.key)
        for mode in catbus_mode_objects(cap.platform):
            if mode.key in seen:
                continue
            cell = _cell_payload(cells.get(f'{cap.platform}.{mode.key}'), status)
            modes.append(_mode_as_dict(mode, engines=[BACKEND_CATBUS], cells={BACKEND_CATBUS: cell}))
        platforms.append(
            {
                'platform': cap.platform,
                'labelKey': f'platform.{cap.platform}',
                'engines': list(engines_for(cap.platform)),
                'modes': modes,
                'profileRecommended': bool(cap.profile_recommended),
                'region': cap.region,
                'serialOnly': bool(cap.serial_only),
                'parallelRecommended': bool(cap.parallel_recommended),
            }
        )

    for platform, label_key in CATBUS_ONLY_PLATFORMS.items():
        entry = manifest.get(platform) or {}
        modes: list[dict] = []
        for mode in catbus_mode_objects(platform):
            cell = _cell_payload(cells.get(f'{platform}.{mode.key}'), status)
            modes.append(_mode_as_dict(mode, engines=[BACKEND_CATBUS], cells={BACKEND_CATBUS: cell}))
        platforms.append(
            {
                'platform': platform,
                'labelKey': label_key,
                'label': str(entry.get('label') or ''),
                'engines': list(engines_for(platform)),
                'modes': modes,
                'profileRecommended': False,
                'region': CATBUS_ONLY_REGIONS.get(platform, 'cn'),
                'serialOnly': False,
                'parallelRecommended': False,
            }
        )

    return {
        'platforms': platforms,
        'fileFields': [_field_as_dict(f) for f in FILE_FIELDS],
        'backends': {BACKEND_CATBUS: status},
    }


def _available_cell() -> dict:
    return {'status': 'available', 'runnable': True, 'reason': '', 'reasonKey': '', 'columns': [], 'identity': []}


def _cell_payload(cell: dict | None, status: dict) -> dict:
    """One 功能 × 引擎 answer, from the adapter's cell plus this machine's probe verdict."""
    if not status.get('available'):
        return {
            'status': 'unavailable',
            'runnable': False,
            'reason': '',
            'reasonKey': str(status.get('panelKey') or 'settings.backendProbeFailed'),
            'columns': [],
            'identity': [],
        }
    if not cell:
        return {'status': 'absent', 'runnable': False, 'reason': '', 'reasonKey': '', 'columns': [], 'identity': []}
    return {
        'status': str(cell.get('status') or ''),
        'runnable': bool(cell.get('runnable')),
        'reason': str(cell.get('reason') or ''),
        'reasonKey': '',
        'columns': list(cell.get('columns') or []),
        'identity': list(cell.get('identity') or []),
    }


def _mode_as_dict(mode: Mode, engines: list[str] | None = None, cells: dict | None = None) -> dict:
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
        # The machine requirement travels as its token; whether THIS host meets it is the payload's
        # ``machine`` map. The browser needs both to grey the option out and to say why in its own language.
        'requires': mode.requires,
        # Which engines offer this function, and what each says about this machine. The panel filters
        # the mode list by the selected engine and greys a pair it cannot run — never removes it, so a
        # canvas that STORED the value still shows what it holds.
        'engines': list(engines if engines is not None else [BACKEND_SELENIUM]),
        'cells': dict(cells if cells is not None else {BACKEND_SELENIUM: _available_cell()}),
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
        'acceptsNames': f.accepts_names,
        'placeholder': f.placeholder,
        'fedBy': f.fed_by,
    }
