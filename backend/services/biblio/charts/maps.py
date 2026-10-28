"""Map-shaped bibliometric views: dual map and choropleth geography.

The dual map stacks a journal column against a discipline column; the geography view
aggregates countries through ``services.biblio.geo`` so the drawn map and the printed
table agree.
"""

import math

import pandas as pd

from i18n import get_lang, t
from services.biblio.geo import aggregate, display
from services.charts.contracts import VARIATION_ROW_LIMIT

from .base import (
    DUAL_MAP_SIDE_LIMIT,
    GEO_BOTTOM,
    GEO_LEFT,
    GEO_RAMP,
    GEO_RIGHT,
    GEO_TOP,
    GRAPH_BOTTOM,
    GRAPH_TOP,
    BiblioChartError,
    _base_graph_series,
    _number,
    _require,
    _text,
)


def _side_slot(index: int, size: int) -> float:
    """One node's vertical slot in a dual-map column, centred when the column has one node."""
    return 500.0 if size < 2 else round(50 + index * (900 / (size - 1)), 2)


def dual_map(df: pd.DataFrame, base: dict) -> dict:
    _require(df, 'map', 'source', 'target', 'weight')
    _base_graph_series(base, base['title']['text'])
    rows = []
    seeds: dict[tuple[str, str], float] = {}
    for _, row in df.iterrows():
        side = _text(row['map']).lower()
        source = _text(row['source'])
        target = _text(row['target'])
        weight = _number(row['weight'], 0.0)
        if side not in ('journal', 'category', 'overlay') or not source:
            continue
        if not target:
            # A ``biblio`` dual-map table also lists its nodes (empty 终点) with their incident
            # weight. A journal cited by exactly one other journal is a real node with no
            # same-side link, and dropping it hides half of the overlay.
            if side != 'overlay' and weight > 0:
                seeds[(side, source)] = weight
            continue
        if weight > 0:
            rows.append((side, source, target, weight))
    if not rows:
        raise BiblioChartError(t('chart.biblio_no_links'))
    # A same-side edge is undirected, so BOTH of its endpoints belong to that side; reading only
    # `source` left a journal that ever appeared as a target without a position, dropping its links.
    left = {source for side, source, _t, _w in rows if side in ('journal', 'overlay')}
    left |= {target for side, _s, target, _w in rows if side == 'journal'}
    right = {target for side, _s, target, _w in rows if side in ('category', 'overlay')}
    right |= {source for side, source, _t, _w in rows if side == 'category'}
    left |= {name for (side, name) in seeds if side == 'journal'}
    right |= {name for (side, name) in seeds if side == 'category'}
    if not left or not right:
        raise BiblioChartError(t('chart.biblio_no_nodes'))
    # Keep the largest side within the drawing budget; the full table remains
    # in the CSV/LaTeX appendix. A dual map that prints 500 unreadable labels
    # is not a figure.
    left_names = sorted(left)[:DUAL_MAP_SIDE_LIMIT]
    right_names = sorted(right)[:DUAL_MAP_SIDE_LIMIT]
    positions = {}
    for index, name in enumerate(left_names):
        positions[('journal', name)] = (150, _side_slot(index, len(left_names)))
    for index, name in enumerate(right_names):
        positions[('category', name)] = (850, _side_slot(index, len(right_names)))
    incident: dict[tuple[str, str], float] = {}
    for side, source, target, weight in rows:
        if side == 'overlay':
            ends = [('journal', source), ('category', target)]
        elif side == 'journal':
            ends = [('journal', source), ('journal', target)]
        else:
            ends = [('category', source), ('category', target)]
        for end in ends:
            if end in positions:
                incident[end] = incident.get(end, 0.0) + weight
    max_incident = max(incident.values(), default=1.0) or 1.0
    # Two categories, so the legend toggles a side that actually exists: one graph series
    # cannot hold two legend entries, and a third entry for the overlay lines would be a
    # control that switches nothing off.
    categories = [
        {'name': t('chart.biblio_journal_map'), 'itemStyle': {'color': base['color'][0]}},
        {'name': t('chart.biblio_category_map'), 'itemStyle': {'color': base['color'][1]}},
    ]
    show_labels = len(positions) <= 120
    # Walk the positions, not the summed weights: a node the table listed without a
    # same-side link has an entry in `seeds` and none in `incident`, and iterating the
    # latter quietly deletes exactly the sparse end of a real dual map.
    data = []
    for (side, name), (x, y) in positions.items():
        value = max(incident.get((side, name), 0.0), seeds.get((side, name), 0.0))
        data.append(
            {
                'name': name,
                'x': x,
                'y': y,
                'value': round(value, 4),
                'symbolSize': round(8 + 30 * math.sqrt(max(0.0, value / max_incident)), 2),
                'category': 0 if side == 'journal' else 1,
                'label': {'show': show_labels, 'position': 'left' if side == 'journal' else 'right'},
            }
        )
    links = []
    max_weight = max((weight for *_rest, weight in rows), default=1.0) or 1.0
    for side, source, target, weight in rows:
        if side == 'overlay':
            a = positions.get(('journal', source))
            b = positions.get(('category', target))
        elif side == 'journal':
            a = positions.get(('journal', source))
            b = positions.get(('journal', target))
        else:
            a = positions.get(('category', source))
            b = positions.get(('category', target))
        if not a or not b:
            continue
        links.append(
            {
                'source': source,
                'target': target,
                'value': round(weight, 6),
                'lineStyle': {
                    'width': round(0.8 + 4 * math.sqrt(max(0.0, weight / max_weight)), 2),
                    'opacity': 0.16 if side == 'overlay' else 0.28,
                    # Both endpoints of a same-side link sit on the SAME column, so a straight
                    # or barely-curved line draws every journal–journal link on top of the
                    # column itself — a braid nobody can read. Bowing it out of the column is
                    # what makes the intra-map network visible at all.
                    'curveness': 0.45 if side == 'overlay' else 0.62,
                },
            }
        )
    if not links:
        raise BiblioChartError(t('chart.biblio_no_links'))
    base['legend'] = {
        'data': [entry['name'] for entry in categories],
        'top': 36,
        'left': 'center',
    }
    base['series'] = [
        {
            'type': 'graph',
            'layout': 'none',
            'roam': True,
            'draggable': True,
            # Room for the bowed same-side arcs AND the outward label columns: a journal name is
            # drawn to the left of its dot, so the reserve has to be wider than the longest label
            # or the canvas clips it. A percentage, because the same option is drawn in a 600px
            # preview panel and a full-screen canvas.
            'left': '12%',
            'top': GRAPH_TOP,
            'right': '12%',
            'bottom': GRAPH_BOTTOM,
            'categories': categories,
            'data': data,
            'links': links,
            'label': {
                'show': True,
                'fontSize': 9,
                'backgroundColor': 'rgba(255,255,255,0.82)',
                'padding': [2, 4],
                'borderRadius': 3,
            },
            'labelLayout': {'hideOverlap': True, 'moveOverlap': 'shiftY', 'draggable': True},
            'lineStyle': {'color': 'source'},
            'emphasis': {'focus': 'adjacency'},
        }
    ]
    return base


