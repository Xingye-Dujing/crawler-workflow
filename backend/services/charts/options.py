"""The ECharts option builder: one ``_build_option`` dispatch and its styling pass.

The option dict is plain JSON — no ``renderItem`` callbacks — so a preview, a saved chart and a
fullscreen render all draw the same figure. Chart families share the palette and the print
restyle defined here; the service in ``visualizer`` assembles this mixin.
"""

import pandas as pd

from i18n import t

from .contracts import ChartConfigError
from .registry import BIBLIO_CHART_TYPES, CHART_TYPES
from .style import (
    _AXIS_STYLE,
    _GRID,
    _TEXT_STYLE,
    ANNOTATED_TYPES,
    CATEGORY_COLORS,
    WORDCLOUD_STYLES,
    _annotation_lines,
    _box_stats,
    _finite,
    _histogram_bins,
    _json_safe,
    _localize_label,
    _parse_annotations,
)


class OptionMixin:
    @classmethod
    def _build_option(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        x: str = None,
        y: str = None,
        value_field: str = None,
        _series: str = None,
        agg: str = 'sum',
        y2: str = None,
        agg2: str = None,
        label_field: str = None,
        annotations: str = '',
        title: str = '',
        **kwargs,
    ) -> dict:
        if chart_type not in CHART_TYPES:
            raise ChartConfigError(f'Unsupported chart type: {chart_type}')
        if annotations and chart_type not in ANNOTATED_TYPES:
            # Checked before anything is built, so the message is about the box, not about a
            # half-drawn figure.
            raise ChartConfigError(
                f'the {chart_type} figure cannot carry event markers: only {", ".join(ANNOTATED_TYPES)} draw a '
                'vertical line at one category. Clear the box rather than trusting a figure '
                'that quietly dropped it.'
            )

        color = CATEGORY_COLORS[:]

        base = {
            'backgroundColor': 'transparent',
            'color': color,
            'title': {
                'text': title,
                'textStyle': {'color': '#e8e8e8', 'fontSize': 14, 'fontWeight': 500, 'fontFamily': 'sans-serif'},
                'left': 'center',
                'top': 6,
            },
            'tooltip': {
                'trigger': 'item' if chart_type in ('pie', 'wordcloud', 'map', 'sankey', 'network') else 'axis',
                'backgroundColor': 'rgba(30,30,40,0.9)',
                'borderColor': '#444',
                'borderWidth': 1,
                'textStyle': {'color': '#eee', 'fontSize': 12, 'fontFamily': 'sans-serif'},
                'formatter': '{b}: {c}' if chart_type not in ('pie', 'sankey', 'network') else None,
            },
            'animationDuration': 800,
            'animationEasing': 'cubicOut',
        }

        # ── Bibliometric views (fixed columns from the biblio node) ──
        if chart_type in BIBLIO_CHART_TYPES:
            from services.biblio import charts

            try:
                return charts.build(df, chart_type, base)
            except charts.BiblioChartError as exc:
                raise ChartConfigError(str(exc)) from exc

        # ── Pie ──
        if chart_type == 'pie':
            if not x:
                raise ChartConfigError('Pie chart requires a category field (x)')
            labels, values = cls.aggregate(df, x, y, agg)
            base['tooltip']['formatter'] = '{b}: {c} ({d}%)'
            base['legend'] = {
                'data': labels,
                'orient': 'vertical',
                'right': 10,
                'top': 36,
                'textStyle': _TEXT_STYLE,
                'icon': 'circle',
                'itemWidth': 10,
                'itemHeight': 10,
            }
            base['series'] = [
                {
                    'type': 'pie',
                    'radius': ['30%', '62%'],
                    'center': ['40%', '52%'],
                    'avoidLabelOverlap': True,
                    'padAngle': 1.5,
                    'itemStyle': {
                        'borderColor': 'rgba(20,20,30,0.6)',
                        'borderWidth': 2,
                    },
                    'label': {
                        'formatter': '{b}\n{d}%',
                        'color': '#ccc',
                        'fontSize': 11,
                        'fontFamily': 'sans-serif',
                    },
                    'labelLine': {'lineStyle': {'color': '#555'}},
                    'emphasis': {
                        'itemStyle': {
                            'shadowBlur': 12,
                            'shadowColor': 'rgba(0,0,0,0.4)',
                        },
                        'label': {'fontSize': 13, 'fontWeight': 'bold'},
                    },
                    'data': [{'name': n, 'value': v} for n, v in zip(labels, values, strict=True)],
                }
            ]
            return base

        # ── Scatter ──
        if chart_type == 'scatter':
            if not x or not y:
                raise ChartConfigError('Scatter chart requires both x and y fields')
            cls.require_columns(df, x, y)
            xs = pd.to_numeric(df[x], errors='coerce')
            ys = pd.to_numeric(df[y], errors='coerce')
            base['grid'] = dict(_GRID)
            base['xAxis'] = {
                'type': 'value',
                'name': _localize_label(x),
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['yAxis'] = {
                'type': 'value',
                'name': _localize_label(y),
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['tooltip']['formatter'] = (
                f'<b>{{@[0]}}</b><br/>{_localize_label(x)}: {{@[0]}}<br/>{_localize_label(y)}: {{@[1]}}'
            )
            base['series'] = [
                {
                    'type': 'scatter',
                    'symbolSize': 9,
                    'itemStyle': {
                        'color': color[0],
                        'shadowBlur': 4,
                        'shadowColor': 'rgba(59,130,249,0.25)',
                    },
                    'data': list(zip(xs.tolist(), ys.tolist(), strict=True)),
                }
            ]
            return base

        # ── Histogram ──
        if chart_type == 'histogram':
            if not x:
                raise ChartConfigError('Histogram requires a numeric field (x)')
            cls.require_columns(df, x)
            values = pd.to_numeric(df[x], errors='coerce').dropna()
            counts, edges = _histogram_bins(values)
            labels_bin = [f'{e:.1f}' for e in edges[:-1]]
            base['grid'] = dict(_GRID)
            base['xAxis'] = {
                'type': 'category',
                'data': labels_bin,
                'name': _localize_label(x),
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['yAxis'] = {
                'type': 'value',
                'name': t('chart.count'),
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['series'] = [
                {
                    'type': 'bar',
                    'data': counts,
                    'barWidth': '98%',
                    'itemStyle': {
                        'color': color[0],
                        'borderRadius': [1, 1, 0, 0],
                    },
                    'emphasis': {'itemStyle': {'color': color[1]}},
                }
            ]
            return base

        # ── Box ──
        if chart_type == 'box':
            # A NAMED field that the table does not hold is refused by name, never swapped for a
            # different column: the old ``elif x and x in df.columns`` fell through to drawing the
            # CATEGORY column x as numeric when a typo'd ``y`` was absent, producing a plausible
            # all-zero box whose axis was a phase name — the figure lied.
            if y:
                cls.require_columns(df, y)
                # Grouped box plot: x = category, y = numeric value
                if not x:
                    raise ChartConfigError('Box plot requires a category field (x) for grouping')
                cls.require_columns(df, x)
                groups = [
                    (_localize_label(name), pd.to_numeric(group[y], errors='coerce').dropna())
                    for name, group in df.groupby(x, sort=False)
                ]
                labels = [g[0] for g in groups]
                data = [_box_stats(g[1]) for g in groups]
                scatter_data = []
                for i, (_, vals) in enumerate(groups):
                    for v in vals.tolist():
                        scatter_data.append([i, v])
            elif x:
                cls.require_columns(df, x)
                # Single box plot: x = numeric value (backward compat)
                values = pd.to_numeric(df[x], errors='coerce').dropna()
                stats = _box_stats(values)
                labels = [_localize_label(x)]
                data = [stats]
                scatter_data = [[0, v] for v in values.tolist()]
            else:
                raise ChartConfigError(
                    'Box plot requires a category field (x) and a numeric field (y), or a single numeric field (x)'
                )
            base['grid'] = dict(_GRID)
            base['xAxis'] = {
                'type': 'category',
                'data': labels,
                **_AXIS_STYLE,
            }
            base['yAxis'] = {
                'type': 'value',
                **_AXIS_STYLE,
            }
            base['series'] = [
                {
                    'type': 'boxplot',
                    'data': data,
                    'itemStyle': {'color': color[0], 'borderColor': color[0]},
                    'boxWidth': [20, 60],
                }
            ]
            if scatter_data:
                base['series'].append(
                    {
                        'type': 'scatter',
                        'data': scatter_data,
                        'symbolSize': 4,
                        'itemStyle': {'color': 'rgba(59,130,249,0.3)'},
                        'tooltip': {'formatter': '{c}'},
                    }
                )
            return base

        # ── Heatmap ──
        if chart_type == 'heatmap':
            if not x or not y:
                raise ChartConfigError('Heatmap requires two category fields (x and y)')
            xcats, ycats, matrix = cls.pivot(df, x, y, value_field, agg)
            # Bounds come from the usable numbers only: an all-missing cell makes
            # the aggregate NaN, and NaN bounds would leave the colour scale blank.
            vals = _finite(v for row in matrix for v in row)
            return cls._apply_heatmap_option(
                base, xcats, ycats, matrix, min(vals) if vals else 0, max(vals) if vals else 1
            )

        # 模型一致率: pairwise label-agreement (percentage of the shared rows on which two
        # models chose the SAME label) drawn as the same square heatmap. It reads the tidy
        # multi-model table by its 模型 / 标签 / 原行 columns, so a renamed analysis output
        # refuses by name rather than rendering a matrix of the wrong thing.
        if chart_type == 'model_agreement':
            cats, matrix = cls._agreement_matrix(
                df,
                kwargs.get('model_field') or '模型',
                kwargs.get('agreement_label_field'),
                kwargs.get('id_field') or '原行',
            )
            return cls._apply_heatmap_option(base, cats, cats, matrix, 0, 100)

        # ── Sankey ──
        if chart_type == 'sankey':
            if not x or not y:
                raise ChartConfigError('Sankey diagram requires a source field (x) and a target field (y)')
            nodes, links = cls.sankey_links(df, x, y, value_field, agg)
            base['tooltip']['formatter'] = '<b>{b}</b><br/>{c}'
            base['series'] = [
                {
                    'type': 'sankey',
                    'data': [
                        {'name': n, 'itemStyle': {'color': CATEGORY_COLORS[i % len(CATEGORY_COLORS)]}}
                        for i, n in enumerate(nodes)
                    ],
                    'links': links,
                    'layoutIterations': 32,
                    'nodeAlign': 'justify',
                    'nodeWidth': 18,
                    'nodeGap': 10,
                    'emphasis': {'focus': 'adjacency'},
                    'lineStyle': {
                        'color': 'gradient',
                        'curveness': 0.5,
                        'opacity': 0.45,
                    },
                    'label': {
                        'color': '#ccc',
                        'fontSize': 11,
                        'fontFamily': 'sans-serif',
                    },
                }
            ]
            return base

        # ── Force-directed network: the co-occurrence and flow graphs ──
        if chart_type == 'network':
            if not x or not y:
                raise ChartConfigError('Network graph requires a source field (x) and a target field (y)')
            nodes, links = cls.sankey_links(df, x, y, value_field, agg)
            if not links:
                # The sankey would draw an empty frame and look like a finished figure; a graph
                # with no edge is not "a sparse relationship network", it is nothing measured.
                raise ChartConfigError(
                    f'network graph has no edges: every {x}/{y} pair was blank, zero-weighted or unvalued'
                )
            # "以某个节点为中心" is a real figure, not a hover hint that vanishes before it can
            # be saved: keep only the chosen word's ego-network (it + direct neighbours + the
            # edges among them), so the reading is persistent and exports identically to how it
            # previews. A blank centre leaves the full candidate graph exactly as before.
            center = str(kwargs.get('center_node') or '').strip()
            if center:
                nodes, links = cls._ego_subgraph(nodes, links, center)
            incident: dict = {}
            for link in links:
                for name in (link['source'], link['target']):
                    incident[name] = incident.get(name, 0.0) + link['value']
            biggest_node = max(incident.values()) or 1.0
            biggest_link = max(link['value'] for link in links) or 1.0
            base['series'] = [
                {
                    'type': 'graph',
                    'layout': 'force',
                    # Circular first, then relaxed: an unconstrained force start is random, and
                    # a figure whose clusters move between two runs of one table is a figure
                    # nobody can put in a report.
                    'force': {
                        'initLayout': 'circular',
                        'repulsion': 160,
                        'edgeLength': [60, 160],
                        'gravity': 0.06,
                        'friction': 0.6,
                    },
                    'roam': True,
                    'draggable': True,
                    'data': [
                        {
                            'name': name,
                            # The node's own number is the sum of the weights of the links it
                            # carries, so the tooltip says what the bubble size means.
                            'value': round(float(incident[name]), 6),
                            # Area, not radius, carries the weight — the same rule as the topic map.
                            'symbolSize': round(14.0 + 40.0 * (float(incident[name]) / biggest_node) ** 0.5, 2),
                            'itemStyle': {'color': CATEGORY_COLORS[position % len(CATEGORY_COLORS)]},
                        }
                        for position, name in enumerate(nodes)
                    ],
                    'links': [
                        {
                            **link,
                            'lineStyle': {'width': round(1.0 + 5.0 * (float(link['value']) / biggest_link) ** 0.5, 2)},
                        }
                        for link in links
                    ],
                    'label': {
                        'show': True,
                        'position': 'right',
                        'color': '#ccc',
                        'fontSize': 10,
                        'fontFamily': 'sans-serif',
                    },
                    'lineStyle': {'color': 'source', 'curveness': 0.15, 'opacity': 0.55},
                    'emphasis': {'focus': 'adjacency', 'lineStyle': {'width': 4}},
                }
            ]
            return base

        # ── Word cloud ──
        if chart_type == 'wordcloud':
            if not x:
                raise ChartConfigError('Word cloud requires a text/category field (x)')
            if kwargs.get('tokenize'):
                labels, values = cls.tokenize_frequency(df, x)
            else:
                labels, values = cls.aggregate(df, x, value_field, agg)
            style_name = kwargs.get('wordcloud_style', 'vibrant')
            # Deliberate fallback, unlike the parameters that choose *data* or *cost*:
            # a word cloud's palette is decoration, and an unknown name (a preset this
            # build no longer ships, a caller that guessed one) must still produce the
            # chart the rest of the request asked for. The node's own refusal rule
            # applies wherever a silent default would change what the user got — the
            # crawl board, the file format, the algorithm, the renderer.
            style = WORDCLOUD_STYLES.get(style_name, WORDCLOUD_STYLES['vibrant'])
            palette = style['textStyle'].get('color', '#ccc')
            if isinstance(palette, list):
                data = [
                    {'name': n, 'value': v, 'textStyle': {'color': palette[i % len(palette)]}}
                    for i, (n, v) in enumerate(zip(labels, values, strict=True))
                ]
            else:
                data = [{'name': n, 'value': v} for n, v in zip(labels, values, strict=True)]
            series_style = {
                'fontFamily': style['textStyle'].get('fontFamily', 'sans-serif'),
                'fontWeight': style['textStyle'].get('fontWeight', 'bold'),
            }
            if not isinstance(palette, list):
                series_style['color'] = palette
            base['series'] = [
                {
                    'type': 'wordCloud',
                    'shape': 'circle',
                    'sizeRange': [14, 64],
                    'rotationRange': [-45, 45],
                    'rotationStep': 30,
                    'gridSize': 6,
                    'drawOutOfBound': False,
                    'textStyle': series_style,
                    'data': data,
                }
            ]
            return base

        # ── Map ──
        if chart_type == 'map':
            if not x:
                raise ChartConfigError('Map chart requires a region-name field (x)')
            labels, values = cls.aggregate(df, x, value_field, agg)
            # NaN would poison the colour scale's upper bound.
            max_val = max(_finite(values) or [1]) or 1
            base['tooltip']['formatter'] = '<b>{b}</b><br/>{c}'
            base['visualMap'] = {
                'min': 0,
                'max': max_val,
                'left': 10,
                'bottom': 10,
                'text': [t('chart.range.high'), t('chart.range.low')],
                'textStyle': {'color': '#aaa', 'fontSize': 10},
                'inRange': {'color': ['#ffffff', '#fef0d9', '#fdcc8a', '#fc8d59', '#e34a33', '#b30000']},
            }
            base['series'] = [
                {
                    'type': 'map',
                    'map': 'china',
                    'roam': True,
                    'selectedMode': 'multiple',
                    'label': {'show': True, 'color': '#555', 'fontSize': 9, 'fontWeight': 400},
                    'emphasis': {
                        'label': {'show': True, 'color': '#fff', 'fontSize': 12, 'fontWeight': 'bold'},
                        'itemStyle': {
                            'areaColor': '#f46d43',
                            'shadowBlur': 10,
                            'shadowColor': 'rgba(0,0,0,0.15)',
                        },
                    },
                    'itemStyle': {
                        'borderColor': 'rgba(0,0,0,0.12)',
                        'borderWidth': 0.8,
                    },
                    'data': [{'name': n, 'value': v} for n, v in zip(labels, values, strict=True)],
                }
            ]
            return base

        # ── Intertopic distance map (the pyLDAvis left panel) ──
        if chart_type == 'topic_map':
            if not x or not y:
                raise ChartConfigError('Intertopic map needs both coordinate fields (x = PC1, y = PC2)')
            cls.require_columns(df, x, y)
            # ``x``/``y`` are refused by name above; the label and size fields must hold the same
            # line. A field the user TYPED into a box but that the table does not hold used to
            # read as "no label", so every bubble came out with an empty name at the floor radius
            # and the figure looked like a valid map of nothing — the rename-on-one-side / silent-
            # empty-figure this project bans. A blank box is genuinely "no labels" and stays.
            if label_field:
                cls.require_columns(df, label_field)
            if value_field:
                cls.require_columns(df, value_field)
            has_label = bool(label_field)
            has_size = bool(value_field)
            first = pd.to_numeric(df[x], errors='coerce').tolist()
            second = pd.to_numeric(df[y], errors='coerce').tolist()
            labels = [_localize_label(name) for name in (df[label_field].tolist() if has_label else [''] * len(df))]
            sizes = pd.to_numeric(df[value_field], errors='coerce').tolist() if has_size else [None] * len(df)
            # A coerced cell is NaN and the unsized branch fills None: pd.notna is the one test
            # that means "there is a real bubble size here".
            biggest = max((float(size) for size in sizes if pd.notna(size)), default=0.0)
            points = []
            for position, name in enumerate(labels):
                size = sizes[position]
                # AREA, not radius, carries the prevalence — a bubble drawn twice as wide for
                # twice the share reads as four times the share, which is the mistake the
                # original figure's square root is there to avoid. The floor is what keeps a
                # zero-share (or unsized) topic visible rather than absent from the map.
                radius = 10.0 if not biggest or pd.isna(size) else max(10.0, 70.0 * (float(size) / biggest) ** 0.5)
                points.append(
                    {
                        'value': [_json_safe(first[position]), _json_safe(second[position])],
                        'symbolSize': round(radius, 1),
                        'name': name,
                    }
                )
            base['grid'] = dict(_GRID)
            base['tooltip']['formatter'] = '{a}<br/>{b}'
            base['xAxis'] = {
                'type': 'value',
                'name': t('chart.axis.pc1'),
                'axisLabel': {'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                'splitLine': {'show': False},
            }
            base['yAxis'] = {
                'type': 'value',
                'name': t('chart.axis.pc2'),
                'axisLabel': {'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                'splitLine': {'show': False},
            }
            base['series'] = [
                {
                    'name': t('chart.series.topics'),
                    'type': 'scatter',
                    'data': points,
                    'itemStyle': {'color': 'rgba(59,130,249,0.35)', 'borderColor': color[0], 'borderWidth': 1},
                    'label': {
                        'show': has_label,
                        'formatter': '{b}',
                        'position': 'inside',
                        'color': '#1a1a1a',
                        'fontWeight': 'bold',
                        'fontSize': 12,
                    },
                    # The two reference lines the figure draws through the origin: without them
                    # the reader cannot tell "far apart" from "both near zero".
                    'markLine': {
                        'silent': True,
                        'symbol': 'none',
                        'lineStyle': {'color': '#555', 'width': 1},
                        'label': {'show': False},
                        'data': [{'xAxis': 0}, {'yAxis': 0}],
                    },
                }
            ]
            return base

        # ── Salient terms of one topic (the pyLDAvis right panel) ──
        if chart_type == 'topic_terms':
            if not x:
                raise ChartConfigError('Salient terms chart requires a term field (x)')
            if not y or not y2:
                raise ChartConfigError(
                    'Salient terms chart needs BOTH frequency fields (y = corpus-wide, y2 = within the topic)'
                )
            cls.require_columns(df, x, y, y2)
            terms = [str(name) for name in df[x].tolist()]
            overall = pd.to_numeric(df[y], errors='coerce').tolist()
            within = pd.to_numeric(df[y2], errors='coerce').tolist()
            y_disp, y2_disp = _localize_label(y), _localize_label(y2)
            base['grid'] = {**_GRID, 'left': 90}
            base['legend'] = {'data': [y_disp, y2_disp], 'top': 28, 'textStyle': _TEXT_STYLE}
            base['tooltip'] = {**base['tooltip'], 'trigger': 'axis', 'axisPointer': {'type': 'shadow'}}
            base['xAxis'] = {
                'type': 'value',
                'axisLabel': {'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                'splitLine': {'lineStyle': {'color': '#2a2a2a', 'type': 'dashed'}},
            }
            # ``inverse`` puts rank 1 at the top, which is how the term list is read; pandas
            # order alone would draw the most salient term at the bottom.
            base['yAxis'] = {
                'type': 'category',
                'data': terms,
                'inverse': True,
                'axisLabel': {'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                'axisLine': {'lineStyle': {'color': '#444'}},
                'axisTick': {'show': False},
            }
            base['series'] = [
                {
                    'name': y_disp,
                    'type': 'bar',
                    'data': [_json_safe(value) for value in overall],
                    'itemStyle': {'color': 'rgba(59,130,249,0.65)'},
                    'barGap': 0,
                },
                {
                    'name': y2_disp,
                    'type': 'bar',
                    'data': [_json_safe(value) for value in within],
                    'itemStyle': {'color': '#E15759'},
                },
            ]
            return base

        # ── Dual-axis line: two magnitudes on one time axis ──
        if chart_type == 'dual_line':
            if not x:
                raise ChartConfigError('Dual-axis line chart requires a category field (x)')
            if not y2:
                raise ChartConfigError('Dual-axis line chart requires a second value field (y2) — the right axis')
            # Display names only; the grouping below still reads the raw columns.
            left_name = _localize_label(y) if y else f'{t("chart.count")}（{_localize_label(x)}）'
            y2_name = _localize_label(y2)
            labels, left = cls.aggregate(df, x, y, agg)
            # Both series group by the SAME x, so they share the category axis by
            # construction; only the second series' values are wanted here.
            _, right = cls.aggregate(df, x, y2, agg2 or agg)
            base['grid'] = {**_GRID, 'right': 60}
            base['legend'] = {'data': [left_name, y2_name], 'top': 28, 'textStyle': _TEXT_STYLE}
            base['xAxis'] = {
                'type': 'category',
                'data': labels,
                'axisLabel': {'rotate': 35, 'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                'axisLine': {'lineStyle': {'color': '#444'}},
                'axisTick': {'lineStyle': {'color': '#444'}},
                'splitLine': {'show': False},
            }
            # A LIST is what makes ECharts draw two scales; each series then says which one
            # it belongs to. The right axis carries no grid lines, or the plot area becomes a
            # second graph paper laid over the first.
            base['yAxis'] = [
                {
                    'type': 'value',
                    'name': left_name,
                    'nameTextStyle': _TEXT_STYLE,
                    'axisLabel': {'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                    'axisLine': {'show': False},
                    'axisTick': {'show': False},
                    'splitLine': {'lineStyle': {'color': '#2a2a2a', 'type': 'dashed'}},
                },
                {
                    'type': 'value',
                    'name': y2_name,
                    'nameTextStyle': _TEXT_STYLE,
                    'position': 'right',
                    'axisLabel': {'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                    'axisLine': {'show': False},
                    'axisTick': {'show': False},
                    'splitLine': {'show': False},
                },
            ]
            base['series'] = [
                {
                    'name': left_name,
                    'type': 'line',
                    'yAxisIndex': 0,
                    'data': left,
                    'smooth': True,
                    'symbol': 'circle',
                    'symbolSize': 6,
                    'lineStyle': {'width': 2.5, 'color': color[0]},
                    'itemStyle': {'color': color[0]},
                },
                {
                    'name': y2_name,
                    'type': 'line',
                    'yAxisIndex': 1,
                    'data': right,
                    'smooth': True,
                    'symbol': 'rect',
                    'symbolSize': 6,
                    'lineStyle': {'width': 2.5, 'color': color[1], 'type': 'dashed'},
                    'itemStyle': {'color': color[1]},
                },
            ]
            if annotations:
                # On the LEFT series, whose values the shared category axis is built from: the
                # marker belongs to the time axis, not to either curve.
                base['series'][0]['markLine'] = _annotation_lines(_parse_annotations(annotations), labels, x)
            return base

        # ── 100% stacked share (any independent distribution over a category axis) ──
        if chart_type == 'stack_pct':
            stack_fields = [
                s.strip() for s in str(kwargs.get('stack_fields') or '').replace('，', ',').split(',') if s.strip()
            ]
            if not x:
                raise ChartConfigError('stack_pct chart requires a category field (x)')
            if not stack_fields:
                raise ChartConfigError('stack_pct chart requires stacked fields (stack_fields)')
            # One message shape for a missing column across every chart type, so a wrong field
            # name reads the same whether it is the axis or one of the stacked shares.
            cls.require_columns(df, x, *stack_fields)
            grouped = df.groupby(x, sort=False)
            keys = list(grouped.groups.keys())
            labels = [str(k) for k in keys]
            cols = {f: grouped[f].sum().reindex(keys).fillna(0).tolist() for f in stack_fields}
            # Each period is normalised to 100%, so the figure reads as shares whether the
            # source columns are already percentages or raw counts.
            totals = [sum(cols[f][i] for f in stack_fields) for i in range(len(labels))]
            series = [
                {
                    'name': _localize_label(f),
                    'type': 'bar',
                    'stack': 'total',
                    'data': [round(cols[f][i] / totals[i] * 100, 2) if totals[i] else 0.0 for i in range(len(labels))],
                    'barMaxWidth': 60,
                    'itemStyle': {'color': color[idx % len(color)]},
                }
                for idx, f in enumerate(stack_fields)
            ]
            base['grid'] = dict(_GRID)
            base['legend'] = {'data': [s['name'] for s in series], 'top': 28, 'textStyle': _TEXT_STYLE}
            base['xAxis'] = {'type': 'category', 'data': labels}
            base['yAxis'] = {'type': 'value', 'name': t('chart.col.share'), 'max': 100}
            base['series'] = series
            return base

        # ── Bar / Line ──
        if not x:
            raise ChartConfigError(f'{chart_type} chart requires a category field (x)')
        labels, values = cls.aggregate(df, x, y, agg)
        base['grid'] = dict(_GRID)
        base['xAxis'] = {
            'type': 'category',
            'data': labels,
            'axisLabel': {'rotate': 35, 'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
            'axisLine': {'lineStyle': {'color': '#444'}},
            'axisTick': {'lineStyle': {'color': '#444'}},
            'splitLine': {'show': False},
        }
        base['yAxis'] = {
            'type': 'value',
            'axisLabel': {'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
            'axisLine': {'show': False},
            'axisTick': {'show': False},
            'splitLine': {'lineStyle': {'color': '#2a2a2a', 'type': 'dashed'}},
        }

        if chart_type == 'bar':
            base['series'] = [
                {
                    'type': 'bar',
                    'data': values,
                    'barWidth': '55%',
                    'itemStyle': {
                        'borderRadius': [3, 3, 0, 0],
                        'color': color[0],
                    },
                    'emphasis': {'itemStyle': {'color': color[1]}},
                }
            ]
        elif chart_type == 'line':
            base['series'] = [
                {
                    'type': 'line',
                    'data': values,
                    'smooth': True,
                    'symbol': 'circle',
                    'symbolSize': 7,
                    'lineStyle': {'width': 2.5, 'color': color[0]},
                    'areaStyle': {
                        'color': {
                            'type': 'linear',
                            'x': 0,
                            'y': 0,
                            'x2': 0,
                            'y2': 1,
                            'colorStops': [
                                {'offset': 0, 'color': 'rgba(59,130,249,0.35)'},
                                {'offset': 1, 'color': 'rgba(59,130,249,0.02)'},
                            ],
                        },
                    },
                    'itemStyle': {'color': color[0]},
                    'emphasis': {
                        'itemStyle': {'color': color[1]},
                        'lineStyle': {'width': 3.5},
                    },
                }
            ]

        if annotations:
            base['series'][0]['markLine'] = _annotation_lines(_parse_annotations(annotations), labels, x)

        return base
