"""One declaration per chart type — the registry every other chart layer derives from.

Before this table a chart type was named in several places that could each be edited alone:
``visualizer.CHART_TYPES`` (which types exist, in panel order), ``ECHARTS_ONLY_TYPES`` (what
matplotlib cannot draw), ``LATEX_UNBUILDABLE_TYPES`` (what has no paper twin),
``contracts.BIBLIO_CHART_TYPES``/``BIBLIO_CHART_READS`` (the bibliometric views and the columns
each requires) and ``NO_X_TYPES`` — five sets, one concept. Adding a chart meant editing all of
them in lockstep, and one miss was a figure that rendered but never printed.

``SPECS`` is now the single answer. The module-level tuples the rest of the code (and its tests)
already import are **derived** below, so their names and order did not change. Adding a type is
one ``ChartSpec`` line here plus its builder — the contract tests in
``tests/unit/charts/test_chart_registry.py`` refuse a spec whose builder, LaTeX twin or browser word is
missing.

The same table also declares which FIELDS a chart reads (:class:`FieldSpec`) and which extra
controls its form offers (``controls``). ``chart_problems`` is the data-free half of validation
(a required box is blank), ``chart_profiles`` is the browser projection the settings panel renders,
and ``nodes.executors.visualize.read_columns`` is derived from the fields — one declaration, three
surfaces, none of them allowed a second copy.
"""

from __future__ import annotations

import math

from capabilities_kernel import registry
from capabilities_kernel.chart import (
    FAMILY_BIBLIO,
    FAMILY_CONSOLE,
    FIELD_ROLES,
    NUMERIC_ROLES,
    ChartSpec,
)

__all__ = ['FAMILY_BIBLIO', 'FAMILY_CONSOLE', 'FIELD_ROLES', 'NUMERIC_ROLES', 'ChartSpec']

#: The chart a blank ``chart_type`` means. The visualize manifest declares the same value as its
#: parameter default; ``test_visualize_manifest`` pins the two together so this is a link, not a
#: second opinion.
DEFAULT_CHART = 'bar'


#: Panel order: the console types first (bar … network), then the bibliometric block the Data Source
#: panel and the LaTeX writer both walk in this order, then the two late additions (wordcloud, map)
#: that have always been listed after it. Each chart's declaration — its fields, its engine flags,
#: its skill — lives in ``capabilities_kernel/charts/<id>/manifest.py``; this tuple is that tree's
#: projection, ordered by the manifest's declared slot.
SPECS: tuple[ChartSpec, ...] = tuple(registry.manifests('chart'))

_BY_KEY = {spec.key: spec for spec in SPECS}

CHART_TYPES = tuple(spec.key for spec in SPECS)
BIBLIO_CHART_TYPES = tuple(spec.key for spec in SPECS if spec.family == FAMILY_BIBLIO)
ECHARTS_ONLY_TYPES = tuple(spec.key for spec in SPECS if spec.echarts_only)
LATEX_UNBUILDABLE_TYPES = tuple(spec.key for spec in SPECS if not spec.latex_buildable)
NO_X_TYPES = frozenset(spec.key for spec in SPECS if spec.no_x)
BIBLIO_CHART_READS = {spec.key: spec.reads for spec in SPECS if spec.reads}
ANNOTATED_TYPES = tuple(spec.key for spec in SPECS if 'annotations' in spec.controls)


def spec_for(chart_type: str) -> ChartSpec | None:
    """The declaration for *chart_type*, or ``None`` for a blank/unknown value.

    Strict on purpose: an HTTP preview or an AI chart spec that names no type is refused, not
    quietly drawn as a bar. The node executor and validation treat a BLANK type as the declared
    default (``DEFAULT_CHART``) because a new node's manifest default is exactly that value.
    """
    return _BY_KEY.get(str(chart_type or '').strip())


def effective_chart_key(chart_type: str) -> str:
    """The chart a node really draws: its stored type, or the declared default when blank."""
    return str(chart_type or '').strip() or DEFAULT_CHART


def with_chart_defaults(chart_type: str, fields: dict) -> dict:
    """A copy of *fields* with every blank box this chart type declares a default for filled.

    One declaration (``ChartSpec.defaults``) serves the node executor and the HTTP preview, so the
    ``/api/visualize/render`` caller and a saved canvas cannot disagree about what an untouched
    topic chart reads. A typed value always wins; only absent/blank fields are filled.
    """
    result = dict(fields or {})
    spec = spec_for(effective_chart_key(chart_type))
    for key, value in spec.defaults if spec else ():
        if not str(result.get(key) or '').strip():
            result[key] = value
    return result


def is_biblio(chart_type: str) -> bool:
    spec = spec_for(chart_type)
    return bool(spec and spec.family == FAMILY_BIBLIO)


def _blank(value) -> bool:
    return not str(value if value is not None else '').strip()