def variation(df: pd.DataFrame, base: dict) -> dict:
    """One marker per (node, consecutive slice pair): where a node's connection pattern moved.

    Position says WHEN, size and colour both say HOW MUCH — size survives a greyscale print,
    colour survives a dense column. A cell with no marker is not a zero: the node had no link in
    both slices of that pair, so nothing was measured, which is the distinction the algorithm
    refuses to invent a number for."""
    _require(df, '节点', '起始年', '结束年', '结构变化')
    base['tooltip']['trigger'] = 'item'
    base['tooltip']['formatter'] = None
    rows = []
    for _, row in df.iterrows():
        name = _text(row['节点'])
        score = _number(row['结构变化'], 0.0)
        start = int(_number(row['起始年'], 0))
        end = int(_number(row['结束年'], 0))
        if not name or score <= 0 or not start or not end or end <= start:
            continue
        rows.append((name, start, end, score, _text(row.get('新增邻居')), _text(row.get('消失邻居'))))
    if not rows:
        raise BiblioChartError(t('chart.biblio_no_variation'))

    pairs = sorted({(start, end) for _name, start, end, _score, _gained, _lost in rows})
    pair_at = {pair: position for position, pair in enumerate(pairs)}
    strongest: dict[str, float] = {}
    for name, _start, _end, score, _gained, _lost in rows:
        strongest[name] = max(score, strongest.get(name, 0.0))
    names = [name for name, _ in sorted(strongest.items(), key=lambda item: (-item[1], item[0]))]
    names = names[:VARIATION_ROW_LIMIT]
    shown = set(names)
    kept = [row for row in rows if row[0] in shown]
    max_score = max(row[3] for row in kept)

    base['grid'] = {'left': '26%', 'right': '18%', 'top': '12%', 'bottom': '18%', 'containLabel': True}
    base['xAxis'] = {
        'type': 'category',
        'data': [f'{start}→{end}' for start, end in pairs],
        'name': t('chart.biblio_pair'),
        'axisLabel': {'interval': 0, 'rotate': 30 if len(pairs) > 4 else 0, 'fontSize': 9},
    }
    base['yAxis'] = {
        'type': 'category',
        'data': names,
        'inverse': True,
        # Horizontal, never auto-rotated: a CJK name turned vertical is as tall as it is long,
        # so with 20 rows the neighbours print over each other (measured in Chrome).
        # `hideOverlap` drops a name that still cannot fit — the marker stays, and the CSV plus
        # the three-line table carry every mover.
        'axisLabel': {
            'fontSize': 9,
            'rotate': 0,
            'width': 200,
            'overflow': 'truncate',
            'hideOverlap': True,
            'interval': 0,
        },
    }
    base['visualMap'] = {
        'min': 0,
        'max': round(max_score, 4),
        'dimension': 2,
        'calculable': True,
        'orient': 'vertical',
        'right': 8,
        'top': 'middle',
        'itemWidth': 12,
        'itemHeight': 120,
        'textGap': 10,
        'text': [f'{round(max_score, 3)} bit', '0'],
        'textStyle': {'fontSize': 9},
    }
    data = []
    for name, start, _end, score, gained, lost in kept:
        data.append(
            {
                'value': [pair_at[(start, _end)], names.index(name), round(score, 6), name, gained, lost],
                # Radius follows the square root so equal CHANGES draw equal AREAS.
                'symbolSize': round(6 + 22 * math.sqrt(min(1.0, score / max_score)), 2),
            }
        )
    base['series'] = [
        {
            'type': 'scatter',
            'name': t('chart.biblio_variation'),
            'data': data,
            'emphasis': {'scale': False},
        }
    ]
    return base


