"""A chart type: the boxes it reads, the shape it draws, and the skill that selects it.

``services.charts.registry`` was already ONE declaration for a chart type (its fields, defaults,
family, engine flags), so this module does not re-declare those facts — it adds the sections a
capability needs and moves the declaration into the capability tree
(``capabilities_kernel/charts/<id>/manifest.py``):

* identity (the panel slot, the ``chart.<id>`` word),
* the AI skill (when to draw this chart rather than a neighbour, the fields it needs, its refusals),
* the documentation pages the generator renders,
* the contract test that proves it.

The chart fields are a shared vocabulary (``capabilities_kernel/charts/_fields.py``): a bar's x and
a pie's x are the same box, so declaring them once keeps two charts from labelling one column twice.

The module imports only the standard library and ``capabilities_kernel.manifest``: manifests load
while a workflow is parsed, and pandas or a builder import here would cost every start.
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

#: Where a chart type is built and what it reads, not a cosmetic grouping: ``console`` types are
#: drawn by ``charts.visualizer`` from a user's table and columns, ``biblio`` types are drawn by
#: ``services.biblio.charts`` from the fixed columns the ``biblio`` node writes.
FAMILY_CONSOLE = 'console'
FAMILY_BIBLIO = 'biblio'
FAMILIES = (FAMILY_CONSOLE, FAMILY_BIBLIO)

#: What a chart's field must HOLD, not which widget draws it. ``category`` groups rows,
#: ``category2`` is the second grouping axis (heatmap), ``value`` is aggregated, ``coordinate`` is a
#: numeric position (topic map), ``source``/``target`` name the two ends of a flow, ``text`` and
#: ``geo`` are drawn as labels, ``list`` names several columns at once (stacked shares), and
#: ``label`` names each mark. The type half of validation (does the named column hold numbers?)
#: needs a sample of the rows and belongs to the preflight; the role is what tells it which columns
#: to coerce.
FIELD_ROLES = (
    'category',
    'category2',
    'value',
    'coordinate',
    'source',
    'target',
    'text',
    'geo',
    'list',
    'label',
    'column',
)

#: Field roles whose named column must hold a number for the builder to draw anything. ``list`` is
#: a comma-joined set of such columns (stacked shares); the rest are drawn as labels or groups.
NUMERIC_ROLES = ('value', 'coordinate', 'list')

#: A literal a generated skill template puts in each role's box: a caller replaces it with a real
#: column. Distinct words beat "c" for every box because the template is also documentation.
_ROLE_PLACEHOLDER = {
    'category': '分类',
    'category2': '分类2',
    'value': '数值',
    'coordinate': '数值',
    'source': '来源',
    'target': '目标',
    'text': '文本',
    'geo': '地区',
    'list': '甲占比, 乙占比',
    'label': '标签',
    'column': '列',
}


@dataclass(frozen=True)
class FieldSpec:
    """One parameter that names a column (or a list of columns) in the upstream table."""

    name: str
    role: str
    required: bool = True
    #: The form's label for this box. A chart-specific word ("Category 1" for a heatmap's x) is the
    #: reason this is declared per field instead of computed from the role.
    label_key: str = ''
    #: A literal example, or the key of a localised one.
    placeholder: str = ''
    placeholder_key: str = ''
    hint_key: str = ''
    #: A widget rendered directly under this field: ``agg``/``agg2`` for an aggregated value.
    control: str = ''
    #: The name of another field that makes this one required: a box plot's x is optional for a
    #: single numeric column but mandatory once a y grouping value is named.
    required_when: str = ''


@dataclass(frozen=True)
class ChartSpec:
    """One chart type, declared once: the nine capability sections plus the chart contract."""

    identity: Identity
    fields: tuple[FieldSpec, ...] = ()
    family: str = FAMILY_CONSOLE
    #: True when the type can only be drawn by ECharts (matplotlib has no honest twin).
    echarts_only: bool = False
    #: False when the type has no LaTeX figure/table twin at all (only the agreement matrix).
    latex_buildable: bool = True
    #: REQUIRED columns (bibliometric views). Optional decorating columns are read when present and
    #: documented at the builder; a missing hard read is a named refusal.
    reads: tuple[str, ...] = ()
    #: Field defaults this type's contract names: ``(param, column)``. A blank box means "use the
    #: contract" — an untouched 主题距离图 / 显著词图 node used to refuse at RUN time (after the
    #: upstream crawl was paid for) because nobody had typed ``pc1``/``term`` into the panel.
    defaults: tuple[tuple[str, str], ...] = ()
    #: At least one field of each group must be filled (a box plot takes a category + value pair, or
    #: one numeric column). A group is a NAMED refusal, never a guess at which one was meant.
    any_of: tuple[tuple[str, ...], ...] = ()
    #: Free-standing controls after the fields (``annotations``, ``center_node``, ``tokenize``,
    #: ``wordcloud_style``). ``agg``/``agg2`` ride on their field instead.
    controls: tuple[str, ...] = ()
    #: A sentence under the fields (an i18n key): what this whole chart reads.
    hint_key: str = ''
    #: True when the chart can read a 分词 node's word/frequency columns.
    tokenize_compatible: bool = False
    execution: Execution = field(default_factory=Execution)
    ui: Ui = field(default_factory=lambda: Ui(form='custom', custom_renderer='visualize'))
    ai: Ai = field(default_factory=Ai)
    tests: Tests = field(default_factory=Tests)
    docs: Docs = field(default_factory=Docs)
    api_version: int = API_VERSION

    # ─── The vocabulary the chart layer already read from a spec ───

    @property
    def key(self) -> str:
        return self.identity.id

    @property
    def label_key(self) -> str:
        return self.identity.title_key

    @property
    def no_x(self) -> bool:
        """True when the type has no x field of its own (the biblio views and the agreement matrix)."""
        return not any(spec.name == 'x_field' for spec in self.fields)

    # ─── The sections the capability gate asks of every manifest ───

    @property
    def params(self) -> tuple[ParamSpec, ...]:
        """A chart's parameters are its fields, which carry a role the schema form cannot express."""
        return ()

    @property
    def ports(self) -> Ports:
        return Ports(rows='pdf', inputs=-1)

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
        """A chart has no flat parameter list; its parameters are its fields."""
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
        """Structural defects, as ``section: sentence``; empty means the chart is whole."""
        found: list[str] = []
        ident = self.identity
        if self.api_version != API_VERSION:
            found.append(f'api_version: {self.api_version!r} is not the supported {API_VERSION}')
        if ident.kind != 'chart':
            found.append(f'identity.kind: {ident.kind!r} is not the chart tree')
        if not str(ident.id or '').strip():
            found.append('identity.id: empty')
        if not str(ident.version or '').strip():
            found.append('identity.version: empty')
        if ident.title_key != f'chart.{ident.id}':
            found.append(f'identity.title_key: {ident.title_key!r} is not chart.{ident.id}')
        if ident.category != self.family:
            found.append(f'identity.category: {ident.category!r} is not the family {self.family!r}')
        if self.family not in FAMILIES:
            found.append(f'family: {self.family!r} is not one of {", ".join(FAMILIES)}')
        if ident.order < 0:
            found.append(f'identity.order: {ident.order} is negative')

        names = [spec.name for spec in self.fields]
        if len(names) != len(set(names)):
            found.append('fields: a field name is declared twice')
        for spec in self.fields:
            if spec.role not in FIELD_ROLES:
                found.append(f'fields.{spec.name}.role: {spec.role!r} is not one of {", ".join(FIELD_ROLES)}')
            if spec.required_when and spec.required_when not in names:
                found.append(f'fields.{spec.name}.required_when: {spec.required_when!r} is not a declared field')
            if not str(spec.label_key or '').strip():
                found.append(f'fields.{spec.name}.label_key: empty')
        for group in self.any_of:
            for name in group:
                if name not in names:
                    found.append(f'any_of: {name!r} is not a declared field')
        for name, _value in self.defaults:
            if name not in names:
                found.append(f'defaults: {name!r} is not a declared field')
        for control in self.controls:
            if not str(control or '').strip():
                found.append('controls: empty control name')

        if self.family == FAMILY_BIBLIO and not self.reads:
            found.append('reads: a bibliometric view must name the columns it reads')

        if not str(self.execution.handler or '').strip():
            found.append('execution.handler: empty')
        elif ':' not in self.execution.handler:
            found.append(f'execution.handler: {self.execution.handler!r} is not module:function')

        if self.ui.form not in ('schema', 'custom'):
            found.append(f'ui.form: {self.ui.form!r} is not schema/custom')
        if self.ui.form == 'custom' and not str(self.ui.custom_renderer or '').strip():
            found.append('ui.custom_renderer: a custom form needs a renderer id')

        if not str(self.ai.summary or '').strip():
            found.append('ai.summary: empty')
        if not isinstance(self.ai.template, dict) or not self.ai.template:
            found.append('ai.template: a chart skill needs a template')
        else:
            params = self.ai.template.get('params')
            if self.ai.template.get('type') != 'visualize':
                found.append('ai.template.type: a chart template is a visualize node')
            elif not isinstance(params, dict) or params.get('chart_type') != self.key:
                found.append(f'ai.template.params.chart_type: not {self.key!r}')
            try:
                json.dumps(self.ai.template, ensure_ascii=False)
            except (TypeError, ValueError):
                found.append('ai.template: not JSON-serialisable')
        if not self.tests.contracts:
            found.append('tests.contracts: a chart needs at least one contract test')
        return found


