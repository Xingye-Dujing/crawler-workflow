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

from dataclasses import dataclass

#: A chart family is where the type is built and what it reads, not a cosmetic grouping:
#: ``console`` types are drawn by ``charts.visualizer`` from a user's table and columns,
#: ``biblio`` types are drawn by ``charts.biblio`` from the fixed columns the ``biblio`` node
#: writes (their required column names are the contract a rename breaks by name).
FAMILY_CONSOLE = 'console'
FAMILY_BIBLIO = 'biblio'

#: What a chart's field must HOLD, not which widget draws it. ``category`` groups rows,
#: ``category2`` is the second grouping axis (heatmap), ``value`` is aggregated, ``coordinate`` is
#: a numeric position (topic map), ``source``/``target`` name the two ends of a flow, ``text`` and
#: ``geo`` are drawn as labels, ``list`` names several columns at once (stacked shares), and
#: ``label`` names each mark. The type half of validation (does the named column hold numbers?)
#: needs a sample of the rows and is the preflight's question; the role is what tells it which
#: columns to coerce.
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

#: The chart a blank ``chart_type`` means. The visualize manifest declares the same value as its
#: parameter default; ``test_visualize_manifest`` pins the two together so this is a link, not a
#: second opinion.
DEFAULT_CHART = 'bar'


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
    """One chart type, declared once."""

    key: str
    family: str
    #: True when the type can only be drawn by ECharts (matplotlib has no honest twin).
    echarts_only: bool = False
    #: False when the type has no LaTeX figure/table twin at all (only the agreement matrix).
    latex_buildable: bool = True
    #: REQUIRED columns (bibliometric views). Optional decorating columns are read when present
    #: and are documented at the builder; a missing hard read is a named refusal.
    reads: tuple[str, ...] = ()
    #: Field defaults this type's contract names: ``(param, column)``. A blank box means "use the
    #: contract" — an untouched 主题距离图 / 显著词图 node used to refuse at RUN time (after the
    #: upstream crawl was paid for) because nobody had typed ``pc1``/``term`` into the panel.
    defaults: tuple[tuple[str, str], ...] = ()
    #: The parameters this chart reads from the upstream table, in form order. A required field
    #: absent from the effective parameters is refused before a run; its role is what the
    #: preflight checks the column's values against.
    fields: tuple[FieldSpec, ...] = ()
    #: At least one field of each group must be filled (a box plot takes a category + value pair,
    #: or one numeric column). A group is a NAMED refusal, never a guess at which one was meant.
    any_of: tuple[tuple[str, ...], ...] = ()
    #: Free-standing controls after the fields (``annotations``, ``center_node``, ``tokenize``,
    #: ``wordcloud_style``). ``agg``/``agg2`` ride on their field instead, so the box stays beside
    #: the value it aggregates.
    controls: tuple[str, ...] = ()
    #: A sentence under the fields (an i18n key): what this whole chart reads.
    hint_key: str = ''
    #: True when the chart can read a 分词 node's word/frequency columns — the panel offers the
    #: simplified tokenize-upstream form only for these.
    tokenize_compatible: bool = False

    @property
    def label_key(self) -> str:
        return f'chart.{self.key}'

    @property
    def no_x(self) -> bool:
        """True when the type has no x field of its own (the biblio views and the agreement matrix)."""
        return not any(field.name == 'x_field' for field in self.fields)


def _biblio(key: str, reads: tuple[str, ...], *, echarts_only: bool = True) -> ChartSpec:
    return ChartSpec(
        key,
        FAMILY_BIBLIO,
        echarts_only=echarts_only,
        reads=reads,
        hint_key='biblio.ui.chartHint',
    )


