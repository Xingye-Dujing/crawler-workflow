"""An analysis operator: one step's contract, shape and skill declared once.

The analysis node runs a pipeline of named operators. Before this module an operator's facts lived in
five places — ``ops/__init__.py`` (the handler), ``contracts.STEP_PARAMS`` (what it refuses),
``params`` (what it writes / how a panel field becomes a kwarg), ``matching.STEP_TWO_TABLE`` and the
node executor's ``EMPTY_BY_DESIGN`` — so adding an operator meant editing five shared tables and the
five could disagree. Here each operator is a manifest in ``capabilities_kernel/operators/<id>/`` and
``services.analysis`` projects those tables from it.

The section vocabulary is the same nine-section capability manifest (identity, params, ports,
execution, rules, ui, ai, tests, docs) with three operator-specific sections:

* ``reads`` — which parameters name a column that must exist, a column subset, a non-blank value or a
  rename mapping, and which two-table keys are checked one side at a time;
* ``writes`` — how the output table is shaped (replace / add a column / pass through / select /
  dynamic names / unknown without the data);
* ``needs_llm`` / ``empty_by_design`` / ``checks`` — the three policies the node executor used to
  keep in its own tables.

The module imports only the standard library and ``capabilities_kernel.manifest``: a manifest is
loaded while the app parses a workflow, so pandas or a service import here would cost every start.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from capabilities_kernel.manifest import (
    API_VERSION,
    KINDS,
    Ai,
    Docs,
    Execution,
    Identity,
    ParamSpec,
    Ports,
    Tests,
    Ui,
)

#: The sentinel a select carries when a blank is a MISSING choice rather than a fallback (a
#: filter with no comparison is a mistyped filter, not "the data was already clean"). It lives here
#: so ``services.analysis.contracts`` re-exports one object instead of inventing a second identity.
NO_DEFAULT = object()

#: How an operator shapes the table it hands downstream.
WRITE_MODES = ('replace', 'add', 'select', 'passthrough', 'dynamic', 'unknown')

#: The placeholder a generated skill template puts in a required column box. It is a literal the
#: engine's design-time check accepts; a caller replaces it with a real column.
_PLACEHOLDERS = {
    'expr': '1',
    'query': '关键词',
    'topics': '5',
    'new_col': '新列',
    'summary_col': '摘要',
    'order_new_col': '序号',
}


@dataclass(frozen=True)
class Reads:
    """Which parameters the step reads from the table, and how strictly.

    ``one`` names exactly one column (a blank or absent name is a mistake, never "every column");
    ``some`` names a subset where an empty list legitimately means every column; ``nonblank`` is a
    parameter that names a new column, a formula or a literal text; ``mapping`` is a rename map;
    ``two_table_keys`` are join keys checked against two different tables, so neither can live in
    ``one`` (the left name is not a column of the right table).
    """

    one: tuple[str, ...] = ()
    some: tuple[str, ...] = ()
    nonblank: tuple[str, ...] = ()
    mapping: bool = False
    two_table_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class Writes:
    """How the output table is shaped, declared rather than re-derived by the lineage view."""

    mode: str = 'passthrough'
    #: ``mode='replace'``: the fixed column set the step emits.
    columns: tuple[str, ...] = ()
    #: ``mode='add'``: ``(canonical param, signature default)`` pairs for the columns it appends.
    add: tuple[tuple[str, str], ...] = ()
    #: ``mode='add'`` with a second, optional column (``bin_time``'s 阶段序号).
    add_maybe: tuple[tuple[str, str], ...] = ()
    #: ``bin_column`` names its column ``f'{column}_bin'`` when the box is blank.
    add_from_column: bool = False


@dataclass(frozen=True)
class OperatorManifest:
    """One analysis operator, the sections the capability kernel and the analysis layer both read."""

    identity: Identity
    params: tuple[ParamSpec, ...] = ()
    reads: Reads = field(default_factory=Reads)
    writes: Writes = field(default_factory=Writes)
    execution: Execution = field(default_factory=Execution)
    #: A step the pipeline hands the run's LLM client, Stop flag and answer store.
    needs_llm: bool = False
    #: Zero rows from a non-empty input is the answer this step was asked for, not an anomaly.
    empty_by_design: bool = False
    #: Design-time checks a parameter table cannot express, as ``module:function`` references.
    checks: tuple[str, ...] = ()
    #: ``(canonical param, browser label key)`` overrides, for a box the panel labels apart.
    labels: tuple[tuple[str, str], ...] = ()
    ui: Ui = field(default_factory=lambda: Ui(form='custom', custom_renderer='analysis'))
    ai: Ai = field(default_factory=Ai)
    tests: Tests = field(default_factory=Tests)
    docs: Docs = field(default_factory=Docs)
    api_version: int = API_VERSION

    # ─── The sections the capability gate asks of every manifest ───

    @property
    def ports(self) -> Ports:
        """An operator carries a table; it declares no node-level lineage hooks."""
        return Ports(rows='table', inputs=1)

    @property
    def rules(self) -> tuple:
        """Refusals are the ``reads`` contract, not a second list of rules."""
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

    # ─── Projections ───

    def param(self, name: str) -> ParamSpec | None:
        for spec in self.params:
            if spec.name == name:
                return spec
        return None

    def defaults(self) -> dict:
        """The seed values a step starts from — deep-copied so callers cannot poison the manifest."""
        return {spec.name: copy.deepcopy(spec.default) for spec in self.params}

    def contract(self) -> dict:
        """The ``STEP_PARAMS`` entry this operator declares.

        ``services.analysis.contracts`` compares exactly this shape, so the validator and the
        manifest cannot disagree about which parameter has to name a column.
        """
        out: dict = {
            'one': tuple(self.reads.one),
            'some': tuple(self.reads.some),
            'nonblank': tuple(self.reads.nonblank),
            'enums': {
                spec.name: (NO_DEFAULT if spec.required else spec.default, tuple(spec.enum))
                for spec in self.params
                if spec.enum
            },
        }
        if self.reads.mapping:
            out['mapping'] = True
        return out

    def labels_map(self) -> dict[str, str]:
        return dict(self.labels)

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
        """Structural defects, as ``section: sentence``; empty means the operator is whole."""
        found: list[str] = []
        ident = self.identity
        if self.api_version != API_VERSION:
            found.append(f'api_version: {self.api_version!r} is not the supported {API_VERSION}')
        if ident.kind not in KINDS:
            found.append(f'identity.kind: {ident.kind!r} is not one of {", ".join(KINDS)}')
        elif ident.kind != 'operator':
            found.append(f'identity.kind: {ident.kind!r} is not the operator tree')
        if not str(ident.id or '').strip():
            found.append('identity.id: empty')
        if not str(ident.version or '').strip():
            found.append('identity.version: empty')
        if not str(ident.title_key or '').strip():
            found.append('identity.title_key: empty')
        if not str(ident.category or '').strip():
            found.append('identity.category: empty')
        if ident.order < 0:
            found.append(f'identity.order: {ident.order} is negative')

        names: set[str] = set()
        for spec in self.params:
            if not str(spec.name or '').strip():
                found.append('params: a parameter has no name')
                continue
            if spec.name in names:
                found.append(f'params.{spec.name}: declared twice')
            names.add(spec.name)
            if spec.enum and spec.default not in ('', None) and spec.default not in spec.enum:
                found.append(f'params.{spec.name}.default: {spec.default!r} is not in its enum')
            try:
                json.dumps(spec.default, ensure_ascii=False)
            except (TypeError, ValueError):
                found.append(f'params.{spec.name}.default: not JSON-serialisable')

        for key in (*self.reads.one, *self.reads.some, *self.reads.nonblank, *self.reads.two_table_keys):
            if key not in names:
                found.append(f'reads: {key!r} is not a declared parameter')
        if self.reads.mapping and self.param('mapping') is None:
            found.append('reads.mapping: no mapping parameter is declared')
        for key in (*self.reads.one, *self.reads.some):
            if self.reads.one and key in self.reads.two_table_keys:
                found.append(f'reads: {key!r} is both a one-column read and a two-table key')

        if self.writes.mode not in WRITE_MODES:
            found.append(f'writes.mode: {self.writes.mode!r} is not one of {", ".join(WRITE_MODES)}')
        elif self.writes.mode == 'replace' and not self.writes.columns:
            found.append('writes.columns: a replace step must name the columns it emits')
        elif self.writes.mode not in ('replace', 'add') and self.writes.columns:
            found.append(f'writes.columns: a {self.writes.mode} step does not declare a fixed column set')
        for param, _default in (*self.writes.add, *self.writes.add_maybe):
            if param not in names:
                found.append(f'writes.add: {param!r} is not a declared parameter')
        if self.writes.add and self.writes.mode != 'add':
            found.append('writes.add: only an add step appends named columns')

        if not str(self.execution.handler or '').strip():
            found.append('execution.handler: empty')
        elif ':' not in self.execution.handler:
            found.append(f'execution.handler: {self.execution.handler!r} is not module:function')

        for reference in self.checks:
            if ':' not in str(reference or ''):
                found.append(f'checks: {reference!r} is not module:function')

        for param, key in self.labels:
            if param not in names:
                found.append(f'labels: {param!r} is not a declared parameter')
            if not str(key or '').strip():
                found.append(f'labels.{param}: empty label key')

        if self.ui.form not in ('schema', 'custom'):
            found.append(f'ui.form: {self.ui.form!r} is not schema/custom')
        if self.ui.form == 'custom' and not str(self.ui.custom_renderer or '').strip():
            found.append('ui.custom_renderer: a custom form needs a renderer id')

        if not str(self.ai.summary or '').strip():
            found.append('ai.summary: empty')
        if not isinstance(self.ai.template, dict) or not self.ai.template:
            found.append('ai.template: an operator skill needs a template')
        else:
            if self.ai.template.get('type') != 'analysis':
                found.append('ai.template.type: an operator template is an analysis node')
            try:
                json.dumps(self.ai.template, ensure_ascii=False)
            except (TypeError, ValueError):
                found.append('ai.template: not JSON-serialisable')
        if not self.tests.contracts:
            found.append('tests.contracts: an operator needs at least one contract test')
        return found


def enum_of(ident: str, param: str) -> tuple[str, ...]:
    """The declared select values of one operator parameter — the one home of that option list.

    ``services.analysis.kernels``/``matching``/``contracts`` publish names like ``FILTER_OPS`` for
    the operations that read them; each is this call, so a value added to the select exists once.
    """
    from capabilities_kernel import registry

    manifest = registry.get('operator', ident)
    if not isinstance(manifest, OperatorManifest):
        raise LookupError(f'no operator manifest {ident!r}')
    spec = manifest.param(param)
    if spec is None or not spec.enum:
        raise LookupError(f'operator {ident!r} declares no select {param!r}')
    return tuple(spec.enum)


def _placeholder(name: str, spec: ParamSpec | None) -> Any:
    if spec is not None and spec.enum:
        return spec.enum[0]
    return _PLACEHOLDERS.get(name, '正文')


def _template(ident: str, params: tuple[ParamSpec, ...], reads: Reads) -> dict:
    """A runnable ``analysis`` node whose one step carries every required box.

    The step is the executor-shaped ``{op, params}`` form, not the panel's flat fields: that is what
    ``run_pipeline`` reads directly, and it keeps a step whose own parameter is called ``op``
    (``filter_rows``' comparison) from overwriting the step name.

    Derived rather than hand-written, so a new required parameter changes the template in the same
    place it is declared. A parameter with a real default keeps it; a required box without one gets a
    literal the design-time check accepts, which a caller replaces with its own column.
    """
    values: dict = {}
    required = list(dict.fromkeys((*reads.one, *reads.nonblank, *reads.two_table_keys)))
    for spec in params:
        if spec.name in required:
            values[spec.name] = spec.default if spec.default not in ('', None) else _placeholder(spec.name, spec)
        elif spec.required and spec.enum and spec.default in ('', None):
            # A select with no fallback (``filter_rows.op``) still has to carry a legal value.
            values[spec.name] = spec.enum[0]
    if reads.mapping:
        values['mapping'] = {'正文': '文本'}
    return {
        'type': 'analysis',
        'params': {'operation': ident, 'steps': json.dumps([{'op': ident, 'params': values}], ensure_ascii=False)},
    }


def _prerequisites(reads: Reads, params: tuple[ParamSpec, ...]) -> tuple[str, ...]:
    lines = ['An upstream table (the analysis node’s input).']
    by_name = {spec.name: spec for spec in params}
    for key in reads.one:
        default = by_name[key].default if key in by_name else ''
        lines.append(f'`{key}` names a column that must exist (default: {default or "none — required"}).')
    for key in reads.some:
        lines.append(f'`{key}` names existing columns; blank means every column.')
    for key in reads.two_table_keys:
        lines.append(f'`{key}` is a key of one of the two incoming tables.')
    if reads.mapping:
        lines.append('`mapping` maps existing columns to their new names.')
    return tuple(lines)


def _steps(ident: str, writes: Writes, extra: Iterable[str]) -> tuple[str, ...]:
    lines = [
        f'Put a step `{{"op": "{ident}", …}}` in the analysis node’s `steps`, or set `operation` to `{ident}`.',
        'A missing column, a blank required box or a value outside a declared select refuses by name.',
    ]
    if writes.mode == 'replace':
        lines.append(
            'The step returns a NEW table with columns ' + ', '.join(f'`{column}`' for column in writes.columns) + '.'
        )
    elif writes.mode == 'add':
        lines.append('The step keeps the upstream columns and appends the column(s) it names.')
    elif writes.mode == 'dynamic':
        lines.append('The step returns a fresh table whose column names come from the step’s own parameters.')
    elif writes.mode == 'unknown':
        lines.append('The output columns depend on the data; read them from the node’s result.')
    lines.extend(extra)
    return tuple(lines)


def _failures(writes: Writes, extra: Iterable[str]) -> tuple[str, ...]:
    lines = [
        'A named column the table does not hold: `analysis.step_col_missing`.',
        'A blank required parameter: `analysis.need_param`.',
        'A value outside a declared select: `analysis.bad_option`.',
    ]
    if writes.mode == 'unknown':
        lines.append('The lineage cannot name this step’s columns without the data; a chart fed by it is unprovable.')
    lines.extend(extra)
    return tuple(lines)


def _acceptance(writes: Writes) -> tuple[str, ...]:
    if writes.mode == 'replace':
        return ('The output table carries exactly: ' + ', '.join(writes.columns) + '.',)
    if writes.mode == 'add':
        return ('Every upstream column is still present, plus the column the step names.',)
    if writes.mode == 'dynamic':
        return ('The output column names equal the parameters the step was given.',)
    if writes.mode == 'unknown':
        return ('The console reports the output shape; a downstream step that names a column is checked against it.',)
    return ('Rows are filtered or reordered; the upstream columns are unchanged.',)


def operator_manifest(
    ident: str,
    *,
    title_key: str,
    category: str,
    order: int,
    summary: str,
    when_to_use: str,
    handler: str,
    params: tuple[ParamSpec, ...] = (),
    reads: Reads | None = None,
    writes: Writes | None = None,
    needs_llm: bool = False,
    empty_by_design: bool = False,
    when_not_to_use: tuple[str, ...] = (),
    steps: tuple[str, ...] = (),
    failures: tuple[str, ...] = (),
    checks: tuple[str, ...] = (),
    labels: tuple[tuple[str, str], ...] = (),
    template_values: dict | None = None,
    version: str = '1.0.0',
) -> OperatorManifest:
    """Build one operator manifest, deriving the sections that are mechanically knowable.

    A skill's prerequisite/steps/failure/acceptance sections follow from ``reads``/``writes``; only
    the words a router selects on (``summary``/``when_to_use``/``when_not_to_use``) and any
    op-specific sentence are authored. The template is generated from the required parameters, so it
    cannot name a box the manifest does not declare.
    """
    reads = reads or Reads()
    writes = writes or Writes()
    template = _template(ident, params, reads)
    if template_values:
        step = json.loads(template['params']['steps'])[0]
        step['params'].update(template_values)
        template['params']['steps'] = json.dumps([step], ensure_ascii=False)
    identity = Identity(
        id=ident,
        kind='operator',
        version=version,
        title_key=title_key,
        category=category,
        order=order,
        description=summary,
        when_to_use=when_to_use,
    )
    ai = Ai(
        summary=summary,
        when_not_to_use=when_not_to_use,
        prerequisites=_prerequisites(reads, params),
        steps=_steps(ident, writes, steps),
        examples=(template,),
        template=template,
        failures=_failures(writes, failures),
        acceptance=_acceptance(writes),
    )
    return OperatorManifest(
        identity=identity,
        params=params,
        reads=reads,
        writes=writes,
        execution=Execution(handler=handler),
        needs_llm=needs_llm,
        empty_by_design=empty_by_design,
        checks=checks,
        labels=labels,
        ai=ai,
        tests=Tests(contracts=('tests/unit/capabilities/test_operator_manifests.py',)),
        docs=Docs(
            page=f'docs/capabilities/operators/{ident}.md', skill=f'docs/capabilities/skills/operators/{ident}.md'
        ),
    )
