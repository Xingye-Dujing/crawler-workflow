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
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use('Agg')  # headless backend, safe for a web server
plt.rcParams['font.sans-serif'] = [
    'SimHei',
    'Microsoft YaHei',
    'WenQuanYi Micro Hei',
    'DejaVu Sans',
    'Arial Unicode MS',
    'sans-serif',
]
plt.rcParams['axes.unicode_minus'] = False

logger = logging.getLogger(__name__)

CHART_TYPES = ('bar', 'line', 'pie', 'scatter', 'histogram', 'box', 'heatmap', 'sankey', 'wordcloud', 'map')

# ── Professional colour palette (Nature/Science journal inspired) ──
CATEGORY_COLORS = [
    '#3B82F9',
    '#EF4444',
    '#10B981',
    '#F59E0B',
    '#8B5CF6',
    '#EC4899',
    '#06B6D4',
    '#F97316',
    '#6366F1',
    '#14B8A6',
    '#E11D48',
    '#0EA5E9',
    '#84CC16',
    '#D946EF',
    '#0284C7',
]
DIVERGING_CMAP = ['#0571B0', '#92C5DE', '#F7F7F7', '#F4A582', '#CA0020']
SEQUENTIAL_CMAP = ['#F7FCF0', '#E0F3DB', '#CCEBC5', '#A8DDB5', '#7BCCC4', '#4EB3D3', '#2B8CBE', '#0868AC', '#084081']

_TEXT_STYLE = {'color': '#e0e0e0', 'fontSize': 11, 'fontFamily': 'sans-serif'}
_AXIS_STYLE = {
    'axisLine': {'lineStyle': {'color': '#444'}},
    'axisTick': {'lineStyle': {'color': '#444'}},
    'axisLabel': {'color': '#aaa', 'fontSize': 10, 'fontFamily': 'sans-serif'},
    'splitLine': {'lineStyle': {'color': '#2a2a2a', 'type': 'dashed'}},
}
_GRID = {'left': 55, 'right': 20, 'top': 36, 'bottom': 36}

# ── Word cloud style presets ──
# Each preset defines textStyle options for the echarts-wordcloud extension.
# The 'color' field accepts a single string or an array (extension picks randomly).
WORDCLOUD_STYLES = {
    'vibrant': {
        'labelKey': 'wordcloudStyle.vibrant',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': [
                '#3B82F9',
                '#EF4444',
                '#10B981',
                '#F59E0B',
                '#8B5CF6',
                '#EC4899',
                '#06B6D4',
                '#F97316',
                '#6366F1',
                '#14B8A6',
                '#E11D48',
                '#0EA5E9',
                '#84CC16',
                '#D946EF',
                '#0284C7',
            ],
        },
    },
    'monoBlue': {
        'labelKey': 'wordcloudStyle.monoBlue',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': [
                '#03045E',
                '#023E8A',
                '#0077B6',
                '#0096C7',
                '#00B4D8',
                '#48CAE4',
                '#90E0EF',
                '#ADE8F4',
                '#CAF0F8',
            ],
        },
    },
    'monoOrange': {
        'labelKey': 'wordcloudStyle.monoOrange',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': ['#7B241C', '#A93226', '#CB4335', '#E74C3C', '#F1948A', '#F5B7B1', '#FADBD8', '#FDEDEC'],
        },
    },
    'pastel': {
        'labelKey': 'wordcloudStyle.pastel',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'normal',
            'color': [
                '#A8E6CF',
                '#DCEDC1',
                '#FFD3B6',
                '#FFAAA5',
                '#FF8B94',
                '#D4A5A5',
                '#9B9B9B',
                '#E8D5B7',
                '#F3E0F2',
            ],
        },
    },
    'ocean': {
        'labelKey': 'wordcloudStyle.ocean',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': [
                '#0A1F3F',
                '#1B4F72',
                '#21618C',
                '#2E86C1',
                '#3498DB',
                '#5DADE2',
                '#85C1E9',
                '#AED6F1',
                '#D4E6F1',
                '#EBF5FB',
            ],
        },
    },
    'sunset': {
        'labelKey': 'wordcloudStyle.sunset',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': ['#4A0E4E', '#801C5C', '#B83D65', '#E66A5D', '#F59E5C', '#FDD87A', '#FFF2B2', '#FFF8E1'],
        },
    },
    'forest': {
        'labelKey': 'wordcloudStyle.forest',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': [
                '#003F1C',
                '#006B2D',
                '#238B45',
                '#41AB5D',
                '#74C476',
                '#A1D99B',
                '#C7E9C0',
                '#E2F3DA',
                '#F4FBF1',
            ],
        },
    },
}