# ─── The fields a chart reads ───
# Declared once per role of the table, not per type: a bar's x and a pie's x are the same box,
# while a heatmap's two axes are two categories. The form labels are the ones the panel has always
# shown, now carried by the declaration instead of a JavaScript map.
_X_CATEGORY = FieldSpec(
    'x_field',
    'category',
    label_key='settings.xField',
    placeholder_key='settings.fieldPlaceholderCategory',
)
_X_CATEGORY2 = FieldSpec(
    'x_field',
    'category2',
    label_key='settings.xFieldCat1',
    placeholder_key='settings.fieldPlaceholderCategory',
)
_X_SOURCE = FieldSpec(
    'x_field',
    'source',
    label_key='settings.sourceField',
    placeholder_key='settings.fieldPlaceholderSource',
)
_X_TEXT = FieldSpec(
    'x_field',
    'text',
    label_key='settings.textField',
    placeholder_key='settings.fieldPlaceholderText',
)
_X_GEO = FieldSpec(
    'x_field',
    'geo',
    label_key='settings.regionField',
    placeholder_key='settings.fieldPlaceholderGeo',
)
_X_COORDINATE = FieldSpec(
    'x_field',
    'coordinate',
    label_key='settings.xField',
    placeholder_key='settings.fieldPlaceholderNumeric',
)
_X_VALUE = FieldSpec(
    'x_field',
    'value',
    label_key='settings.xField',
    placeholder_key='settings.fieldPlaceholderNumeric',
)
_X_OPTIONAL = FieldSpec(
    'x_field',
    'category',
    required=False,
    label_key='settings.xField',
    placeholder_key='settings.fieldPlaceholderCategory',
    # A box plot's single numeric column lives in x with no y; naming a y makes this the grouping
    # axis, which the builder refuses to run without.
    required_when='y_field',
)
_Y_VALUE = FieldSpec(
    'y_field',
    'value',
    required=False,
    label_key='settings.yField',
    placeholder_key='settings.fieldPlaceholderValue',
    control='agg',
)
_Y_VALUE_REQUIRED = FieldSpec(
    'y_field',
    'value',
    label_key='settings.yField',
    placeholder_key='settings.fieldPlaceholderNumeric',
)
_Y_COORDINATE = FieldSpec(
    'y_field',
    'coordinate',
    label_key='settings.yField',
    placeholder_key='settings.fieldPlaceholderNumeric',
)
_Y_CATEGORY2 = FieldSpec(
    'y_field',
    'category2',
    label_key='settings.yFieldCat2',
    placeholder_key='settings.fieldPlaceholderCategory',
)
_Y_TARGET = FieldSpec(
    'y_field',
    'target',
    label_key='settings.targetField',
    placeholder_key='settings.fieldPlaceholderTarget',
)
_Y2_VALUE = FieldSpec(
    'y2_field',
    'value',
    label_key='settings.y2Field',
    placeholder_key='settings.fieldPlaceholderRightAxis',
    control='agg2',
)
_VALUE_FIELD = FieldSpec(
    'value_field',
    'value',
    required=False,
    label_key='settings.valueField',
    placeholder_key='settings.fieldPlaceholderWeight',
)
#: The same box where the value is AGGREGATED per category/cell (heatmap, sankey, network): the
#: aggregation control belongs to the column it reduces, so it rides on the field.
_VALUE_FIELD_AGG = FieldSpec(
    'value_field',
    'value',
    required=False,
    label_key='settings.valueField',
    placeholder_key='settings.fieldPlaceholderWeight',
    control='agg',
)
_LABEL_FIELD = FieldSpec('label_field', 'label', required=False, label_key='settings.labelField')
_STACK_FIELDS = FieldSpec(
    'stack_fields',
    'list',
    label_key='settings.stackFields',
    placeholder='积极占比, 中性占比, 消极占比',
    hint_key='hint.stackFields',
)
#: The agreement matrix reads a tidy multi-model table by its own columns. The two the analysis
#: step writes carry defaults, so a fresh chart needs no typing; a renamed column refuses by name.
_MODEL_FIELD = FieldSpec('model_field', 'column', label_key='settings.modelField')
_AGREEMENT_LABEL_FIELD = FieldSpec(
    'agreement_label_field',
    'column',
    required=False,
    label_key='settings.agreementLabelField',
    placeholder='emotion / tendency / sentiment',
)
_ID_FIELD = FieldSpec('id_field', 'column', label_key='settings.idField')


