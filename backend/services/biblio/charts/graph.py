"""Graph-shaped bibliometric views: knowledge graph, circular, concentric, 3D.

Node placement, label collision and the legend column are one subject: the first 180
nodes carry labels, larger graphs show a name on hover, and labels never sit on top of
one another in Chinese.
"""

import math

import pandas as pd

from i18n import t
from services.biblio.charts.base import (
    GRAPH_BOTTOM,
    GRAPH_LEFT,
    GRAPH_RIGHT,
    GRAPH_SCALE,
    GRAPH_TOP,
    LABEL_LIMIT,
    BiblioChartError,
    _base_graph_series,
    _categories,
    _legend,
    _node_rows,
    _number,
    _parsed,
    _require,
    _text,
)


def _label_position(x: float, y: float, center_x: float, center_y: float) -> str:
    dx, dy = x - center_x, y - center_y
    if abs(dx) >= abs(dy):
        return 'right' if dx >= 0 else 'left'
    return 'top' if dy >= 0 else 'bottom'


def _overlaps(rect, placed):
    left, bottom, right, top = rect
    return any(left < other[2] and other[0] < right and bottom < other[3] and other[1] < top for other in placed)


def _label_candidates(x, y, radius, width, height, direction):
    """Try the natural outside position, then shift sideways/up/down until clear."""
    horizontal = direction in ('right', 'left')
    sign = 1 if direction in ('right', 'top') else -1
    if horizontal:
        base_x = x + sign * (radius + width / 2.0 + 4.0)
        base_y = y
    else:
        base_x = x
        base_y = y + sign * (radius + height / 2.0 + 4.0)
    yield base_x, base_y
    for shift in range(8, 400, 8):
        if horizontal:
            yield base_x, base_y + shift
            yield base_x, base_y - shift
            yield base_x + shift * sign, base_y
            yield base_x - shift * sign, base_y
        else:
            yield base_x + shift, base_y
            yield base_x - shift, base_y
            yield base_x, base_y + shift * sign
            yield base_x, base_y - shift * sign


def _resolve_fixed_labels(rows: dict[str, dict], names: list[str], center_x: float, center_y: float):
    """Return label offsets in graph coordinates, or None when even 90 labels collide."""
    max_freq = max((_number(rows[name]['频次'], 0.0) for name in names), default=1.0) or 1.0
    ranked = sorted(names, key=lambda name: (-_number(rows[name]['频次'], 0.0), name))
    placements: dict[str, dict] = {}
    placed: list[tuple[float, float, float, float]] = []
    for name in ranked[:LABEL_LIMIT]:
        row = rows[name]
        x = _number(row.get('x'), 0.0)
        y = _number(row.get('y'), 0.0)
        frequency = _number(row['频次'], 0.0)
        font = 9.0 + 4.0 * math.sqrt(max(0.0, frequency / max_freq))
        width = (len(name) * font * 1.08 + 14.0) / GRAPH_SCALE
        height = (font * 1.45 + 10.0) / GRAPH_SCALE
        radius = (10.0 + 34.0 * math.sqrt(max(0.0, frequency / max_freq))) / GRAPH_SCALE / 2.0
        direction = _label_position(x, y, center_x, center_y)
        chosen = None
        for candidate_x, candidate_y in _label_candidates(x, y, radius, width, height, direction):
            rect = (
                candidate_x - width / 2,
                candidate_y - height / 2,
                candidate_x + width / 2,
                candidate_y + height / 2,
            )
            if not _overlaps(rect, placed):
                chosen = (candidate_x, candidate_y)
                placed.append(rect)
                break
        if chosen is None:
            continue
        placements[name] = {
            'font': round(font, 1),
            'x': round(chosen[0], 2),
            'y': round(chosen[1], 2),
            'offset': [round((chosen[0] - x) * GRAPH_SCALE, 1), round((chosen[1] - y) * GRAPH_SCALE, 1)],
        }
    return placements


def _activity(row: dict) -> list:
    """The node's per-year counts as ``[[year, count], …]``, oldest first.

    The graph's own ``年份序列`` column, shipped through to the browser so the network can be
    replayed slice by slice without a second request. Pairs rather than a dict because the order
    IS the answer, and a JSON object would have it re-sorted by whoever read it. A node with no
    series at all gets nothing: a play bar with one dimmed dot is worse than no play bar.
    """
    if '年份序列' not in row:
        return []
    parsed = _parsed(row.get('年份序列'), '年份序列')
    if not isinstance(parsed, dict):
        raise BiblioChartError(t('chart.biblio_bad_json', col='年份序列'))
    frames = []
    for key, count in parsed.items():
        try:
            year = int(float(str(key).strip()))
            value = float(count)
        except (TypeError, ValueError):
            continue
        frames.append([year, value])
    return sorted(frames)


