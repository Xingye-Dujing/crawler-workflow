"""The declaration dataclasses: one input, one mode, one platform.

``Field`` is what the Data Source panel renders and what the executor coerces; ``Mode`` is one way
to crawl a platform (its fields, what it collects, whether it needs a session, which machine
requirement it carries); ``Capability`` is a platform's ordered modes plus the panel's advice.
Frozen, because the whole matrix is a value: a ``replace`` copy is how a variant is made, never a
mutation.
"""

from dataclasses import dataclass

from core.refs import as_bool, split_urls


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
