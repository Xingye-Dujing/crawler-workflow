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
``tests/unit/test_chart_registry.py`` refuse a spec whose builder, LaTeX twin or front-end word is
missing. The front end keeps its own lists for rendering; they are pinned against this table, not
kept as a second opinion.
"""

from dataclasses import dataclass

#: A chart family is where the type is built and what it reads, not a cosmetic grouping:
#: ``console`` types are drawn by ``charts.visualizer`` from a user's table and columns,
#: ``biblio`` types are drawn by ``charts.biblio`` from the fixed columns the ``biblio`` node
#: writes (their required column names are the contract a rename breaks by name).
FAMILY_CONSOLE = 'console'
FAMILY_BIBLIO = 'biblio'


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
    #: True when the type's x axis is not a user-chosen column (validation must not demand it).
    no_x: bool = False

    @property
    def label_key(self) -> str:
        return f'chart.{self.key}'


def _biblio(key: str, reads: tuple[str, ...], *, echarts_only: bool = True, no_x: bool = True) -> ChartSpec:
    return ChartSpec(key, FAMILY_BIBLIO, echarts_only=echarts_only, reads=reads, no_x=no_x)


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
    ChartSpec('bar', FAMILY_CONSOLE),
    ChartSpec('line', FAMILY_CONSOLE),
    ChartSpec('dual_line', FAMILY_CONSOLE, echarts_only=True),
    ChartSpec('stack_pct', FAMILY_CONSOLE),
    ChartSpec('topic_map', FAMILY_CONSOLE, echarts_only=True),
    ChartSpec('topic_terms', FAMILY_CONSOLE, echarts_only=True),
    ChartSpec('pie', FAMILY_CONSOLE),
    ChartSpec('scatter', FAMILY_CONSOLE),
    ChartSpec('histogram', FAMILY_CONSOLE),
    ChartSpec('box', FAMILY_CONSOLE),
    ChartSpec('heatmap', FAMILY_CONSOLE),
    ChartSpec('model_agreement', FAMILY_CONSOLE, echarts_only=True, latex_buildable=False, no_x=True),
    ChartSpec('sankey', FAMILY_CONSOLE, echarts_only=True),
    ChartSpec('network', FAMILY_CONSOLE, echarts_only=True),
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
    ChartSpec('wordcloud', FAMILY_CONSOLE, echarts_only=True),
    ChartSpec('map', FAMILY_CONSOLE, echarts_only=True),
)

_BY_KEY = {spec.key: spec for spec in SPECS}

CHART_TYPES = tuple(spec.key for spec in SPECS)
BIBLIO_CHART_TYPES = tuple(spec.key for spec in SPECS if spec.family == FAMILY_BIBLIO)
ECHARTS_ONLY_TYPES = tuple(spec.key for spec in SPECS if spec.echarts_only)
LATEX_UNBUILDABLE_TYPES = tuple(spec.key for spec in SPECS if not spec.latex_buildable)
NO_X_TYPES = frozenset(spec.key for spec in SPECS if spec.no_x)
BIBLIO_CHART_READS = {spec.key: spec.reads for spec in SPECS if spec.reads}


def spec_for(chart_type: str) -> ChartSpec | None:
    return _BY_KEY.get(str(chart_type or '').strip())


def is_biblio(chart_type: str) -> bool:
    spec = spec_for(chart_type)
    return bool(spec and spec.family == FAMILY_BIBLIO)