def _node_data(rows: dict[str, dict], names: list[str], base: dict, *, layout: str, categories):
    use_clusters, category_names, category_index = categories
    max_freq = max((_number(rows[name]['频次'], 0.0) for name in names), default=1.0) or 1.0
    ranked = sorted(names, key=lambda name: (-_number(rows[name]['频次'], 0.0), name))
    labelled = set(ranked[:LABEL_LIMIT]) if len(names) > LABEL_LIMIT else set(names)
    xs = [_number(rows[name].get('x'), 0.0) for name in names]
    ys = [_number(rows[name].get('y'), 0.0) for name in names]
    center_x = sum(xs) / len(xs) if xs else 0.0
    center_y = sum(ys) / len(ys) if ys else 0.0
    placements = _resolve_fixed_labels(rows, names, center_x, center_y) if layout == 'none' else {}
    data = []
    for name in names:
        row = rows[name]
        burst = _number(row.get('突现强度'), 0.0) if '突现强度' in row else 0.0
        category_key = (
            f'#{_text(row["聚类"])} {_text(row["聚类标签"]) or "#" + _text(row["聚类"])}'
            if use_clusters
            else category_names[0]
        )
        item_style = {'color': base['color'][category_index[category_key] % len(base['color'])]}
        if burst > 0:
            item_style['borderColor'] = '#e74c3c'
            item_style['borderWidth'] = 2.5
        frequency = _number(row['频次'], 0.0)
        x = _number(row.get('x'), 0.0)
        y = _number(row.get('y'), 0.0)
        size = round(10.0 + 34.0 * math.sqrt(max(0.0, frequency / max_freq)), 2)
        placement = placements.get(name)
        label = {
            'show': placement is not None if layout == 'none' else name in labelled,
            'fontSize': placement['font']
            if placement
            else round(9 + 4.0 * math.sqrt(max(0.0, frequency / max_freq)), 1),
            'fontFamily': 'sans-serif',
        }
        item = {
            'name': name,
            'value': round(frequency, 4),
            'symbolSize': size,
            'category': category_index[category_key],
            'itemStyle': item_style,
            'label': label,
        }
        activity = _activity(row)
        if activity:
            item['yearSeries'] = activity
        if layout == 'none':
            item['x'] = x
            item['y'] = y
            if placement:
                label.update({'position': 'inside', 'offset': placement['offset']})
        else:
            label['position'] = _label_position(
                _number(row.get('x'), 0.0),
                _number(row.get('y'), 0.0),
                center_x,
                center_y,
            )
        data.append(item)
    return data


def _graph_links(rows: dict[str, dict], names: list[str]) -> dict[tuple[str, str], dict]:
    links: dict[tuple[str, str], dict] = {}
    for name in names:
        for item in _parsed(rows[name].get('连接'), '连接'):
            if not isinstance(item, dict):
                continue
            target = _text(item.get('target'))
            if target not in rows or target == name:
                continue
            left, right = sorted((name, target))
            value = _number(item.get('value'), 0.0)
            if (left, right) not in links or value > links[(left, right)]['value']:
                links[(left, right)] = {'source': left, 'target': right, 'value': round(value, 6)}
    if not links:
        raise BiblioChartError(t('chart.biblio_no_links'))
    biggest = max(link['value'] for link in links.values()) or 1.0
    return {
        key: {
            **link,
            'lineStyle': {
                'width': round(1.0 + 4.0 * math.sqrt(max(0.0, link['value'] / biggest)), 2),
                'opacity': 0.38,
            },
        }
        for key, link in links.items()
    }


def _graph_option(df: pd.DataFrame, base: dict, *, layout: str, require_coordinates: bool) -> dict:
    rows, names = _node_rows(df, require_coordinates=require_coordinates)
    categories = _categories(rows, names, df)
    data = _node_data(rows, names, base, layout=layout, categories=categories)
    links = _graph_links(rows, names)
    base['legend'] = _legend(categories[1])
    series = {
        'type': 'graph',
        'layout': layout,
        'roam': True,
        'draggable': True,
        'left': GRAPH_LEFT,
        'top': GRAPH_TOP,
        'right': GRAPH_RIGHT,
        'bottom': GRAPH_BOTTOM,
        # A rotated label cannot be pulled back into the reserved band — the solver moves a box,
        # not a glyph turned 90°, and the browser measured one standing on the chart title.
        # Circular terms read horizontally here, like every other view in this project.
        'circular': {'rotateLabel': False},
        'categories': [{'name': name} for name in categories[1]],
        'data': data,
        'links': sorted(links.values(), key=lambda item: (-item['value'], item['source'], item['target'])),
        'label': {
            'show': True,
            'color': '#222',
            'backgroundColor': 'rgba(255,255,255,0.82)',
            'borderColor': 'rgba(0,0,0,0.08)',
            'borderWidth': 1,
            'borderRadius': 3,
            'padding': [2, 4],
        },
        'labelLayout': {'hideOverlap': True, 'moveOverlap': 'shiftY', 'draggable': True},
        'lineStyle': {'color': 'source', 'curveness': 0.12},
        'emphasis': {'focus': 'adjacency', 'lineStyle': {'width': 4}, 'label': {'show': True}},
    }
    base['series'] = [series]
    return base