def chart_problems(chart_type: str, params: dict) -> list[dict]:
    """Every field this chart cannot be built without, as data — no table needed.

    The other half of a chart contract is the FIELD'S TYPE (a scatter needs numbers, a pie cannot
    draw a negative share); that needs a sample of the upstream rows and belongs to the preflight.
    Here a required box is judged against the declared defaults first, so an untouched 主题距离图
    is not "missing pc1" — the contract already answered that.

    An unknown type is refused BY NAME rather than falling through to a bar chart: a stored value
    the registry no longer serves is a chart the user asked for and will not get. The declared
    default is offered as the fix, because that is what a fresh node starts with.
    """
    chart = effective_chart_key(chart_type)
    spec = spec_for(chart)
    if spec is None:
        return [
            {
                'code': 'engine.chart_unknown',
                'message_key': 'engine.chart_unknown',
                'severity': 'error',
                'param': 'chart_type',
                'context': {'chart': chart, 'allowed': ', '.join(CHART_TYPES)},
                'fix': {'set': {'chart_type': DEFAULT_CHART}},
            },
        ]
    effective = with_chart_defaults(chart, params)
    found: list[dict] = []
    for field in spec.fields:
        required = field.required or (bool(field.required_when) and not _blank(effective.get(field.required_when)))
        if required and _blank(effective.get(field.name)):
            found.append(
                {
                    'code': 'engine.chart_field_missing',
                    'message_key': 'engine.chart_field_missing',
                    'severity': 'error',
                    'param': field.name,
                    'context': {'chart': chart, 'field': field.name},
                },
            )
    for group in spec.any_of:
        if all(_blank(effective.get(name)) for name in group):
            found.append(
                {
                    'code': 'engine.chart_field_group_missing',
                    'message_key': 'engine.chart_field_group_missing',
                    'severity': 'error',
                    'param': group[0],
                    'context': {'chart': chart, 'fields': ', '.join(group)},
                },
            )
    return found


def _blank_cell(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN: a cell pandas left empty, not a text value
        return True
    return not str(value).strip()


def _cell_number(value) -> float | None:
    """The cell as a finite number, or None — the one reading the preflight applies."""
    if isinstance(value, bool) or _blank_cell(value):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        try:
            number = float(str(value).strip())
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _field_columns(field, value: str) -> list[str]:
    if field.role == 'list':
        return [part.strip() for part in value.replace('，', ',').split(',') if part.strip()]
    return [value]


def chart_preflight(chart_type: str, params: dict, sample) -> list[dict]:
    """What a SAMPLE of the upstream rows proves about this chart's VALUE contract.

    The missing-column half is the data contract's: ``services.validation.engine`` compares the
    chart's declared reads with the producer's recorded (or declared) schema, so a rename is named
    before any run without this function having to guess from 200 rows. What only data can answer
    stays here:

    * a value/coordinate/list column holding at least one non-blank cell and NO number at all is
      the ``chart.y_not_numeric`` refusal the builders make. An all-blank column is NOT reported:
      the builders draw it as an empty chart rather than refuse, and the preflight mirrors that.

    A sample cannot prove a pie share is negative after ALL rows are aggregated — more positive
    rows can flip a sum — so that refusal stays at run time. A preflight that guessed would refuse
    runs that would have succeeded, which is the failure mode this project bans.
    """
    chart = effective_chart_key(chart_type)
    spec = spec_for(chart)
    rows = [row for row in (sample or []) if isinstance(row, dict)]
    if spec is None or not rows:
        return []
    effective = with_chart_defaults(chart, params)
    present: set[str] = set()
    for row in rows:
        present.update(str(key) for key in row)
    found: list[dict] = []
    for field in spec.fields:
        if field.role not in NUMERIC_ROLES:
            continue
        value = str(effective.get(field.name) or '').strip()
        if not value:
            continue
        for column in _field_columns(field, value):
            if column not in present:
                continue
            has_text = False
            has_number = False
            for row in rows:
                cell = row.get(column)
                if _blank_cell(cell):
                    continue
                if _cell_number(cell) is None:
                    has_text = True
                else:
                    has_number = True
            if has_text and not has_number:
                found.append(
                    {
                        'code': 'engine.chart_column_not_numeric',
                        'message_key': 'engine.chart_column_not_numeric',
                        'severity': 'error',
                        'param': field.name,
                        'context': {'chart': chart, 'column': column},
                    },
                )
    return found


def chart_profiles() -> list[dict]:
    """The browser projection of every chart type: fields, controls and display defaults.

    ``/api/node-types`` serves it and the generated cold-page catalogue carries the same bytes, so
    the settings panel renders the boxes this table declares instead of keeping its own map of
    which chart shows which field. Validation reads the same fields, so a box the user can fill is
    a box a run accepts.
    """
    return [
        {
            'key': spec.key,
            'family': spec.family,
            'echartsOnly': spec.echarts_only,
            'latexBuildable': spec.latex_buildable,
            'tokenize': spec.tokenize_compatible,
            'labelKey': spec.label_key,
            'hintKey': spec.hint_key,
            'defaults': dict(spec.defaults),
            'fields': [
                {
                    'name': field.name,
                    'role': field.role,
                    'required': field.required,
                    'labelKey': field.label_key,
                    'placeholder': field.placeholder,
                    'placeholderKey': field.placeholder_key,
                    'hintKey': field.hint_key,
                    'control': field.control,
                }
                for field in spec.fields
            ],
            'controls': list(spec.controls),
        }
        for spec in SPECS
    ]