# These have no sane matplotlib equivalent without extra heavy dependencies
# (echarts-wordcloud, a sankey layout engine, GeoJSON map data) — they are
# ECharts-only. render_image() raises a clear ChartConfigError for these.
ECHARTS_ONLY_TYPES = ('wordcloud', 'sankey', 'map')


class ChartConfigError(ValueError):
    """Raised when the chart spec is missing required fields for the chosen type."""


class VisualizationService:
    """Builds chart specs from a DataFrame. Stateless / reusable."""

    # ── Shared data prep ────────────────────────────────────────

    @staticmethod
    def _aggregate(df: pd.DataFrame, x: str, y: str = None, agg: str = 'sum'):
        """Group by *x* and aggregate *y* (or count rows if y is None)."""
        if y and y in df.columns:
            numeric = pd.to_numeric(df[y], errors='coerce')
            grouped = numeric.groupby(df[x]).agg(agg)
        else:
            grouped = df.groupby(x).size()
        grouped = grouped.sort_index()
        return grouped.index.astype(str).tolist(), grouped.values.tolist()

    # ── ECharts option builder ───────────────────────────────────

    @classmethod
    def to_echarts_option(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        x: str = None,
        y: str = None,
        value_field: str = None,
        _series: str = None,
        agg: str = 'sum',
        title: str = '',
        **kwargs,
    ) -> dict:
        if chart_type not in CHART_TYPES:
            raise ChartConfigError(f'Unsupported chart type: {chart_type}')

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
                'trigger': 'item' if chart_type in ('pie', 'wordcloud', 'map', 'sankey') else 'axis',
                'backgroundColor': 'rgba(30,30,40,0.9)',
                'borderColor': '#444',
                'borderWidth': 1,
                'textStyle': {'color': '#eee', 'fontSize': 12, 'fontFamily': 'sans-serif'},
                'formatter': '{b}: {c}' if chart_type not in ('pie', 'sankey') else None,
            },
            'animationDuration': 800,
            'animationEasing': 'cubicOut',
        }

        # ── Pie ──
        if chart_type == 'pie':
            if not x:
                raise ChartConfigError('Pie chart requires a category field (x)')
            labels, values = cls._aggregate(df, x, y, agg)
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
            xs = pd.to_numeric(df[x], errors='coerce')
            ys = pd.to_numeric(df[y], errors='coerce')
            base['grid'] = dict(_GRID)
            base['xAxis'] = {
                'type': 'value',
                'name': x,
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['yAxis'] = {
                'type': 'value',
                'name': y,
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['tooltip']['formatter'] = f'<b>{{@[0]}}</b><br/>{x}: {{@[0]}}<br/>{y}: {{@[1]}}'
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
            values = pd.to_numeric(df[x], errors='coerce').dropna()
            counts, edges = _histogram_bins(values)
            labels_bin = [f'{e:.1f}' for e in edges[:-1]]
            base['grid'] = dict(_GRID)
            base['xAxis'] = {
                'type': 'category',
                'data': labels_bin,
                'name': x,
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['yAxis'] = {
                'type': 'value',
                'name': 'Frequency',
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
            if y and y in df.columns:
                # Grouped box plot: x = category, y = numeric value
                if not x:
                    raise ChartConfigError('Box plot requires a category field (x) for grouping')
                groups = [
                    (str(name), pd.to_numeric(group[y], errors='coerce').dropna()) for name, group in df.groupby(x)
                ]
                labels = [g[0] for g in groups]
                data = [_box_stats(g[1]) for g in groups]
                scatter_data = []
                for i, (_, vals) in enumerate(groups):
                    for v in vals.tolist():
                        scatter_data.append([i, v])
            elif x and x in df.columns:
                # Single box plot: x = numeric value (backward compat)
                values = pd.to_numeric(df[x], errors='coerce').dropna()
                stats = _box_stats(values)
                labels = [x]
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
            xcats, ycats, matrix = cls._pivot(df, x, y, value_field, agg)
            data = [[xi, yi, matrix[yi][xi]] for yi in range(len(ycats)) for xi in range(len(xcats))]
            vals = [row[2] for row in data]
            max_val = max(vals) if vals else 1
            min_val = min(vals) if vals else 0
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
                    'label': {
                        'show': True,
                        'color': '#ccc',
                        'fontSize': 10,
                        'fontFamily': 'sans-serif',
                    },
                    'emphasis': {
                        'itemStyle': {'shadowBlur': 8, 'shadowColor': 'rgba(0,0,0,0.4)'},
                    },
                }
            ]
            return base

        # ── Sankey ──
        if chart_type == 'sankey':
            if not x or not y:
                raise ChartConfigError('Sankey diagram requires a source field (x) and a target field (y)')
            nodes, links = cls._sankey_links(df, x, y, value_field, agg)
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

        # ── Word cloud ──
        if chart_type == 'wordcloud':
            if not x:
                raise ChartConfigError('Word cloud requires a text/category field (x)')
            if kwargs.get('tokenize'):
                labels, values = cls.tokenize_frequency(df, x)
            else:
                labels, values = cls._aggregate(df, x, value_field, agg)
            style_name = kwargs.get('wordcloud_style', 'vibrant')
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
            labels, values = cls._aggregate(df, x, value_field, agg)
            max_val = max(values, default=1) or 1
            base['tooltip']['formatter'] = '<b>{b}</b><br/>{c}'
            base['visualMap'] = {
                'min': 0,
                'max': max_val,
                'left': 10,
                'bottom': 10,
                'text': ['High', 'Low'],
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

        # ── Bar / Line ──
        if not x:
            raise ChartConfigError(f'{chart_type} chart requires a category field (x)')
        labels, values = cls._aggregate(df, x, y, agg)
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

        return base

    @staticmethod
    def tokenize_frequency(df: pd.DataFrame, column: str, top_n: int = 120):
        """Tokenize a free-text column into word frequencies for a word
        cloud. Uses jieba for Chinese segmentation (this app's crawler
        content is primarily Chinese); falls back to whitespace splitting
        for non-Chinese text if jieba isn't installed."""

        stopwords = {
            '的',
            '了',
            '是',
            '我',
            '你',
            '他',
            '她',
            '它',
            '这',
            '那',
            '在',
            '和',
            '就',
            '都',
            '也',
            '还',
            '不',
            '有',
            '与',
            '及',
            '但',
            '而',
            '被',
            '把',
            '为',
            '对',
            '啊',
            '吧',
            '呢',
            '吗',
            '哦',
            '呀',
            '一个',
            '一些',
            '这个',
            '那个',
            '什么',
            'the',
            'a',
            'an',
            'is',
            'are',
            'was',
            'were',
            'and',
            'or',
            'to',
            'of',
            'in',
            'it',
            'this',
            'that',
            'for',
            'on',
            'with',
            'as',
            'at',
            'by',
        }
        texts = df[column].dropna().astype(str).tolist()
        counter = Counter()
        try:
            for text in texts:
                for token in jieba.lcut(text):
                    token = token.strip()
                    if len(token) < 2 or token in stopwords or not any(c.isalnum() for c in token):
                        continue
                    counter[token] += 1
        except ImportError:
            for text in texts:
                for token in text.split():
                    token = token.strip().lower()
                    if len(token) < 2 or token in stopwords:
                        continue
                    counter[token] += 1
        top = counter.most_common(top_n)
        if not top:
            return [], []
        labels, values = zip(*top, strict=True)
        return list(labels), list(values)

    @staticmethod
    def _pivot(df: pd.DataFrame, x: str, y: str, value_field: str = None, agg: str = 'count'):
        """Build a y-by-x matrix for a heatmap: counts co-occurrences of
        (x, y) pairs, or aggregates value_field over each pair if given."""
        work = df[[x, y]].copy()
        if value_field and value_field in df.columns:
            work['_v'] = pd.to_numeric(df[value_field], errors='coerce')
            pivot = work.pivot_table(index=y, columns=x, values='_v', aggfunc=agg, fill_value=0)
        else:
            pivot = work.pivot_table(index=y, columns=x, aggfunc='size', fill_value=0)
        xcats = pivot.columns.astype(str).tolist()
        ycats = pivot.index.astype(str).tolist()
        matrix = pivot.values.tolist()
        return xcats, ycats, matrix

    @staticmethod
    def _sankey_links(df: pd.DataFrame, source: str, target: str, value_field: str = None, agg: str = 'count'):
        """Build ECharts sankey nodes+links from a source/target column pair
        (e.g. platform -> emotion), weighted by row count or value_field."""
        work = df[[source, target]].copy()
        work.columns = ['_s', '_t']
        if value_field and value_field in df.columns:
            work['_v'] = pd.to_numeric(df[value_field], errors='coerce')
            grouped = work.groupby(['_s', '_t'])['_v'].agg(agg).reset_index()
        else:
            grouped = work.groupby(['_s', '_t']).size().reset_index(name='_v')

        # Sankey requires distinct node names; if a value appears on both
        # sides (e.g. same label used as both source and target) ECharts
        # can still render it as one shared node, so no renaming is needed.
        nodes = sorted(set(grouped['_s'].astype(str)) | set(grouped['_t'].astype(str)))
        links = [
            {'source': str(row['_s']), 'target': str(row['_t']), 'value': float(row['_v'])}
            for _, row in grouped.iterrows()
            if row['_v']
        ]
        return nodes, links

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
    ) -> str:
        """Render the chart with matplotlib and return a base64 PNG data URI."""

        if chart_type not in CHART_TYPES:
            raise ChartConfigError(f'Unsupported chart type: {chart_type}')
        if chart_type in ECHARTS_ONLY_TYPES:
            raise ChartConfigError(
                f'"{chart_type}" is only available with engine=echarts '
                f'(no matplotlib equivalent without extra dependencies)'
            )

        fig, ax = plt.subplots(figsize=(7, 4.2), dpi=130)

        if chart_type == 'pie':
            labels, values = cls._aggregate(df, x, y, agg)
            ax.pie(values, labels=labels, autopct='%1.1f%%', textprops={'fontsize': 8})
        elif chart_type == 'scatter':
            ax.scatter(pd.to_numeric(df[x], errors='coerce'), pd.to_numeric(df[y], errors='coerce'), s=18)
            ax.set_xlabel(x)
            ax.set_ylabel(y)
        elif chart_type == 'histogram':
            ax.hist(pd.to_numeric(df[x], errors='coerce').dropna(), bins=20)
            ax.set_xlabel(x)
            ax.set_ylabel('count')
        elif chart_type == 'box':
            if y and y in df.columns:
                groups = [pd.to_numeric(group[y], errors='coerce').dropna().values for _, group in df.groupby(x)]
                grp_labels = [str(name) for name in df.groupby(x).groups]
                ax.boxplot(groups, labels=grp_labels)
                ax.set_xlabel(str(x))
            else:
                ax.boxplot(pd.to_numeric(df[x], errors='coerce').dropna(), labels=[x])
        elif chart_type == 'heatmap':
            xcats, ycats, matrix = cls._pivot(df, x, y, value_field, agg if value_field else 'count')
            im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
            ax.set_xticks(range(len(xcats)))
            ax.set_xticklabels(xcats, rotation=45, ha='right', fontsize=8)
            ax.set_yticks(range(len(ycats)))
            ax.set_yticklabels(ycats, fontsize=8)
            fig.colorbar(im, ax=ax)
        elif chart_type == 'line':
            labels, values = cls._aggregate(df, x, y, agg)
            ax.plot(labels, values, marker='o')
            ax.tick_params(axis='x', rotation=45)
        else:  # bar
            labels, values = cls._aggregate(df, x, y, agg)
            ax.bar(labels, values)
            ax.tick_params(axis='x', rotation=45)

        if title:
            ax.set_title(title)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', transparent=True)
        plt.close(fig)
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode('ascii')
        return f'data:image/png;base64,{encoded}'


def _histogram_bins(values: pd.Series, bins: int = 10):
    if values.empty:
        return [], [0, 1]
    counts, edges = pd.cut(values, bins=bins, retbins=True, duplicates='drop')
    hist = counts.value_counts().sort_index()
    return hist.tolist(), edges.tolist()


def _box_stats(values: pd.Series) -> list:
    if values.empty:
        return [0, 0, 0, 0, 0]
    q1, q2, q3 = values.quantile([0.25, 0.5, 0.75])
    iqr = q3 - q1
    lower = max(values.min(), q1 - 1.5 * iqr)
    upper = min(values.max(), q3 + 1.5 * iqr)
    return [float(lower), float(q1), float(q2), float(q3), float(upper)]
