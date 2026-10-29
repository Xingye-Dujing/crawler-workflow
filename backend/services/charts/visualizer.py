"""General-purpose visualization service.

Two rendering back-ends are supported so the "Visualize" node (and any
standalone caller) can pick whichever fits:

* ``engine="echarts"`` -> returns a JSON-serializable ECharts ``option``
  dict. Cheap, renders client-side, reuses the ECharts script already
  loaded by the frontend (see stats.js for the existing pie-chart usage
  this mirrors).
* ``engine="matplotlib"`` -> renders server-side with matplotlib and
  returns a base64 PNG data URI. Useful for chart types or styling that
  are easier to express in Python, or for headless/report generation.

This service is data-source agnostic: it only cares about a DataFrame and
a chart spec, so it works identically whether the data came from a
workflow's upstream node, an uploaded CSV/JSON file, or hand-typed JSON
pasted into the UI.
"""

import base64
import io
import logging
from collections import Counter

import jieba
import numpy as np
import pandas as pd

from i18n import t
from services.charts.contracts import ChartConfigError
from services.charts.options import OptionMixin
from services.charts.registry import CHART_TYPES, ECHARTS_ONLY_TYPES
from services.charts.style import (
    _CJK_CANDIDATES as _CJK_CANDIDATES,
)
from services.charts.style import (
    _NO_CHINESE as _NO_CHINESE,
)
from services.charts.style import (
    ANNOTATED_TYPES as ANNOTATED_TYPES,
)
from services.charts.style import (
    CATEGORY_COLORS as CATEGORY_COLORS,
)
from services.charts.style import (
    FONT_STACK as FONT_STACK,
)
from services.charts.style import (
    _box_stats as _box_stats,
)
from services.charts.style import (
    _boxplot as _boxplot,
)
from services.charts.style import (
    _finite as _finite,
)
from services.charts.style import (
    _histogram_bins as _histogram_bins,
)
from services.charts.style import (
    _json_safe as _json_safe,
)
from services.charts.style import (
    _localize_label as _localize_label,
)
from services.charts.style import (
    _pyplot as _pyplot,
)
from services.charts.style import (
    _warn_missing_cjk_font as _warn_missing_cjk_font,
)
from services.charts.style import (
    cjk_font as cjk_font,
)
from services.charts.style import print_style

#: The style surface kept on this module: tests and the LaTeX builder ask the visualizer for
#: the font stack, the palette and the rendering helpers, while their implementation lives in
#: ``services.charts.style``. Declaring them here is what tells the linter they are exported.
__all__ = [
    'ANNOTATED_TYPES',
    'CATEGORY_COLORS',
    'FONT_STACK',
    'VisualizationService',
    '_box_stats',
    '_finite',
    '_histogram_bins',
    '_localize_label',
    '_pyplot',
    '_warn_missing_cjk_font',
    'cjk_font',
    'print_style',
]

logger = logging.getLogger(__name__)

#: The two renderers a chart may ask for. A value off this list is refused by name rather
#: than defaulted, so the figure never silently comes from the engine the user did not pick.
_CHART_ENGINES = ('echarts', 'matplotlib')


def chart_engine(value) -> str:
    """The renderer this chart asked for, refused by name when it asked for neither.

    Both visualize paths branched on ``engine == 'matplotlib'`` and sent everything
    else to the browser library, so ``'mpl'``, ``'Matplotlib'`` or a key that named no
    renderer produced the chart the user had *not* chosen — and, unlike a bad column
    name, no line anywhere saying the choice was not understood. The chart's own error
    channel is ``ChartConfigError``, which the node reports as its failure reason and
    the HTTP route as a 400.
    """
    name = str(value or 'echarts').strip() or 'echarts'
    if name not in _CHART_ENGINES:
        raise ChartConfigError(
            t('analysis.bad_option', op='visualize', param='engine', value=name, allowed=', '.join(_CHART_ENGINES))
        )
    return name


