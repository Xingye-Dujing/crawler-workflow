"""The two topic views behind the pyLDAvis-style panels: the map and one topic's salient terms."""

import pandas as pd

from i18n import t

from ..contracts import ChartConfigError
from ..style import _GRID, _TEXT_STYLE, _json_safe, _localize_label
from .base import ChartRequest, builder


@builder('topic_map')
def _topic_map(cls, base: dict, req: ChartRequest) -> dict:
    """Intertopic distance map: bubbles at (PC1, PC2), area carrying the topic's prevalence.

    ``x``/``y`` are refused by name; the label and size fields must hold the same line. A field
    the user TYPED into a box but that the table does not hold used to read as "no label", so
    every bubble came out with an empty name at the floor radius and the figure looked like a
    valid map of nothing — the rename-on-one-side / silent-empty-figure this project bans. A blank
    box is genuinely "no labels" and stays.
    """
    if not req.x or not req.y:
        raise ChartConfigError('Intertopic map needs both coordinate fields (x = PC1, y = PC2)')
    cls.require_columns(req.df, req.x, req.y)
    if req.label_field:
        cls.require_columns(req.df, req.label_field)
    if req.value_field:
        cls.require_columns(req.df, req.value_field)
    color = base['color']
    has_label = bool(req.label_field)
    has_size = bool(req.value_field)
    first = pd.to_numeric(req.df[req.x], errors='coerce').tolist()
    second = pd.to_numeric(req.df[req.y], errors='coerce').tolist()
    labels = [_localize_label(name) for name in (req.df[req.label_field].tolist() if has_label else [''] * len(req.df))]
    sizes = pd.to_numeric(req.df[req.value_field], errors='coerce').tolist() if has_size else [None] * len(req.df)
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


@builder('topic_terms')
def _topic_terms(cls, base: dict, req: ChartRequest) -> dict:
    """Salient terms of one topic: corpus-wide frequency (``y``) beside within-topic (``y2``)."""
    if not req.x:
        raise ChartConfigError('Salient terms chart requires a term field (x)')
    if not req.y or not req.y2:
        raise ChartConfigError(
            'Salient terms chart needs BOTH frequency fields (y = corpus-wide, y2 = within the topic)'
        )
    cls.require_columns(req.df, req.x, req.y, req.y2)
    terms = [str(name) for name in req.df[req.x].tolist()]
    overall = pd.to_numeric(req.df[req.y], errors='coerce').tolist()
    within = pd.to_numeric(req.df[req.y2], errors='coerce').tolist()
    y_disp, y2_disp = _localize_label(req.y), _localize_label(req.y2)
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
