"""The nine-section capability manifest.

A manifest answers every question a surface used to answer with its own copy of the facts: what a
capability is called, which parameters it takes and what they default to, what shape it carries
downstream, which function runs it, which parameters it refuses before a run, which form widget it
wants, what the AI should know about it, which test proves it, and which document explains it.

The dataclasses are the schema. ``Manifest.problems()`` is the structural half of the completeness
gate: the gate/doctor adds the facts that need the file system (executor import, bilingual keys,
generated artifacts) on top, and refuses by name rather than letting a half-declared capability
reach the canvas.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

#: The manifest wire version. A manifest written for another version is refused by name instead of
#: being interpreted with fields the writer did not mean.
API_VERSION = 1

#: The capability kinds the registry knows. Only ``node`` has manifests in P1; the vocabulary is
#: declared here so an operator/chart/platform manifest is a data change, not a second registry.
KINDS = ('node', 'operator', 'chart', 'platform', 'tool', 'skill')

#: Row shapes a capability can carry downstream. ``nodes/catalog.py`` imports this tuple rather than
#: keeping a second answer: it is the same fact the engine's table/PDF sets are built from.
ROW_SHAPES = ('table', 'pdf', 'none')

_PARAM_TYPES = ('string', 'integer', 'number', 'boolean', 'object', 'array')

#: The widgets the schema form renderer knows. An unknown widget is a named gate failure, not a text
#: box that silently replaces the control the author meant.
WIDGETS = ('text', 'textarea', 'number', 'select', 'switch', 'column', 'dataset', 'json')

_RULE_KINDS = ('required_param', 'enum_param', 'upstream_required', 'no_input', 'requires_output')
_SEVERITIES = ('error', 'warning')
_UI_FORMS = ('schema', 'custom')

_IDENTIFIER = re.compile(r'^[a-z][a-z0-9_]*$')
_VERSION = re.compile(r'^\d+\.\d+\.\d+$')


@dataclass(frozen=True)
class Identity:
    """Section 1: who this capability is, and where its word lives."""

    id: str
    kind: str
    version: str
    title_key: str
    category: str
    #: Position in the served catalogue. Declared here so a migrated capability keeps the slot its
    #: users already know instead of moving to the end when its old table entry is deleted.
    order: int = 1000
    description: str = ''
    when_to_use: str = ''


@dataclass(frozen=True)
class ParamSpec:
    """One parameter: the JSON Schema subset the API/AI/forms read, plus the form hint."""

    name: str
    type: str = 'string'
    default: Any = ''
    required: bool = False
    enum: tuple = ()
    minimum: float | None = None
    maximum: float | None = None
    widget: str = ''
    placeholder: str = ''
    description_key: str = ''

    def schema(self) -> dict:
        """The JSON Schema projection (``required``/UI hints belong to the manifest, not here)."""
        out: dict = {'type': self.type, 'default': copy.deepcopy(self.default)}
        if self.enum:
            out['enum'] = list(self.enum)
        if self.minimum is not None:
            out['minimum'] = self.minimum
        if self.maximum is not None:
            out['maximum'] = self.maximum
        return out


@dataclass(frozen=True)
class Ports:
    """Section 3: what the capability consumes, what shape it carries, what it emits/reads.

    ``emit_columns``/``read_columns`` are ``module:function`` references rather than callables: the
    manifest must stay importable without pandas, and only the lineage view needs to resolve them.
    """

    rows: str = 'table'
    #: ``0`` no input, ``1`` one table, ``-1`` any number. A node with two named inputs declares 2.
    inputs: int = 1
    emit_columns: str = ''
    read_columns: str = ''


@dataclass(frozen=True)
class Execution:
    """Section 4: the lazy ``module:function`` handler and console policy."""

    handler: str = ''
    #: A console-noise decision, not a filtering hook: quiet types omit the generic pair and still
    #: count in every progress total.
    quiet: bool = False


@dataclass(frozen=True)
class Rule:
    """Section 5: one declarative pre-run refusal.

    ``code`` is what the console/badge carries (``engine.*`` today); ``message_key`` is the
    ``i18n`` template the message is worded from. They are separate so a code can stay stable while
    its wording changes.
    """

    kind: str
    code: str
    message_key: str
    param: str = ''
    severity: str = 'error'


@dataclass(frozen=True)
class Ui:
    """Section 6: the default schema form, or the escape hatch that replaces it."""

    form: str = 'schema'
    custom_renderer: str = ''


@dataclass(frozen=True)
class Ai:
    """Section 7: what the AI tools/skills should know. Generated into skills in P6."""

    tool: str = ''
    summary: str = ''
    steps: tuple[str, ...] = ()
    #: Template JSON the AI can send back. Each entry must survive ``json.dumps`` — the gate parses
    #: it so a hand-written example cannot become a tool call the server refuses.
    examples: tuple[dict, ...] = ()
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tests:
    """Section 8: the contract test(s) that prove this capability, repo-relative."""

    contracts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Docs:
    """Section 9: the page that explains the capability, and the generated skill/hash later."""

    page: str = ''
    skill: str = ''
    version_hash: str = ''


@dataclass(frozen=True)
class Manifest:
    """One capability, nine sections. ``api_version`` is pinned by the registry."""

    identity: Identity
    params: tuple[ParamSpec, ...] = ()
    ports: Ports = field(default_factory=Ports)
    execution: Execution = field(default_factory=Execution)
    rules: tuple[Rule, ...] = ()
    #: Node-specific checks a rule cannot express (parent shapes, an operation carried on the node
    #: itself). Each is ``module:function`` returning ``[{code, message_key, context?, severity?}]``;
    #: the function lives with the capability, never in the shared validator.
    validators: tuple[str, ...] = ()
    ui: Ui = field(default_factory=Ui)
    ai: Ai = field(default_factory=Ai)
    tests: Tests = field(default_factory=Tests)
    docs: Docs = field(default_factory=Docs)
    api_version: int = API_VERSION

    def param(self, name: str) -> ParamSpec | None:
        for spec in self.params:
            if spec.name == name:
                return spec
        return None

    def defaults(self) -> dict:
        """The seed parameters a new node starts from — deep-copied so callers cannot poison it."""
        return {spec.name: copy.deepcopy(spec.default) for spec in self.params}

    def as_dict(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        """A stable hash of the declaration. Generated artifacts and docs carry it."""
        payload = json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def problems(self) -> list[str]:
        """Structural defects, as ``section: sentence``; empty means the manifest is whole.

        The completeness gate and ``tools/doctor.py`` both call this, so the two can never disagree
        about what "complete" means. File-system facts (does the executor import, does the doc
        exist) stay in the gate: a manifest itself must be answerable without touching a path.
        """
        found: list[str] = []
        ident = self.identity
        if self.api_version != API_VERSION:
            found.append(f'api_version: {self.api_version!r} is not the supported {API_VERSION}')
        if ident.kind not in KINDS:
            found.append(f'identity.kind: {ident.kind!r} is not one of {", ".join(KINDS)}')
        if not _IDENTIFIER.match(ident.id or ''):
            found.append(f'identity.id: {ident.id!r} is not a lowercase identifier')
        if not _VERSION.match(ident.version or ''):
            found.append(f'identity.version: {ident.version!r} is not MAJOR.MINOR.PATCH')
        if not str(ident.title_key or '').strip():
            found.append('identity.title_key: empty')
        if not str(ident.category or '').strip():
            found.append('identity.category: empty')
        if ident.order < 0:
            found.append(f'identity.order: {ident.order} is negative')

        names: set[str] = set()
        for spec in self.params:
            if not _IDENTIFIER.match(spec.name or ''):
                found.append(f'params.{spec.name}: not a lowercase identifier')
            if spec.name in names:
                found.append(f'params.{spec.name}: declared twice')
            names.add(spec.name)
            if spec.type not in _PARAM_TYPES:
                found.append(f'params.{spec.name}.type: {spec.type!r} is not one of {", ".join(_PARAM_TYPES)}')
            if spec.widget and spec.widget not in WIDGETS:
                found.append(f'params.{spec.name}.widget: {spec.widget!r} is not one of {", ".join(WIDGETS)}')
            if spec.enum and spec.default not in ('', None) and spec.default not in spec.enum:
                found.append(f'params.{spec.name}.default: {spec.default!r} is not in its enum')
            if spec.minimum is not None and spec.maximum is not None and spec.minimum > spec.maximum:
                found.append(f'params.{spec.name}: minimum {spec.minimum} is above maximum {spec.maximum}')
            try:
                json.dumps(spec.default, ensure_ascii=False)
            except (TypeError, ValueError):
                found.append(f'params.{spec.name}.default: not JSON-serialisable')

        if self.ports.rows not in ROW_SHAPES:
            found.append(f'ports.rows: {self.ports.rows!r} is not one of {", ".join(ROW_SHAPES)}')
        if self.ports.inputs < -1:
            found.append(f'ports.inputs: {self.ports.inputs} is not -1/0/1/2…')
        if not str(self.execution.handler or '').strip():
            found.append('execution.handler: empty')
        elif ':' not in self.execution.handler:
            found.append(f'execution.handler: {self.execution.handler!r} is not module:function')

        for rule in self.rules:
            if rule.kind not in _RULE_KINDS:
                found.append(f'rules.{rule.code}: {rule.kind!r} is not one of {", ".join(_RULE_KINDS)}')
            if not str(rule.code or '').strip():
                found.append('rules: a rule has an empty code')
            if not str(rule.message_key or '').strip():
                found.append(f'rules.{rule.code}: empty message_key')
            if rule.severity not in _SEVERITIES:
                found.append(f'rules.{rule.code}.severity: {rule.severity!r} is not one of {", ".join(_SEVERITIES)}')
            if rule.kind in ('required_param', 'enum_param'):
                if rule.param not in names:
                    found.append(f'rules.{rule.code}: param {rule.param!r} is not declared')
                elif rule.kind == 'enum_param' and not self.param(rule.param).enum:
                    found.append(f'rules.{rule.code}: enum_param names a param with no enum')

        for reference in self.validators:
            if not str(reference or '').strip():
                found.append('validators: empty reference')
            elif ':' not in reference:
                found.append(f'validators: {reference!r} is not module:function')

        if self.ui.form not in _UI_FORMS:
            found.append(f'ui.form: {self.ui.form!r} is not one of {", ".join(_UI_FORMS)}')
        if self.ui.form == 'custom' and not str(self.ui.custom_renderer or '').strip():
            found.append('ui.custom_renderer: a custom form needs a renderer id')

        for example in self.ai.examples:
            if not isinstance(example, dict):
                found.append(f'ai.examples: {type(example).__name__} is not an object')
                continue
            try:
                json.dumps(example, ensure_ascii=False)
            except (TypeError, ValueError):
                found.append('ai.examples: an example is not JSON-serialisable')

        if ident.kind == 'node':
            if not self.tests.contracts:
                found.append('tests.contracts: a node needs at least one contract test')
            if not str(self.docs.page or '').strip():
                found.append('docs.page: a node needs a documentation page')
        return found