class VisualizationService(OptionMixin):
    """Builds chart specs from a DataFrame. Stateless / reusable."""

    # ── Shared data prep ────────────────────────────────────────

    @staticmethod
    def require_columns(df: pd.DataFrame, *names):
        """Every builder indexes the frame by user-configured field names.

        A renamed or mistyped column must say so: a bare ``KeyError: 'nope'``
        reaches the user as an opaque node failure, and a missing *y* used to
        silently degrade a sum chart into a row count.
        """
        for name in names:
            if name and name not in df.columns:
                raise ChartConfigError(f'Field not found in the data: {name}')

    @staticmethod
    def aggregate(df: pd.DataFrame, x: str, y: str = None, agg: str = 'sum'):
        """Group by *x* and aggregate *y* (or count rows if y is None).

        The category order is the TABLE's, not an alphabetical one. This step is the last chance to
        lose a lifecycle: 表 2 arrives sorted by 阶段序号, and `sort_index()` here put 一次爆发期 in
        the first bar of 图 3 — a figure that reads the event backwards while looking complete. A
        group that appears again later keeps its first position (`sort=False`), because "where the
        user put it" is the only ordering this layer is allowed to trust.
        """
        VisualizationService.require_columns(df, x, y)
        if y:
            numeric = pd.to_numeric(df[y], errors='coerce')
            grouped = numeric.groupby(df[x], sort=False).agg(agg)
        else:
            grouped = df.groupby(x, sort=False).size()
        return [_localize_label(value) for value in grouped.index.astype(str)], grouped.values.tolist()

    # ── ECharts option builder ───────────────────────────────────

    @classmethod
    def to_echarts_option(cls, df: pd.DataFrame, chart_type: str, **kwargs) -> dict:
        """Build a chart spec for *chart_type*.

        The spec is always JSON-safe: non-finite numbers survive some
        aggregations (a mean over an all-missing group is NaN) and a single
        ``NaN`` token would make the browser reject the entire response.
        """
        return _json_safe(print_style(cls._build_option(df, chart_type, **kwargs)))

    @staticmethod
    def tokenize_frequency(df: pd.DataFrame, column: str, top_n: int = 120):
        """Tokenize a free-text column into word frequencies for a word
        cloud. Uses jieba for Chinese segmentation (this app's crawler
        content is primarily Chinese); falls back to whitespace splitting
        for non-Chinese text if jieba isn't installed.

        The stop-word rule is the shared one (:mod:`analyzers.stopwords`), not the small local set
        this used to carry: a cloud drawn from a different vocabulary than 表 1's 特征词 is two
        measurements of the same corpus that a reader cannot put side by side.
        """
        VisualizationService.require_columns(df, column)
        from analyzers.stopwords import is_meaningful

        texts = df[column].dropna().astype(str).tolist()
        counter = Counter()
        try:
            for text in texts:
                for token in jieba.lcut(text):
                    if not is_meaningful(token):
                        continue
                    counter[token] += 1
        except ImportError:
            for text in texts:
                for token in text.split():
                    word = token.strip().lower()
                    if word and is_meaningful(word):
                        counter[word] += 1

        top = counter.most_common(top_n)
        if not top:
            return [], []
        labels, values = zip(*top, strict=True)
        return list(labels), list(values)

    @staticmethod
    def apply_heatmap_option(base, xcats, ycats, matrix, min_val, max_val):
        """Turn an (xcats × ycats) numeric matrix into the shared ECharts heatmap spec.

        Both the data heatmap and the 模型一致率 matrix draw identically, so the colour ramp,
        axes and visualMap live in ONE place — a tweak to the figure reaches both, and the two
        can never drift apart. Bounds are supplied by the caller (counts vs a fixed 0–100 %).
        """
        data = [[xi, yi, matrix[yi][xi]] for yi in range(len(ycats)) for xi in range(len(xcats))]
        base['grid'] = {'left': 80, 'right': 60, 'top': 10, 'bottom': 60}
        base['xAxis'] = {
            'type': 'category',
            'data': xcats,
            'splitArea': {'show': True, 'areaStyle': {'color': ['rgba(0,0,0,0)']}},
            'axisLabel': {'rotate': 30, 'color': '#aaa', 'fontSize': 10},
            'axisLine': {'show': False},
        }
        base['yAxis'] = {
            'type': 'category',
            'data': ycats,
            'splitArea': {'show': True, 'areaStyle': {'color': ['rgba(0,0,0,0)']}},
            'axisLabel': {'color': '#aaa', 'fontSize': 10},
            'axisLine': {'show': False},
        }
        base['visualMap'] = {
            'min': min_val,
            'max': max_val,
            'calculable': True,
            'orient': 'horizontal',
            'left': 'center',
            'bottom': 8,
            'inRange': {
                'color': [
                    '#313695',
                    '#4575B4',
                    '#74ADD1',
                    '#ABD9E9',
                    '#E0F3F8',
                    '#FFFFBF',
                    '#FEE090',
                    '#FDAE61',
                    '#F46D43',
                    '#D73027',
                    '#A50026',
                ]
            },
            'textStyle': {'color': '#aaa', 'fontSize': 10},
        }
        base['series'] = [
            {
                'type': 'heatmap',
                'data': data,
                'label': {'show': True, 'color': '#ccc', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                'emphasis': {'itemStyle': {'shadowBlur': 8, 'shadowColor': 'rgba(0,0,0,0.4)'}},
            }
        ]
        return base

    @classmethod
    def agreement_matrix(cls, df, model_col, label_col, id_col):
        """Pairwise label-agreement (percent of the rows two models both answered where they
        chose the same label), aligned by ``id_col`` across the tidy multi-model table.

        The model order is the TABLE's first-appearance order (never alphabetical), for the
        same reason `aggregate`/`pivot` keep it: the canvas put the models somewhere, and
        an off-diagonal cell is read against that axis. A pair is scored only over rows where
        BOTH models answered (a row one model left blank cannot be an agreement or a
        disagreement); the diagonal is 100 by definition. Fewer than two models refuses — a
        1×1 square is not a comparison and would hide that the node ran one model.
        """
        cls.require_columns(df, model_col, id_col)
        if not label_col:
            raise ChartConfigError('model_agreement needs the label column (agreement_label_field)')
        cls.require_columns(df, label_col)
        order = []
        for value in df[model_col].astype(str):
            if value not in order:
                order.append(value)
        if len(order) < 2:
            raise ChartConfigError(f'model_agreement needs at least 2 models in {model_col!r}; found {len(order)}')
        # One Series per model, indexed by the row id, so a pair aligns on 原行 not on position.
        per_model = {name: g.set_index(id_col)[label_col] for name, g in df.groupby(df[model_col].astype(str))}
        matrix = []
        for a in order:
            row = []
            for b in order:
                if a == b:
                    row.append(100.0)
                    continue
                sa, sb = per_model[a], per_model[b]
                # A blank is "this model answered nothing", and blank against blank is NOT
                # agreement: an inner join alone scored every row both models left empty as a
                # pair the two chose identically, inflating the cell the docstring promises is
                # computed only "where BOTH models answered".
                sa = sa[(sa.astype(str).str.strip() != '') & (sa.notna())]
                sb = sb[(sb.astype(str).str.strip() != '') & (sb.notna())]
                joined = pd.concat([sa, sb], axis=1, join='inner', keys=['a', 'b'])
                n = len(joined)
                if n == 0:
                    row.append(0.0)
                    continue
                agree = (joined['a'].astype(str) == joined['b'].astype(str)).sum() / n * 100.0
                row.append(round(float(agree), 2))
            matrix.append(row)
        cats = [_localize_label(name) for name in order]
        return cats, matrix

    @staticmethod
    def pivot(df: pd.DataFrame, x: str, y: str, value_field: str = None, agg: str = 'count'):
        """Build a y-by-x matrix for a heatmap: counts co-occurrences of
        (x, y) pairs, or aggregates value_field over each pair if given.

        Both axes keep the table's order, for the same reason `aggregate` does — `pivot_table`
        sorts its index and columns, which would put a heatmap's phases in code-point order and
        make the picture disagree with the 表 it was built from.
        """
        VisualizationService.require_columns(df, x, y)
        work = df[[x, y]].copy()
        xcats = [str(value) for value in pd.unique(df[x].astype(str))]
        ycats = [str(value) for value in pd.unique(df[y].astype(str))]
        work['_xc'] = work[x].astype(str)
        work['_yc'] = work[y].astype(str)
        if value_field:
            # A value field named but absent is refused by name, not silently replaced by a row
            # count — a heatmap the user asked to aggregate by 「分值」 that quietly showed 条数 lies.
            VisualizationService.require_columns(df, value_field)
            work['_v'] = pd.to_numeric(df[value_field], errors='coerce')
            grouped = work.groupby(['_yc', '_xc'], sort=False)['_v'].agg(agg)
        else:
            grouped = work.groupby(['_yc', '_xc'], sort=False).size()
        cells = {
            (str(ykey), str(xkey)): (value if np.isfinite(value) else 0) for (ykey, xkey), value in grouped.items()
        }
        matrix = [[cells.get((yy, xx), 0) for xx in xcats] for yy in ycats]
        # The matrix is addressed by the RAW strings above; localise only what reaches the screen.
        return [_localize_label(value) for value in xcats], [_localize_label(value) for value in ycats], matrix

    @staticmethod
    def sankey_links(df: pd.DataFrame, source: str, target: str, value_field: str = None, agg: str = 'count'):
        """Build ECharts sankey nodes+links from a source/target column pair
        (e.g. platform -> emotion), weighted by row count or value_field."""
        VisualizationService.require_columns(df, source, target)
        work = df[[source, target]].copy()
        work.columns = ['_s', '_t']
        if value_field:
            VisualizationService.require_columns(df, value_field)
            work['_v'] = pd.to_numeric(df[value_field], errors='coerce')
            grouped = work.groupby(['_s', '_t'])['_v'].agg(agg).reset_index()
        else:
            grouped = work.groupby(['_s', '_t']).size().reset_index(name='_v')

        # Sankey requires distinct node names; if a value appears on both
        # sides (e.g. same label used as both source and target) ECharts
        # can still render it as one shared node, so no renaming is needed.
        # A zero-weight link renders as nothing in ECharts and a NaN weight is
        # not valid JSON, so neither one is emitted.
        links = []
        for _, row in grouped.iterrows():
            weights = _finite([row['_v']])
            if weights and weights[0]:
                links.append(
                    {
                        'source': _localize_label(row['_s']),
                        'target': _localize_label(row['_t']),
                        'value': weights[0],
                    }
                )
        nodes = sorted(
            set(_localize_label(v) for v in grouped['_s'].astype(str))
            | set(_localize_label(v) for v in grouped['_t'].astype(str))
        )
        return nodes, links

    @classmethod
    def ego_subgraph(cls, nodes, links, center):
        """Reduce a co-occurrence graph to one node's ego-network: the centre word, the words
        directly co-occurring with it, and the edges among that set. ``center`` must name a node
        already in the graph — a word this data never linked is refused BY NAME, not quietly
        returned as an empty figure. The centre then carries the largest incident weight, so it
        is naturally the biggest bubble and the hub the force layout gathers around.
        """
        if center not in nodes:
            raise ChartConfigError(
                f'network center_node {center!r} is not a node in this graph (it must name one '
                f'of the {len(nodes)} words this data already links)',
            )
        keep = {center}
        for link in links:
            if link['source'] == center:
                keep.add(link['target'])
            elif link['target'] == center:
                keep.add(link['source'])
        kept_nodes = [n for n in nodes if n in keep]
        kept_links = [link for link in links if link['source'] in keep and link['target'] in keep]
        return kept_nodes, kept_links

    # ── Matplotlib renderer (server-side PNG) ───────────────────

    @classmethod
    def render_image(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        x: str = None,
        y: str = None,
        value_field: str = None,
        agg: str = 'sum',
        title: str = '',
        annotations: str = '',
        stack_fields: str = '',
    ) -> str:
        """Render the chart with matplotlib and return a base64 PNG data URI."""

        if chart_type not in CHART_TYPES:
            raise ChartConfigError(f'Unsupported chart type: {chart_type}')
        if annotations:
            # The markers exist as an ECharts ``markLine`` on a category axis; a PNG without
            # them would be a figure whose dates vanished with no word said.
            raise ChartConfigError(
                'event markers (annotations) are only drawn with engine=echarts — the matplotlib '
                'renderer has no marker layer, so switch engine or clear the box'
            )
        if chart_type in ECHARTS_ONLY_TYPES:
            raise ChartConfigError(
                f'"{chart_type}" is only available with engine=echarts '
                f'(no matplotlib equivalent without extra dependencies)'
            )
        # Same field requirements as the ECharts builder, so both engines fail
        # the same readable way — groupby(None) is a bare pandas TypeError.
        if chart_type in ('scatter', 'heatmap'):
            if not x or not y:
                raise ChartConfigError(f'{chart_type} chart requires both x and y fields')
        elif chart_type in ('pie', 'histogram', 'box', 'line', 'bar', 'stack_pct') and not x:
            raise ChartConfigError(f'{chart_type} chart requires a field (x)')
        # Every branch below indexes the frame by the configured field names.
        cls.require_columns(df, x, y)

        plt = _pyplot()
        fig, ax = plt.subplots(figsize=(7, 4.2), dpi=130)
        try:
            if chart_type == 'pie':
                labels, values = cls.aggregate(df, x, y, agg)
                ax.pie(values, labels=labels, autopct='%1.1f%%', textprops={'fontsize': 8})
            elif chart_type == 'scatter':
                ax.scatter(pd.to_numeric(df[x], errors='coerce'), pd.to_numeric(df[y], errors='coerce'), s=18)
                ax.set_xlabel(_localize_label(x))
                ax.set_ylabel(_localize_label(y))
            elif chart_type == 'histogram':
                ax.hist(pd.to_numeric(df[x], errors='coerce').dropna(), bins=20)
                ax.set_xlabel(_localize_label(x))
                ax.set_ylabel(t('chart.count'))
            elif chart_type == 'box':
                if y:
                    # One grouping, ``sort=False``: a box must sit under the same phase order the
                    # bar/aggregate paths use, not pandas' default code-point sort (which put
                    # 二次爆发期 before 发酵期). One pass keeps labels and data aligned by construction.
                    grouped = df.groupby(x, sort=False)
                    groups = [pd.to_numeric(g[y], errors='coerce').dropna().values for _, g in grouped]
                    grp_labels = [_localize_label(str(name)) for name in grouped.groups]
                    _boxplot(ax, groups, grp_labels)
                    ax.set_xlabel(_localize_label(x))
                else:
                    _boxplot(ax, pd.to_numeric(df[x], errors='coerce').dropna(), [x])
            elif chart_type == 'heatmap':
                xcats, ycats, matrix = cls.pivot(df, x, y, value_field, agg if value_field else 'count')
                im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
                ax.set_xticks(range(len(xcats)))
                ax.set_xticklabels(xcats, rotation=45, ha='right', fontsize=8)
                ax.set_yticks(range(len(ycats)))
                ax.set_yticklabels(ycats, fontsize=8)
                fig.colorbar(im, ax=ax)
            elif chart_type == 'line':
                labels, values = cls.aggregate(df, x, y, agg)
                ax.plot(labels, values, marker='o')
                ax.tick_params(axis='x', rotation=45)
            elif chart_type == 'stack_pct':
                fields = [s.strip() for s in str(stack_fields or '').replace('，', ',').split(',') if s.strip()]
                if not fields:
                    raise ChartConfigError('stack_pct chart requires stacked fields (stack_fields)')
                cls.require_columns(df, *fields)
                grouped = df.groupby(x, sort=False)
                keys = list(grouped.groups.keys())
                cats = [str(k) for k in keys]
                cols = {f: grouped[f].sum().reindex(keys).fillna(0).tolist() for f in fields}
                totals = [sum(cols[f][i] for f in fields) for i in range(len(cats))]
                bottoms = [0.0] * len(cats)
                for idx, f in enumerate(fields):
                    shares = [cols[f][i] / totals[i] * 100 if totals[i] else 0.0 for i in range(len(cats))]
                    ax.bar(
                        cats,
                        shares,
                        bottom=bottoms,
                        label=_localize_label(f),
                        color=CATEGORY_COLORS[idx % len(CATEGORY_COLORS)],
                    )
                    bottoms = [b + s for b, s in zip(bottoms, shares, strict=True)]
                ax.set_ylabel(t('chart.col.share'))
                ax.set_ylim(0, 100)
                ax.legend(frameon=False, fontsize=8, ncol=len(fields))
                ax.tick_params(axis='x', rotation=45)
            else:  # bar
                labels, values = cls.aggregate(df, x, y, agg)
                ax.bar(labels, values)
                ax.tick_params(axis='x', rotation=45)

            if chart_type not in ('pie', 'heatmap'):
                # A paper figure keeps the two axes the reader measures against and drops the
                # box: no top/right spine, dark left/bottom, no gridlines.
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                for _spine in ('left', 'bottom'):
                    ax.spines[_spine].set_color('#666')

            if title:
                ax.set_title(title)
            fig.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True)
        finally:
            # Nearly every step above can raise — a pie of negative values, a
            # groupby over all-null data, matplotlib refusing to lay out a tick.
            # Closing only on the success path leaked one open figure per failed
            # render into matplotlib's registry, and the UI retries charts.
            plt.close(fig)
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode('ascii')
        return f'data:image/png;base64,{encoded}'