#: How many regions get their name printed on the map. Every label on a 239-region world map is
#: no label at all; the rest answer on hover, and the LaTeX figure prints them as a ranked bar.
GEO_LABELS = 12


def geo_map(df: pd.DataFrame, base: dict) -> dict:
    """A world choropleth of one bibliometric entity type, keyed through the basemap's codes.

    The rows are the node table of a ``country`` graph (or any table whose 节点 column holds
    country/region names). Names are resolved to ISO codes and summed PER CODE, not per spelling:
    a corpus that says ``England``, ``Scotland`` and ``United Kingdom`` describes three rows of one
    region on this basemap, and drawing them as three would be a map of the spellings rather than
    of the world.

    Both facts the map cannot show are printed in the figure itself rather than only in a log the
    reader has already scrolled past: how many names the basemap does not know, and which names
    were merged into one region.
    """
    _require(df, '节点', '频次')
    lang = 'zh' if (get_lang() or 'zh') == 'zh' else 'en'
    result = aggregate(df.to_dict('records'))
    ordered = result['regions']
    unknown = result['unknown']
    if not ordered:
        raise BiblioChartError(t('chart.biblio_geo_none', names='、'.join(unknown[:5]) or t('chart.biblio_no_nodes')))

    max_value = ordered[0][1] or 1.0
    labelled = {iso for iso, _value, _names in ordered[:GEO_LABELS]}
    merged = [f'{"、".join(names[:3])}→{display(iso, lang)}' for iso, _value, names in ordered if names]
    notes = []
    if unknown:
        notes.append(t('chart.biblio_geo_unknown', n=len(unknown), names='、'.join(unknown[:3])))
    if merged:
        notes.append(t('chart.biblio_geo_merged', n=len(merged), detail='；'.join(merged[:4])))

    base['tooltip']['trigger'] = 'item'
    base['tooltip']['formatter'] = '{b}: {c}'
    if notes:
        # Inset and wrapped: at the preview panel's 400 px the one-line note used to run past the
        # canvas, which is the same "figure wider than the page" defect the printed views guard.
        base['title']['subtext'] = ' · '.join(notes)
        base['title']['subtextStyle'] = {'fontSize': 9, 'color': '#888', 'width': 330, 'overflow': 'break'}
        base['title']['left'] = GEO_LEFT
        base['title']['right'] = 12
    base['visualMap'] = {
        'min': 0,
        'max': round(max_value, 4),
        'left': GEO_LEFT + 4,
        'bottom': 22,
        'calculable': True,
        'orient': 'vertical',
        'itemWidth': 12,
        'itemHeight': 88,
        'textGap': 8,
        'text': [t('chart.range.high'), t('chart.range.low')],
        'textStyle': {'fontSize': 10},
        'inRange': {'color': GEO_RAMP},
    }
    base['series'] = [
        {
            'type': 'map',
            # The basemap is one file with both spellings of every region; the run's language picks
            # which column ECharts keys the data on, so the map and its labels stay in one language.
            'map': 'world_zh' if lang == 'zh' else 'world',
            'nameProperty': 'zh' if lang == 'zh' else 'name',
            'roam': True,
            'selectedMode': 'multiple',
            'left': GEO_LEFT,
            'right': GEO_RIGHT,
            'top': GEO_TOP,
            'bottom': GEO_BOTTOM,
            'aspectScale': 0.92,
            'label': {'show': False, 'fontSize': 10},
            'emphasis': {
                'label': {'show': True, 'fontSize': 11, 'fontWeight': 'bold'},
                'itemStyle': {'areaColor': '#f46d43'},
            },
            'itemStyle': {'borderColor': 'rgba(120,120,120,0.35)', 'borderWidth': 0.6},
            'data': [
                {
                    'name': display(iso, lang),
                    'value': round(value, 4),
                    'label': {'show': iso in labelled},
                }
                for iso, value, _names in ordered
            ],
        }
    ]
    return base
