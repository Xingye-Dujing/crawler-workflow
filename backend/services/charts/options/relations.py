"""Relationship views: scatter, the two heatmaps, sankey and the force-directed network."""

import pandas as pd

from ..contracts import ChartConfigError
from ..style import _AXIS_STYLE, _GRID, _TEXT_STYLE, CATEGORY_COLORS, _finite, _localize_label
from .base import ChartRequest, builder


@builder('scatter')
def _scatter(cls, base: dict, req: ChartRequest) -> dict:
    """Two numeric fields on value axes; the tooltip names the columns."""
    if not req.x or not req.y:
        raise ChartConfigError('Scatter chart requires both x and y fields')
    cls.require_columns(req.df, req.x, req.y)
    color = base['color']
    xs = pd.to_numeric(req.df[req.x], errors='coerce')
    ys = pd.to_numeric(req.df[req.y], errors='coerce')
    base['grid'] = dict(_GRID)
    base['xAxis'] = {
        'type': 'value',
        'name': _localize_label(req.x),
        'nameTextStyle': _TEXT_STYLE,
        **_AXIS_STYLE,
    }
    base['yAxis'] = {
        'type': 'value',
        'name': _localize_label(req.y),
        'nameTextStyle': _TEXT_STYLE,
        **_AXIS_STYLE,
    }
    base['tooltip']['formatter'] = (
        f'<b>{{@[0]}}</b><br/>{_localize_label(req.x)}: {{@[0]}}<br/>{_localize_label(req.y)}: {{@[1]}}'
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


@builder('heatmap')
def _heatmap(cls, base: dict, req: ChartRequest) -> dict:
    """Two category fields against an aggregated value, painted by the shared heatmap frame."""
    if not req.x or not req.y:
        raise ChartConfigError('Heatmap requires two category fields (x and y)')
    xcats, ycats, matrix = cls.pivot(req.df, req.x, req.y, req.value_field, req.agg)
    # Bounds come from the usable numbers only: an all-missing cell makes
    # the aggregate NaN, and NaN bounds would leave the colour scale blank.
    vals = _finite(v for row in matrix for v in row)
    return cls._apply_heatmap_option(base, xcats, ycats, matrix, min(vals) if vals else 0, max(vals) if vals else 1)


@builder('model_agreement')
def _model_agreement(cls, base: dict, req: ChartRequest) -> dict:
    """Pairwise label agreement between models, drawn as a square heatmap.

    Reads the tidy multi-model table by its 模型 / 标签 / 原行 columns (overridable through
    ``model_field``/``agreement_label_field``/``id_field``), so a renamed analysis output refuses
    by name rather than rendering a matrix of the wrong thing.
    """
    cats, matrix = cls._agreement_matrix(
        req.df,
        req.kwargs.get('model_field') or '模型',
        req.kwargs.get('agreement_label_field'),
        req.kwargs.get('id_field') or '原行',
    )
    return cls._apply_heatmap_option(base, cats, cats, matrix, 0, 100)


@builder('sankey')
def _sankey(cls, base: dict, req: ChartRequest) -> dict:
    """Weighted flows from field ``x`` to field ``y``."""
    if not req.x or not req.y:
        raise ChartConfigError('Sankey diagram requires a source field (x) and a target field (y)')
    nodes, links = cls.sankey_links(req.df, req.x, req.y, req.value_field, req.agg)
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


@builder('network')
def _network(cls, base: dict, req: ChartRequest) -> dict:
    """Force-directed co-occurrence/flow graph.

    ``center_node`` keeps only that node's ego-network (it, its neighbours and the edges among
    them) — a real figure, not a hover hint that vanishes before it can be saved. Node size is
    AREA-carried evidence of the summed link weight; the layout starts circular so the same table
    does not produce a different-looking figure twice.
    """
    if not req.x or not req.y:
        raise ChartConfigError('Network graph requires a source field (x) and a target field (y)')
    nodes, links = cls.sankey_links(req.df, req.x, req.y, req.value_field, req.agg)
    if not links:
        # The sankey would draw an empty frame and look like a finished figure; a graph
        # with no edge is not "a sparse relationship network", it is nothing measured.
        raise ChartConfigError(
            f'network graph has no edges: every {req.x}/{req.y} pair was blank, zero-weighted or unvalued'
        )
    center = str(req.kwargs.get('center_node') or '').strip()
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
