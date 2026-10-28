"""LaTeX figure + three-line-table generator for the ``visualize`` node.

A chart is emitted here as *source*, not a raster: a self-contained ``standalone`` document the user compiles
with MiKTeX ``xelatex`` (the figures carry Chinese, so ``ctex``). The look mirrors the hand-tuned paper this tool
feeds — 仿宋 (FangSong) CJK text, a muted paper palette, a light dotted grid, thousands-separated ticks, value
labels on bars, and boxed leader-line labels on the topic/network/sankey figures — because these are figures for
a paper, not a dashboard. Every figure and table shares ONE ``cixi`` axis style and a pair of tikz styles
(``lblbox``/``leadline``) defined once in the preamble, so a merged ``compile`` document restyles all charts at once.

The numbers come from the SAME helpers ``VisualizationService`` uses to draw the chart, so the LaTeX and
the on-screen figure are two projections of one value and cannot disagree. Colour is the exception and
says so: ``_PAPER_PALETTE`` is the paper's own list, matched color-for-color to the reference figures this
build imitates, and it is NOT ``visualizer.CATEGORY_COLORS`` — the two agree on the data, not on the ink.

The service itself is assembled from three mixins: ``DocumentShellMixin`` (standalone wrapper),
``ConsoleFigureMixin`` (palette chart types) and ``BiblioFigureMixin`` (bibliometric views). The dispatch
below is the one place a chart type is routed, so a new figure is one method plus one branch.
"""

import pandas as pd

from services.charts.contracts import BIBLIO_CHART_TYPES
from services.charts.tikz_biblio import BiblioFigureMixin
from services.charts.tikz_biblio_charts import BiblioChartMixin
from services.charts.tikz_biblio_tables import BiblioTableMixin
from services.charts.tikz_console import ConsoleFigureMixin
from services.charts.tikz_document import DocumentShellMixin
from services.charts.tikz_preamble import (
    CJK_FAMILY as CJK_FAMILY,
)
from services.charts.tikz_preamble import (
    CTEX_FONTSET as CTEX_FONTSET,
)
from services.charts.tikz_preamble import (
    GRAPH_BOX_CM as GRAPH_BOX_CM,
)
from services.charts.tikz_preamble import (
    GRAPH_LINE_CM as GRAPH_LINE_CM,
)
from services.charts.tikz_preamble import (
    _packages as _packages,
)
from services.charts.tikz_preamble import (
    ctex_options as ctex_options,
)
from services.charts.tikz_preamble import (
    esc as esc,
)
from services.charts.tikz_preamble import (
    paper_preamble as paper_preamble,
)
from services.charts.visualizer import ChartConfigError

#: Kept on this module because callers and tests address the paper helpers here
#: (``reports/paper.py`` imports ``esc``/``paper_preamble``; the platform table tests ask
#: ``ctex_options``), while the code that implements them lives in ``tikz_preamble``.
__all__ = [
    'CJK_FAMILY',
    'CTEX_FONTSET',
    'GRAPH_BOX_CM',
    'GRAPH_LINE_CM',
    'LatexChartService',
    'ctex_options',
    'esc',
    'paper_preamble',
]


class LatexChartService(DocumentShellMixin, ConsoleFigureMixin, BiblioFigureMixin, BiblioChartMixin, BiblioTableMixin):
    """Render a chart's numbers as compilable LaTeX — a figure document, or a booktabs three-line table."""

    @classmethod
    def to_latex_document(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        *,
        x=None,
        y=None,
        value_field=None,
        agg='sum',
        y2=None,
        agg2=None,
        label_field='topic',
        stack_fields='',
        title='',
        tokenize=False,
        **_ignored,
    ) -> str:
        body = cls._figure(
            df,
            chart_type,
            x=x,
            y=y,
            value_field=value_field,
            agg=agg,
            y2=y2,
            agg2=agg2,
            label_field=label_field,
            stack_fields=stack_fields,
            tokenize=tokenize,
        )
        return cls._document(body, chart_type, title, table=False)

    @classmethod
    def to_latex_table(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        *,
        x=None,
        y=None,
        value_field=None,
        agg='sum',
        y2=None,
        label_field='topic',
        stack_fields='',
        title='',
        **_ignored,
    ) -> str:
        head, rows = cls._table_data(
            df,
            chart_type,
            x=x,
            y=y,
            value_field=value_field,
            agg=agg,
            y2=y2,
            label_field=label_field,
            stack_fields=stack_fields,
        )
        return cls._document(cls._tabular(head, rows), chart_type, title, table=True)

    # ── figure dispatch ───────────────────────────────────────────────

    @classmethod
    def _figure(cls, df, chart_type, *, x, y, value_field, agg, y2, agg2, label_field, stack_fields, tokenize) -> str:
        if chart_type in ('bar', 'line'):
            return cls._bars_or_line(df, chart_type, x, y, agg)
        if chart_type == 'dual_line':
            return cls._dual_line(df, x, y, agg, y2, agg2)
        if chart_type == 'stack_pct':
            return cls._stack_pct(df, x, stack_fields)
        if chart_type == 'scatter':
            return cls._scatter(df, x, y)
        if chart_type == 'histogram':
            return cls._histogram(df, x)
        if chart_type == 'box':
            return cls._box(df, x, y)
        if chart_type == 'pie':
            return cls._pie(df, x, y, agg)
        if chart_type == 'heatmap':
            return cls._heatmap(df, x, y, value_field, agg)
        if chart_type == 'topic_map':
            return cls._topic_map(df, x, y, value_field, label_field)
        if chart_type == 'topic_terms':
            return cls._topic_terms(df, x, y, y2)
        if chart_type in BIBLIO_CHART_TYPES:
            return cls._biblio_figure(df, chart_type)
        if chart_type == 'sankey':
            return cls._relation(df, x, y, value_field, agg, ribbons=True)
        if chart_type == 'network':
            return cls._relation(df, x, y, value_field, agg, ribbons=False)
        if chart_type == 'wordcloud':
            return cls._wordcloud(df, x, value_field, agg, tokenize)
        if chart_type == 'map':
            return cls._map(df, x, value_field, agg)
        raise ChartConfigError(f'no LaTeX figure for chart type: {chart_type}')