#: Panel order: the console types first (bar … network), then the bibliometric block the
#: Data Source panel and the LaTeX writer both walk in this order, then the two late additions
#: (wordcloud, map) that have always been listed after it.
#:
#: Why the ECharts-only flags read the way they do: the word cloud, the sankey layout and the
#: GeoJSON map have no matplotlib implementation in this app at all. ``dual_line`` joins them
#: for a different reason — a second axis is drawable with ``twinx()``, but the right-hand scale,
#: legend and shared tooltip are the parts that make 热度 and 强度 readable on one figure, and
#: re-implementing them per engine is how the two engines start telling the same data
#: differently. Every bibliometric view is ECharts-only because it is a network/layout figure.
SPECS: tuple[ChartSpec, ...] = (
    ChartSpec(
        'bar',
        FAMILY_CONSOLE,
        fields=(_X_CATEGORY, _Y_VALUE),
        controls=('annotations',),
        tokenize_compatible=True,
    ),
    ChartSpec(
        'line',
        FAMILY_CONSOLE,
        fields=(_X_CATEGORY, _Y_VALUE),
        controls=('annotations',),
    ),
    ChartSpec(
        'dual_line',
        FAMILY_CONSOLE,
        echarts_only=True,
        fields=(_X_CATEGORY, _Y_VALUE, _Y2_VALUE),
        controls=('annotations',),
        hint_key='hint.dualLine',
    ),
    ChartSpec('stack_pct', FAMILY_CONSOLE, fields=(_X_CATEGORY, _STACK_FIELDS)),
    ChartSpec(
        'topic_map',
        FAMILY_CONSOLE,
        echarts_only=True,
        defaults=(('x_field', 'pc1'), ('y_field', 'pc2'), ('label_field', 'topic'), ('value_field', 'prevalence_pct')),
        fields=(_X_COORDINATE, _Y_COORDINATE, _LABEL_FIELD, _VALUE_FIELD),
    ),
    ChartSpec(
        'topic_terms',
        FAMILY_CONSOLE,
        echarts_only=True,
        defaults=(('x_field', 'term'), ('y_field', 'overall_freq'), ('y2_field', 'within_freq')),
        fields=(_X_CATEGORY, _Y_VALUE_REQUIRED, _Y2_VALUE),
    ),
    ChartSpec('pie', FAMILY_CONSOLE, fields=(_X_CATEGORY, _Y_VALUE), tokenize_compatible=True),
    ChartSpec('scatter', FAMILY_CONSOLE, fields=(_X_VALUE, _Y_VALUE_REQUIRED)),
    ChartSpec('histogram', FAMILY_CONSOLE, fields=(_X_VALUE,)),
    ChartSpec(
        'box',
        FAMILY_CONSOLE,
        fields=(_X_OPTIONAL, _Y_VALUE),
        any_of=(('x_field', 'y_field'),),
    ),
    ChartSpec('heatmap', FAMILY_CONSOLE, fields=(_X_CATEGORY2, _Y_CATEGORY2, _VALUE_FIELD_AGG)),
    ChartSpec(
        'model_agreement',
        FAMILY_CONSOLE,
        echarts_only=True,
        latex_buildable=False,
        defaults=(('model_field', '模型'), ('id_field', '原行')),
        fields=(_MODEL_FIELD, _AGREEMENT_LABEL_FIELD, _ID_FIELD),
        hint_key='hint.modelAgreement',
    ),
    ChartSpec('sankey', FAMILY_CONSOLE, echarts_only=True, fields=(_X_SOURCE, _Y_TARGET, _VALUE_FIELD_AGG)),
    ChartSpec(
        'network',
        FAMILY_CONSOLE,
        echarts_only=True,
        fields=(_X_SOURCE, _Y_TARGET, _VALUE_FIELD_AGG),
        controls=('center_node',),
    ),
    _biblio('knowledge_graph', ('节点', 'x', 'y', '连接', '频次')),
    _biblio('cluster_timeline', ('节点', '聚类', '聚类标签', '首年', '末年', '频次')),
    _biblio('burst', ('节点', '突现起始', '突现结束', '突现强度')),
    _biblio('timezone', ('节点', '年份序列', '频次')),
    _biblio('circular', ('节点', '连接', '频次')),
    _biblio('landscape', ('节点', '聚类', '聚类标签', '频次')),
    _biblio('biblio_heatmap', ('节点', '聚类', '聚类标签', '年份序列', '频次')),
    _biblio('graph3d', ('节点', 'x', 'y', '连接', '频次')),
    _biblio('variation', ('节点', '起始年', '结束年', '结构变化')),
    _biblio('dual_map', ('map', 'source', 'target', 'weight')),
    # The choropleth reads the node table's own names and counts; the geometry is the committed
    # basemap, so no coordinate column is asked of the data.
    _biblio('geo_map', ('节点', '频次')),
    # The overlay views read only the distribution columns the biblio node writes when its
    # sentiment/topic mapping is filled. Requiring them is how a chart over an unlabelled table
    # becomes a named refusal instead of a blank frame.
    _biblio('sentiment_overlay', ('节点', '情感分布')),
    _biblio('topic_overlay', ('节点', '话题分布')),
    # Concentric rings are cut by each node's FIRST year, which only the per-year series carries
    # for every entity table (首年 exists only when clustering ran).
    _biblio('concentric', ('节点', '年份序列', '频次')),
    ChartSpec(
        'wordcloud',
        FAMILY_CONSOLE,
        echarts_only=True,
        fields=(_X_TEXT, _VALUE_FIELD),
        controls=('tokenize', 'wordcloud_style'),
        tokenize_compatible=True,
    ),
    ChartSpec('map', FAMILY_CONSOLE, echarts_only=True, fields=(_X_GEO, _VALUE_FIELD), hint_key='hint.mapRegionNames'),
)

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