def _template(
    key: str,
    fields: tuple[FieldSpec, ...],
    defaults: tuple[tuple[str, str], ...],
    any_of: tuple[tuple[str, ...], ...],
) -> dict:
    """A visualize node that fills every box this chart declares.

    A declared default wins (an untouched 主题距离图 is not "missing pc1"); a required box — or a
    member of an ``any_of`` group, which is how "one of x/y is enough" is written — without a
    default gets its role's literal, which a caller replaces with a real column.
    """
    declared = dict(defaults)
    grouped = {name for group in any_of for name in group}
    params: dict = {'chart_type': key}
    for spec in fields:
        if spec.name in declared:
            params[spec.name] = declared[spec.name]
        elif spec.required or spec.name in grouped:
            params[spec.name] = spec.placeholder or _ROLE_PLACEHOLDER.get(spec.role, '列')
    return {'type': 'visualize', 'params': params}


def _field_sentence(spec: FieldSpec) -> str:
    need = '必填' if spec.required else '可选'
    when = f'（{spec.required_when} 已填时必填）' if spec.required_when else ''
    return f'`{spec.name}`（{spec.role}，{need}{when}）'


def chart_manifest(
    key: str,
    *,
    order: int,
    family: str,
    handler: str,
    summary: str,
    when_to_use: str,
    when_not_to_use: tuple[str, ...] = (),
    fields: tuple[FieldSpec, ...] = (),
    defaults: tuple[tuple[str, str], ...] = (),
    reads: tuple[str, ...] = (),
    any_of: tuple[tuple[str, ...], ...] = (),
    controls: tuple[str, ...] = (),
    hint_key: str = '',
    tokenize_compatible: bool = False,
    echarts_only: bool | None = None,
    latex_buildable: bool = True,
    version: str = '1.0.0',
) -> ChartSpec:
    """Build one chart manifest, deriving the skill sections the field contract already answers."""
    if echarts_only is None:
        # Every bibliometric view is a network/layout figure with no matplotlib implementation in
        # this app; a console type has a twin unless it declares otherwise.
        echarts_only = family == FAMILY_BIBLIO
    template = _template(key, fields, defaults, any_of)
    prerequisites = ['An upstream table (the visualize node’s input).']
    if reads:
        prerequisites.append('Columns written by 文献分析: ' + ', '.join(f'`{column}`' for column in reads) + '.')
    if fields:
        prerequisites.append('These boxes: ' + ', '.join(_field_sentence(spec) for spec in fields) + '.')
    steps = [
        f'Set the visualize node’s `chart_type` to `{key}`.',
        'Fill each required box with a column of the upstream table.',
    ]
    steps += [f'`{spec.name}` reads a {spec.role} column.' for spec in fields if spec.required]
    if controls:
        steps.append('Optional controls: ' + ', '.join(controls) + '.')
    failures = [
        'A required box is blank: engine.chart_field_missing names the chart and the box.',
        'A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).',
        'A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.',
    ]
    if any_of:
        failures.append('A required group left entirely blank: engine.chart_field_group_missing.')
    acceptance = ['The chart option or image exists for the run.', 'A missing required box is named before the run.']
    identity = Identity(
        id=key,
        kind='chart',
        version=version,
        title_key=f'chart.{key}',
        category=family,
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
    return ChartSpec(
        identity=identity,
        fields=fields,
        family=family,
        echarts_only=echarts_only,
        latex_buildable=latex_buildable,
        reads=reads,
        defaults=defaults,
        any_of=any_of,
        controls=controls,
        hint_key=hint_key,
        tokenize_compatible=tokenize_compatible,
        execution=Execution(handler=handler),
        ai=ai,
        tests=Tests(contracts=('tests/unit/capabilities/test_chart_manifests.py',)),
        docs=Docs(
            page=f'docs/capabilities/charts/{key}.md',
            skill=f'docs/capabilities/skills/charts/{key}.md',
        ),
    )


def field_placeholder(spec: FieldSpec) -> str:
    """The literal a caller can paste into a skill template for one field."""
    return spec.placeholder or _ROLE_PLACEHOLDER.get(spec.role, '列')


def as_serialisable(value: Any) -> Any:
    """``value`` as JSON data (a tuple becomes a list); the generator's one normaliser."""
    return json.loads(json.dumps(value, ensure_ascii=False))
