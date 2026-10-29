"""Category-axis series: bar, line, dual-axis line and the 100% stacked share."""

from i18n import t

from ..contracts import ChartConfigError
from ..style import _GRID, _TEXT_STYLE, _annotation_lines, _localize_label, _parse_annotations
from .base import ChartRequest, builder


def _category_axes(base: dict, labels: list) -> None:
    """The plain category/value frame the bar and line families share (key order preserved)."""
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


@builder('bar')
def _bar(cls, base: dict, req: ChartRequest) -> dict:
    """Vertical bars; ``annotations`` draws the event markers on the first series."""
    if not req.x:
        raise ChartConfigError('bar chart requires a category field (x)')
    labels, values = cls.aggregate(req.df, req.x, req.y, req.agg)
    color = base['color']
    _category_axes(base, labels)
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
    if req.annotations:
        base['series'][0]['markLine'] = _annotation_lines(_parse_annotations(req.annotations), labels, req.x)
    return base


@builder('line')
def _line(cls, base: dict, req: ChartRequest) -> dict:
    """Smoothed line with the gradient area fill; ``annotations`` as on bar."""
    if not req.x:
        raise ChartConfigError('line chart requires a category field (x)')
    labels, values = cls.aggregate(req.df, req.x, req.y, req.agg)
    color = base['color']
    _category_axes(base, labels)
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
    if req.annotations:
        base['series'][0]['markLine'] = _annotation_lines(_parse_annotations(req.annotations), labels, req.x)
    return base


@builder('dual_line')
def _dual_line(cls, base: dict, req: ChartRequest) -> dict:
    """Two magnitudes on one time axis (``y`` left, ``y2`` right).

    A LIST of y-axes is what makes ECharts draw two scales; the right axis carries no grid lines,
    or the plot area becomes a second graph paper laid over the first. An annotation goes on the
    LEFT series, whose values built the shared category axis.
    """
    if not req.x:
        raise ChartConfigError('Dual-axis line chart requires a category field (x)')
    if not req.y2:
        raise ChartConfigError('Dual-axis line chart requires a second value field (y2) — the right axis')
    color = base['color']
    # Display names only; the grouping below still reads the raw columns.
    left_name = _localize_label(req.y) if req.y else f'{t("chart.count")}（{_localize_label(req.x)}）'
    y2_name = _localize_label(req.y2)
    labels, left = cls.aggregate(req.df, req.x, req.y, req.agg)
    # Both series group by the SAME x, so they share the category axis by
    # construction; only the second series' values are wanted here.
    _, right = cls.aggregate(req.df, req.x, req.y2, req.agg2 or req.agg)
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
    if req.annotations:
        # On the LEFT series, whose values the shared category axis is built from: the
        # marker belongs to the time axis, not to either curve.
        base['series'][0]['markLine'] = _annotation_lines(_parse_annotations(req.annotations), labels, req.x)
    return base


@builder('stack_pct')
def _stack_pct(cls, base: dict, req: ChartRequest) -> dict:
    """100% stacked shares: ``stack_fields`` (comma-separated) each contribute a bar per category.

    Each period is normalised to 100%, so the figure reads as shares whether the source columns
    are already percentages or raw counts.
    """
    stack_fields = [
        s.strip() for s in str(req.kwargs.get('stack_fields') or '').replace('，', ',').split(',') if s.strip()
    ]
    if not req.x:
        raise ChartConfigError('stack_pct chart requires a category field (x)')
    if not stack_fields:
        raise ChartConfigError('stack_pct chart requires stacked fields (stack_fields)')
    # One message shape for a missing column across every chart type, so a wrong field
    # name reads the same whether it is the axis or one of the stacked shares.
    cls.require_columns(req.df, req.x, *stack_fields)
    color = base['color']
    grouped = req.df.groupby(req.x, sort=False)
    keys = list(grouped.groups.keys())
    labels = [str(k) for k in keys]
    cols = {f: grouped[f].sum().reindex(keys).fillna(0).tolist() for f in stack_fields}
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
