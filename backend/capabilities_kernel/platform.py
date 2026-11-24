"""A social platform: the modes it offers, the fields each mode asks, and the skill that chooses.

``capabilities/platforms/<id>.py`` already declared one platform per file; this module is the move
of those declarations into the capability tree (``capabilities_kernel/platforms/<id>/manifest.py``)
so a platform is a capability like a node, an operator or a chart: it carries an identity, its
skill, the documentation the generator renders and the contract test that proves it.

The three dataclasses are the same value types the crawl matrix has always used — a ``Field`` is
one input, a ``Mode`` is one way to crawl, a ``PlatformManifest`` is the platform — moved here
because a manifest may import only the standard library and the kernel. ``Field.value_from`` defers
its ``core.refs`` import: ``core.refs`` pulls pandas, and a manifest is loaded while a canvas is
parsed, so the cost belongs on the crawl path where the coercion actually happens.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from capabilities_kernel.manifest import (
    API_VERSION,
    Ai,
    Docs,
    Execution,
    Identity,
    ParamSpec,
    Ports,
    Tests,
    Ui,
)


def _int(raw, default, minimum=None, maximum=None) -> int:
    """A number field, clamped.

    The panel lets a person type anything, and a negative row budget turns into an instant
    "exhausted" crawl that reports success, so the matrix owns the floor and the ceiling rather than
    trusting the widget.
    """
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError, OverflowError):
        # ``int(float('inf'))`` is the third one, and ``<input type=number>`` happily accepts
        # ``1e400`` / ``Infinity``: a dirty number typed into 采集条数 crashed the source node with
        # ``OverflowError`` instead of being clamped to the range this matrix already owns.
        return default if isinstance(default, int) else 0
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


@dataclass(frozen=True)
class Field:
    """One input of the Data Source panel, and one argument of the crawl.

    ``label_key``/``hint_key`` name *frontend* catalogue entries, so the payload travels as keys and
    the browser answers in whatever language the canvas is using. ``coerce`` is the one thing the
    executor needs beyond the widget type: how to turn a stored parameter into the crawler's argument.
    """

    key: str
    control: str  # text | textarea | number | checkbox | select
    label_key: str
    default: object = ''
    hint_key: str = ''
    options: tuple = ()  # ((value, label_key), …) for control='select'
    minimum: int | None = None
    maximum: int | None = None
    required: bool = False
    coerce: str = 'text'  # text | number | bool | urls
    links_of: str = ''  # set ⇒ every URL has to belong to that platform
    placeholder: str = ''
    #: The *backend* catalogue key naming this field. The console refuses a run in the run's own
    #: language, and the panel's label keys live in the browser catalogue, so a required-field
    #: message needs its own word for 'keyword' / 'article URLs'.
    name_key: str = ''
    #: Set ⇒ this list field can be **fed from an upstream table column**: its value names a sibling
    #: parameter (``input_column``) that carries the column name. One declaration drives panel
    #: (disable the textarea), validation (waive the pasted requiredness) and executor (inject the
    #: column's values). A mode is feedable iff one of its fields sets this.
    fed_by: str = ''
    #: Set ⇒ a line of this link list may also be a plain NAME. Declared for 红果's comment form,
    #: whose crawl runs inside the desktop client: the web board and the client's 排行榜 are two
    #: different rankings, so the input the client can answer is the drama's title.
    accepts_names: bool = False

    def is_link_list(self) -> bool:
        return self.coerce == 'urls'

    def value_from(self, params: dict):
        """The stored parameter, coerced.

        A missing key falls back to the declared default rather than to None: the crawler's own
        signature default is a second opinion on the same number and the parity test keeps them
        equal, so a node that never opened its panel runs with exactly the figures its panel showed.
        """
        # Deferred: ``core.refs`` imports pandas, and a manifest is loaded while a canvas is parsed.
        from core.refs import as_bool, split_urls

        raw = params.get(self.key)
        if raw is None or (self.coerce != 'text' and str(raw).strip() == ''):
            return self.default
        if self.coerce == 'number':
            return _int(raw, self.default, self.minimum, self.maximum)
        if self.coerce == 'bool':
            # NOT ``bool(raw)``: an unticked box can be stored as the text 'false', and
            # ``bool('false')`` is True — which read "do not keep the part files" as "keep them".
            return as_bool(raw, bool(self.default))
        if self.coerce == 'urls':
            return split_urls(raw)
        return str(raw).strip()


@dataclass(frozen=True)
class Mode:
    """One way of using a platform: an entry of the 采集模式 select and its form.

    ``collects`` is what the mode actually DOES on screen, and it is the only answer to "does a
    visible window show anything?": ``'fetch'`` loads a page and then reads JSON from inside it,
    ``'dom_read'`` reads a rendered page without scrolling, ``'dom_scroll'`` scrolls a feed that
    visibly moves, ``'modal_per_row'`` opens an in-page overlay per row, ``'page_per_row'`` opens one
    whole page per row, and ``'external_app'`` drives a desktop client rather than a browser.
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
    #: Whether this mode's crawl needs a logged-in session at all. The pre-run cookie probe works per
    #: PLATFORM, so without this field a mode that answers an anonymous browser is refused by a gate
    #: that was never about it. Default True: nearly every crawl here is a session crawl.
    needs_session: bool = True
    #: A machine requirement, by name, from ``capabilities.requirements`` — '' when any machine that
    #: runs the server can run this mode. 红果评论 drives a desktop player through a proxy we install
    #: as a system certificate authority, so on Linux, on a Mac and in cloud mode there is nothing to
    #: drive. The payload answers whether THIS machine satisfies it and the panel greys the mode out.
    requires: str = ''


