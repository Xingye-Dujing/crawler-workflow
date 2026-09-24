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

from utils.helpers import split_urls


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
            return bool(raw)
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
    default='popular',
    options=(('popular', 'settings.hotBoardPopular'), ('ranking', 'settings.hotBoardRanking')),
)


def _hot_mode(*extra: Field, target: int = 50) -> Mode:
    """The site's own hot list — not a keyword's result page.

    No required field: what a hot list is about is chosen by the site, so the only
    choices offered are how many rows and which board.
    """
    return Mode(
        key='hot',
        label_key='settings.collectHot',
        handler='hot',
        fields=(replace(_TARGET, default=target), _BOARD, *extra, _RECOLLECT),
    )


def _comment_mode(platform: str, example: str) -> Mode:
    """The 评论 form, which is the same on every platform except the link shape.

    The example URL is the only per-platform part besides the ownership rule, and
    both are data: the panel prints the example as the field's placeholder so a
    person sees one valid shape rather than three at once, and the engine refuses
    links that contradict the platform the node selected.
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
        # The comment engine opens a visible window whatever the run settings
        # say (Zhihu refuses a headless content page), and the panel has to say
        # so before the user starts a crawl that looks like it hung.
        note_key='settings.commentHint',
    )


def _posts_mode(*extra: Field, target: int = 50) -> Mode:
    return Mode(
        key='posts',
        label_key='settings.collectPosts',
        fields=(_KEYWORD, replace(_TARGET, default=target), *extra, _RECOLLECT),
    )


def _author_mode(
    *extra: Field,
    target: int = 50,
    placeholder: str = '@handle',
    hint_key: str = 'settings.authorHint',
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
    )


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        platform='zhihu',
        modes=(
            _posts_mode(_FULL_BODY),
            _author_mode(
                placeholder='https://www.zhihu.com/people/<id>',
                hint_key='settings.authorHintZhihu',
            ),
            _comment_mode('zhihu', 'https://www.zhihu.com/question/...'),
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
                )
            ),
            _comment_mode('xiaohongshu', 'https://www.xiaohongshu.com/explore/...'),
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
            ),
        ),
    ),
    Capability(
        platform='bilibili',
        modes=(
            _posts_mode(),
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
            _posts_mode(),
            _author_mode(
                placeholder='https://www.douyin.com/user/<sec_uid>',
                hint_key='settings.authorHintDouyin',
            ),
            _comment_mode('douyin', 'https://www.douyin.com/video/...'),
        ),
    ),
    # The overseas three come last on purpose: they are the newest entries and the
    # panel's order is this tuple's order, so the platforms a Chinese-language
    # user reaches for first stay at the top of the list.
    Capability(
        platform='youtube',
        region='overseas',
        modes=(
            _posts_mode(_WITH_FACTS),
            _author_mode(_WITH_FACTS),
            _comment_mode('youtube', 'https://www.youtube.com/watch?v=...'),
        ),
    ),
    Capability(
        platform='twitter',
        region='overseas',
        modes=(
            _posts_mode(),
            _author_mode(),
            _comment_mode('twitter', 'https://x.com/.../status/...'),
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