def knowledge_graph(df: pd.DataFrame, base: dict) -> dict:
    _base_graph_series(base, base['title']['text'])
    return _graph_option(df, base, layout='none', require_coordinates=True)


def circular(df: pd.DataFrame, base: dict) -> dict:
    _base_graph_series(base, base['title']['text'])
    return _graph_option(df, base, layout='circular', require_coordinates=False)


def _ring_year(row: dict) -> int:
    """The node's first appearance year, read from its own per-year series.

    ``首年`` is only written when clustering ran, while ``年份序列`` is on every entity table —
    reading the cluster columns would make this view refuse tables the timezone view can draw.
    """
    for year, count in _activity(row):
        if count:
            return int(year)
    return int(_number(row.get('首年'), 0))


def concentric(df: pd.DataFrame, base: dict) -> dict:
    """One ring per first-appearance year, oldest at the centre, frequency running clockwise.

    This is a LAYOUT, not a time axis: the ``timezone`` view spreads nodes along x by year, while
    here every year becomes a circle and the reader sees at a glance whether a field's vocabulary
    accumulates at the rim (new terms keep arriving) or stays in the middle (a stable core).
    """
    _require(df, '节点', '年份序列', '频次')
    _base_graph_series(base, base['title']['text'])
    rows, names = _node_rows(df)
    buckets: dict[int, list[str]] = {}
    unknown: list[str] = []
    for name in names:
        year = _ring_year(rows[name])
        if year:
            buckets.setdefault(year, []).append(name)
        else:
            unknown.append(name)
    if not buckets:
        raise BiblioChartError(t('chart.biblio_no_years'))
    rings: list[tuple[str, list[str]]] = [(str(year), buckets[year]) for year in sorted(buckets)]
    if unknown:
        # A node with no year at all cannot be placed on a time ring; it gets its own outer ring
        # and a legend entry that says so, because dropping it would hide a node the table has.
        rings.append((t('chart.biblio_ring_unknown'), unknown))
    max_freq = max((_number(rows[name]['频次'], 0.0) for name in names), default=1.0) or 1.0
    ranked = sorted(names, key=lambda name: (-_number(rows[name]['频次'], 0.0), name))
    labelled = set(ranked[:LABEL_LIMIT]) if len(names) > LABEL_LIMIT else set(names)
    data = []
    for ring, (_label, ring_names) in enumerate(rings):
        radius = float(ring + 1)
        ordered = sorted(ring_names, key=lambda name: (-_number(rows[name]['频次'], 0.0), name))
        for index, name in enumerate(ordered):
            # A phase turn per ring keeps consecutive years from lining up into spokes, which
            # would read as columns and hide that these are separate circles.
            angle = 2.0 * math.pi * index / len(ordered) + 0.35 * ring
            frequency = _number(rows[name]['频次'], 0.0)
            data.append(
                {
                    'name': name,
                    'value': round(frequency, 4),
                    'x': round(radius * math.cos(angle), 6),
                    'y': round(radius * math.sin(angle), 6),
                    'symbolSize': round(10.0 + 26.0 * math.sqrt(max(0.0, frequency / max_freq)), 2),
                    'category': ring,
                    'itemStyle': {'color': base['color'][ring % len(base['color'])]},
                    'label': {
                        'show': name in labelled,
                        'position': 'right',
                        'fontSize': 10,
                        'fontFamily': 'sans-serif',
                    },
                }
            )
    links = _graph_links(rows, names)
    base['title']['subtext'] = t('chart.biblio_ring_rule', rings=len(rings))
    # ECharts does not wrap a subtitle by itself: at the preview's 400 px the English note ran
    # off the right edge (measured), so its width is stated and long text breaks instead.
    base['title']['subtextStyle'] = {'fontSize': 11, 'overflow': 'break', 'width': 330}
    base['legend'] = _legend([label for label, _ in rings])
    # The rule is painted under the title, so the legend has to start below it as well: at its
    # default ``top: 40`` the first year entry sat on the note in a real 400 px preview.
    base['legend']['top'] = 78
    base['series'] = [
        {
            'type': 'graph',
            'layout': 'none',
            'roam': True,
            'draggable': False,
            'left': GRAPH_LEFT,
            # The ring rule sits under the title. Measured in a real browser at the preview's
            # 400 px: the note wraps to two lines there and the innermost ring's year label
            # landed on it, so this one view pays for the note in its reserved band.
            'top': GRAPH_TOP + 30,
            'right': GRAPH_RIGHT,
            'bottom': GRAPH_BOTTOM,
            'categories': [{'name': label} for label, _ in rings],
            'data': data,
            'links': sorted(links.values(), key=lambda item: (-item['value'], item['source'], item['target'])),
            'label': {
                'show': True,
                'color': '#222',
                'backgroundColor': 'rgba(255,255,255,0.82)',
                'borderColor': 'rgba(0,0,0,0.08)',
                'borderWidth': 1,
                'borderRadius': 3,
                'padding': [2, 4],
            },
            'labelLayout': {'hideOverlap': True, 'moveOverlap': 'shiftY'},
            'lineStyle': {'color': 'source', 'curveness': 0.12},
            'emphasis': {'focus': 'adjacency', 'lineStyle': {'width': 4}, 'label': {'show': True}},
        }
    ]
    return base


