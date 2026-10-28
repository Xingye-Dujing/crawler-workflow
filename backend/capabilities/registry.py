"""What every platform can actually crawl — the queries over the declarations.

The declarations themselves live in ``capabilities/platforms/<id>.py`` (one file per
platform, panel order pinned by the package's ``__init__``), their shared atoms and mode
factories in ``capabilities/fields.py``, and the second engine's own vocabulary in
``capabilities/catbus.py``. This module is the question side only: what exists, what a
node asks for, what it must be given, and the payload ``GET /api/capabilities`` ships.

It sits inside ``backend/capabilities/`` for the same reason ``i18n.py`` sits at the root:
``engine/workflow.py`` reads it and must not import the crawler package (the Selenium
import is heavy and the dependency would run the wrong way), while ``app.py`` and the
crawler modules need the very same description.

Deliberately absent: result column names. Those are a property of the page a crawler read,
so a copy here would be an unchecked claim — the live-site tests derive columns from real
crawls instead.
"""

import re
from dataclasses import replace

from capabilities.catbus import (
    CATBUS_FIELD_TEMPLATES,
    CATBUS_MODE_LABELS,
    CATBUS_ONLY_PLATFORMS,
    CATBUS_ONLY_REGIONS,
)
from capabilities.fields import BACKEND_CATBUS, BACKEND_SELENIUM, BACKENDS, FILE_FIELDS, RECOLLECT
from capabilities.model import Capability, Field, Mode
from capabilities.platforms import CAPABILITIES
from capabilities.requirements import requirement_label_key, requirement_met
from i18n import t

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
    from services.ingest import catbus

    return catbus.status_payload()


def _catbus_platforms() -> dict:
    from services.ingest import catbus

    return catbus.manifest_platforms()


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
        template = CATBUS_FIELD_TEMPLATES.get(name)
        if template is None:
            return None
        fields.append(
            replace(template, required=name in required) if template.required != (name in required) else template
        )
    if RECOLLECT not in fields:
        fields.append(RECOLLECT)
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
    from services.ingest import catbus

    info = catbus.probe()
    if not info.available:
        return [t(info.reason_key, **info.reason_params)]
    state, why = catbus.mode_state(platform, mode_key)
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
        from services.ingest import catbus

        return catbus.needs_session(platform, mode_key)
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
    from services.ingest import catbus

    return catbus.supports(platform, mode_key)


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
