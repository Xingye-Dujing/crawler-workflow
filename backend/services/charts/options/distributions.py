"""Distribution-shaped views: pie, histogram, box, word cloud and the GeoJSON map."""

import pandas as pd

from i18n import t

from ..contracts import ChartConfigError
from ..style import (
    _AXIS_STYLE,
    _GRID,
    _TEXT_STYLE,
    WORDCLOUD_STYLES,
    _box_stats,
    _finite,
    _histogram_bins,
    _localize_label,
)
from .base import ChartRequest, builder


@builder('pie')
def _pie(cls, base: dict, req: ChartRequest) -> dict:
    """Share-of-total pie; the legend sits on the right, labels on the slices."""
    if not req.x:
        raise ChartConfigError('Pie chart requires a category field (x)')
    labels, values = cls.aggregate(req.df, req.x, req.y, req.agg)
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


@builder('histogram')
def _histogram(cls, base: dict, req: ChartRequest) -> dict:
    """Binned counts of one numeric column (``x``); the bin labels are the category axis."""
    if not req.x:
        raise ChartConfigError('Histogram requires a numeric field (x)')
    cls.require_columns(req.df, req.x)
    color = base['color']
    values = pd.to_numeric(req.df[req.x], errors='coerce').dropna()
    counts, edges = _histogram_bins(values)
    labels_bin = [f'{e:.1f}' for e in edges[:-1]]
    base['grid'] = dict(_GRID)
    base['xAxis'] = {
        'type': 'category',
        'data': labels_bin,
        'name': _localize_label(req.x),
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


@builder('box')
def _box(cls, base: dict, req: ChartRequest) -> dict:
    """Box plot, grouped (``x`` category + ``y`` value) or single-column (``x`` numeric).

    A NAMED field that the table does not hold is refused by name, never swapped for a different
    column: the old ``elif x and x in df.columns`` fell through to drawing the CATEGORY column x
    as numeric when a typo'd ``y`` was absent, producing a plausible all-zero box whose axis was a
    phase name — the figure lied.
    """
    color = base['color']
    if req.y:
        cls.require_columns(req.df, req.y)
        # Grouped box plot: x = category, y = numeric value
        if not req.x:
            raise ChartConfigError('Box plot requires a category field (x) for grouping')
        cls.require_columns(req.df, req.x)
        groups = [
            (_localize_label(name), pd.to_numeric(group[req.y], errors='coerce').dropna())
            for name, group in req.df.groupby(req.x, sort=False)
        ]
        labels = [g[0] for g in groups]
        data = [_box_stats(g[1]) for g in groups]
        scatter_data = []
        for i, (_, vals) in enumerate(groups):
            for v in vals.tolist():
                scatter_data.append([i, v])
    elif req.x:
        cls.require_columns(req.df, req.x)
        # Single box plot: x = numeric value (backward compat)
        values = pd.to_numeric(req.df[req.x], errors='coerce').dropna()
        stats = _box_stats(values)
        labels = [_localize_label(req.x)]
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


@builder('wordcloud')
def _wordcloud(cls, base: dict, req: ChartRequest) -> dict:
    """Word cloud; ``tokenize`` splits ``x`` with jieba instead of aggregating it whole.

    ``wordcloud_style`` is a deliberate fallback, unlike the parameters that choose *data* or
    *cost*: a word cloud's palette is decoration, and an unknown name (a preset this build no
    longer ships, a caller that guessed one) must still produce the chart the rest of the request
    asked for. The node's own refusal rule applies wherever a silent default would change what the
    user got — the crawl board, the file format, the algorithm, the renderer.
    """
    if not req.x:
        raise ChartConfigError('Word cloud requires a text/category field (x)')
    if req.kwargs.get('tokenize'):
        labels, values = cls.tokenize_frequency(req.df, req.x)
    else:
        labels, values = cls.aggregate(req.df, req.x, req.value_field, req.agg)
    style_name = req.kwargs.get('wordcloud_style', 'vibrant')
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


@builder('map')
def _map(cls, base: dict, req: ChartRequest) -> dict:
    """China GeoJSON choropleth of ``x`` region names weighted by ``value_field``/``y``."""
    if not req.x:
        raise ChartConfigError('Map chart requires a region-name field (x)')
    labels, values = cls.aggregate(req.df, req.x, req.value_field, req.agg)
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