def graph3d(df: pd.DataFrame, base: dict) -> dict:
    rows, names = _node_rows(df, require_coordinates=True)
    _base_graph_series(base, base['title']['text'])
    max_freq = max((_number(rows[name]['频次'], 0.0) for name in names), default=1.0) or 1.0
    xs = [_number(rows[name]['x'], 0.0) for name in names]
    ys = [_number(rows[name]['y'], 0.0) for name in names]
    zs = [_number(rows[name].get('中介中心性'), 0.0) if '中介中心性' in df.columns else 0.0 for name in names]
    if not any(zs):
        zs = [_number(rows[name]['频次'], 0.0) / max_freq for name in names]
    min_x, max_x, min_y, max_y, min_z, max_z = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
    span_x = max_x - min_x or 1.0
    span_y = max_y - min_y or 1.0
    span_z = max_z - min_z or 1.0
    positions = {
        name: (
            round(100 * (xs[i] - min_x) / span_x, 3),
            round(100 * (ys[i] - min_y) / span_y, 3),
            round(100 * (zs[i] - min_z) / span_z, 3),
        )
        for i, name in enumerate(names)
    }
    ranked = sorted(names, key=lambda name: (-_number(rows[name]['频次'], 0.0), name))
    labelled = set(ranked[:40])
    data = []
    for name in names:
        frequency = _number(rows[name]['频次'], 0.0)
        size = round(4 + 18 * math.sqrt(max(0.0, frequency / max_freq)), 2)
        data.append(
            {
                'name': name,
                'value': [*positions[name], round(frequency, 4)],
                'symbolSize': size,
                'itemStyle': {'color': base['color'][0], 'opacity': 0.88},
                'label': {'show': name in labelled, 'formatter': '{b}', 'fontSize': 9},
            }
        )
    links = _graph_links(rows, names)
    biggest = max(link['value'] for link in links.values()) or 1.0
    line_data = []
    for link in links.values():
        left = positions[link['source']]
        right = positions[link['target']]
        size = round(1.8 + 3.0 * math.sqrt(max(0.0, link['value'] / biggest)), 2)
        for step in range(1, 10):
            ratio = step / 10.0
            line_data.append(
                {
                    'value': [
                        round(left[0] + (right[0] - left[0]) * ratio, 3),
                        round(left[1] + (right[1] - left[1]) * ratio, 3),
                        round(left[2] + (right[2] - left[2]) * ratio, 3),
                    ],
                    'symbolSize': size,
                }
            )
    base['tooltip']['formatter'] = None
    base['grid3D'] = {
        'viewDistance': 180,
        'alpha': 22,
        'beta': 35,
        'boxWidth': 100,
        'boxDepth': 100,
        'boxHeight': 100,
        'axisLine': {'lineStyle': {'color': '#999'}},
        'axisLabel': {'show': False},
        'axisPointer': {'show': False},
        'light': {'main': {'intensity': 1.2, 'alpha': 30, 'beta': 40}},
    }
    base['xAxis3D'] = {'name': 'X', 'min': 0, 'max': 100, 'axisLabel': {'show': False}}
    base['yAxis3D'] = {'name': 'Y', 'min': 0, 'max': 100, 'axisLabel': {'show': False}}
    base['zAxis3D'] = {'name': 'Centrality', 'min': 0, 'max': 100, 'axisLabel': {'show': False}}
    base['series'] = [
        {
            'type': 'scatter3D',
            'name': t('chart.biblio_links'),
            'data': line_data,
            'symbolSize': 2.2,
            'itemStyle': {'color': '#666', 'opacity': 0.45},
            'silent': True,
        },
        {'type': 'scatter3D', 'name': t('chart.biblio_nodes'), 'data': data, 'emphasis': {'focus': 'self'}},
    ]
    return base