@dataclass(frozen=True)
class PlatformManifest:
    """One platform: its modes, its measured advice, and the capability sections around them."""

    identity: Identity
    modes: tuple[Mode, ...] = ()
    #: Running in a throwaway browser is measurably punished on this platform — its session rotates
    #: or its risk control re-walls a replayed snapshot within minutes, while the user's own browser
    #: keeps working. The panel and the pre-run dialog read this; it is never a refusal.
    profile_recommended: bool = False
    #: Crawls of this platform take turns **even when the user has 错峰 on**: one account paging two
    #: sessions at once is answered by the login wall (measured on weibo). A property of the site.
    serial_only: bool = False
    #: The opposite advice, derived from its own measurements: two sessions have been watched to
    #: coexist while a single account stays inside the site's tolerance.
    parallel_recommended: bool = False
    execution: Execution = field(default_factory=Execution)
    ui: Ui = field(default_factory=lambda: Ui(form='custom', custom_renderer='source'))
    ai: Ai = field(default_factory=Ai)
    tests: Tests = field(default_factory=Tests)
    docs: Docs = field(default_factory=Docs)
    api_version: int = API_VERSION

    # ─── The vocabulary the crawl matrix has always read ───

    @property
    def platform(self) -> str:
        return self.identity.id

    @property
    def region(self) -> str:
        """``cn`` or ``overseas``: which network this site's content and account live on."""
        return self.identity.category

    @property
    def mode_keys(self) -> tuple[str, ...]:
        return tuple(mode.key for mode in self.modes)

    # ─── The sections the capability gate asks of every manifest ───

    @property
    def params(self) -> tuple[ParamSpec, ...]:
        """A platform's parameters are its modes' fields, which carry a control and a coercion."""
        return ()

    @property
    def ports(self) -> Ports:
        return Ports(rows='table', inputs=0)

    @property
    def rules(self) -> tuple:
        return ()

    @property
    def validators(self) -> tuple[str, ...]:
        return ()

    @property
    def preflight(self) -> str:
        return ''

    @property
    def postcheck(self) -> str:
        return ''

    def param(self, _name: str) -> ParamSpec | None:
        """A platform has no flat parameter list; its parameters are its modes' fields."""
        return None

    # ─── Generated artifacts and the gate ───

    def as_dict(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        payload = json.dumps(
            {**asdict(self), 'api_version': self.api_version},
            sort_keys=True,
            ensure_ascii=False,
            separators=(',', ':'),
        )
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def problems(self) -> list[str]:
        """Structural defects, as ``section: sentence``; empty means the platform is whole."""
        found: list[str] = []
        ident = self.identity
        if self.api_version != API_VERSION:
            found.append(f'api_version: {self.api_version!r} is not the supported {API_VERSION}')
        if ident.kind != 'platform':
            found.append(f'identity.kind: {ident.kind!r} is not the platform tree')
        if not str(ident.id or '').strip():
            found.append('identity.id: empty')
        if not str(ident.version or '').strip():
            found.append('identity.version: empty')
        if ident.title_key != f'platform.{ident.id}':
            found.append(f'identity.title_key: {ident.title_key!r} is not platform.{ident.id}')
        if ident.category not in ('cn', 'overseas'):
            found.append(f'identity.category: {ident.category!r} is not cn/overseas')
        if not str(ident.when_to_use or '').strip():
            found.append('identity.when_to_use: empty')
        if not self.modes:
            found.append('modes: a platform needs at least one mode')
        keys: set[str] = set()
        for mode in self.modes:
            if not str(mode.key or '').strip():
                found.append('modes: a mode has no key')
                continue
            if mode.key in keys:
                found.append(f'modes.{mode.key}: declared twice')
            keys.add(mode.key)
            if not str(mode.label_key or '').strip():
                found.append(f'modes.{mode.key}.label_key: empty')
            if not str(mode.handler or '').strip():
                found.append(f'modes.{mode.key}.handler: empty')
            if mode.collects not in COLLECT_KINDS:
                found.append(f'modes.{mode.key}.collects: {mode.collects!r} is not a known kind')
            for spec in mode.fields:
                if not str(spec.key or '').strip():
                    found.append(f'modes.{mode.key}: a field has no key')
                if spec.minimum is not None and spec.maximum is not None and spec.minimum > spec.maximum:
                    found.append(f'modes.{mode.key}.{spec.key}: minimum above maximum')
        if not str(self.execution.handler or '').strip():
            found.append('execution.handler: empty')
        elif ':' not in self.execution.handler:
            found.append(f'execution.handler: {self.execution.handler!r} is not module:function')
        if not str(self.ai.summary or '').strip():
            found.append('ai.summary: empty')
        if not isinstance(self.ai.template, dict) or not self.ai.template:
            found.append('ai.template: a platform skill needs a template')
        else:
            params = self.ai.template.get('params') or {}
            if self.ai.template.get('type') != 'source':
                found.append('ai.template.type: a platform template is a source node')
            elif params.get('platform') != self.platform:
                found.append(f'ai.template.params.platform: not {self.platform!r}')
            try:
                json.dumps(self.ai.template, ensure_ascii=False)
            except (TypeError, ValueError):
                found.append('ai.template: not JSON-serialisable')
        if not self.tests.contracts:
            found.append('tests.contracts: a platform needs at least one contract test')
        return found


#: The vocabulary of :attr:`Mode.collects`, declared once for the gate and the panel.
COLLECT_KINDS = ('fetch', 'dom_read', 'dom_scroll', 'modal_per_row', 'page_per_row', 'external_app')

#: A literal a generated skill template puts in a required box. A caller replaces it with its own
#: keyword/URL; the design-time check only asks that the box is not blank.
_TEMPLATE_VALUES = {'keyword': '关键词', 'author': '@handle', 'urls': 'https://example.com/item/1'}


def platform_manifest(
    key: str,
    *,
    order: int,
    modes: tuple[Mode, ...],
    crawler: str,
    summary: str,
    when_to_use: str,
    when_not_to_use: tuple[str, ...] = (),
    region: str = 'cn',
    profile_recommended: bool = False,
    serial_only: bool = False,
    parallel_recommended: bool = False,
    version: str = '1.0.0',
) -> PlatformManifest:
    """Build one platform manifest, deriving the skill sections the mode declarations answer."""
    first = modes[0] if modes else None
    step: dict[str, Any] = {'platform': key, 'collect': first.key if first else ''}
    if first is not None:
        for spec in first.fields:
            if spec.required:
                step[spec.key] = _TEMPLATE_VALUES.get(spec.key, '示例')
    template = {'type': 'source', 'params': step}
    session_modes = [mode.key for mode in modes if mode.needs_session]
    prerequisites = [
        'A network this platform answers from: ' + ('国内' if region == 'cn' else '海外（需要对应的网络出口）') + '.'
    ]
    if session_modes:
        prerequisites.append('A saved login for the modes that need one: ' + ', '.join(session_modes) + '.')
    prerequisites.append('Every required box of the chosen mode filled (or fed from an upstream column).')
    steps = [
        f'Put a `source` node with `platform` `{key}` and `collect` one of: '
        + ', '.join(f'`{m.key}`' for m in modes)
        + '.',
        'Fill the mode’s required boxes; a comment walk takes the article/video links.',
        'A mode this machine cannot run is refused by name before the run starts.',
    ]
    failures = [
        'A required box left blank: the refusal names the field (engine.source names it once).',
        'A link that belongs to another platform: the comment walk refuses it by name.',
        'A login wall or risk page: the crawl names it and the run is not silently empty.',
    ]
    if serial_only:
        failures.append('This platform is serial-only: two sessions at once is a login wall (the gate forces 真排队).')
    acceptance = ['The node produced rows, or the refusal named the reason (login wall / risk / captcha).']
    identity = Identity(
        id=key,
        kind='platform',
        version=version,
        title_key=f'platform.{key}',
        category=region,
        order=order,
        description=summary,
        when_to_use=when_to_use,
    )
    ai = Ai(
        summary=summary,
        when_not_to_use=when_not_to_use,
        prerequisites=tuple(prerequisites),
        steps=tuple(steps),
        examples=(template,),
        template=template,
        failures=tuple(failures),
        acceptance=tuple(acceptance),
    )
    return PlatformManifest(
        identity=identity,
        modes=modes,
        profile_recommended=profile_recommended,
        serial_only=serial_only,
        parallel_recommended=parallel_recommended,
        execution=Execution(handler=crawler),
        ai=ai,
        tests=Tests(contracts=('tests/unit/capabilities/test_platform_manifests.py',)),
        docs=Docs(
            page=f'docs/capabilities/platforms/{key}.md',
            skill=f'docs/capabilities/skills/platforms/{key}.md',
        ),
    )
