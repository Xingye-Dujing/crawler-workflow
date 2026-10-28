"""ECharts options for the bibliometric views.

These builders read the fixed columns emitted by ``services.biblio.metrics``.
A missing required column is a named refusal, never an empty frame. Options
are plain JSON: no ``renderItem`` callbacks, so a preview, a saved chart and a
fullscreen render all draw the same figure.

Label handling is deliberately conservative: the first 180 nodes are labelled,
larger graphs show a node's full name on hover. ``labelLayout`` shifts labels
vertically so Chinese terms do not sit on top of one another.
"""

import json
import math

import pandas as pd

from i18n import get_lang, t
from services.biblio.geo import aggregate, display
from services.chart_contracts import (
    OVERLAY_ROW_LIMIT,
    OVERLAY_TOPIC_LIMIT,
    POLARITY_COLORS,
    POLARITY_LABELS,
    VARIATION_ROW_LIMIT,
)

#: Node labels beyond this are hover-only. A 500-node knowledge graph with every
#: label painted is not a figure; it is a smudge. The bubbles stay drawn.
LABEL_LIMIT = 70
#: Approximate pixels represented by one graph coordinate unit. The collision
#: resolver places labels in coordinate space and hands ECharts a pixel offset.
GRAPH_SCALE = 1.5
#: Characters of a cluster label shown in the legend column.
LEGEND_LABEL_WIDTH = 14
#: The band a graph series is drawn inside: the title and subtitle above, the cluster
#: legend column on the right. Node labels that wander into either read as a rendering bug.
GRAPH_TOP = 70
GRAPH_RIGHT = 170
GRAPH_LEFT = 24
GRAPH_BOTTOM = 30
#: A dual map draws two stacked label columns; past this many names per side the
#: column is taller than the canvas, so the tail belongs in the CSV/LaTeX table.
DUAL_MAP_SIDE_LIMIT = 80
#: The colour ramp of a choropleth, light to dark. Shared with the LaTeX figure so the printed
#: ranking and the drawn map agree about what "high" looks like.
GEO_RAMP = ['#ffffff', '#fef0d9', '#fdcc8a', '#fc8d59', '#e34a33', '#b30000']
#: The band a choropleth is drawn inside. Measured in Chrome: with ECharts' own centring, the
#: label of the easternmost country ran past the preview panel's edge and was cut mid-word. The
#: right gutter is where that label lands instead, and the bottom band is the colour bar's.
GEO_LEFT = 12
GEO_RIGHT = 96
GEO_TOP = 74
GEO_BOTTOM = 96


class BiblioChartError(ValueError):
    """A chart refusal that the Visualize node reports as its own failure."""


def _require(df: pd.DataFrame, *columns: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise BiblioChartError(t('chart.biblio_missing', cols='、'.join(missing)))


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ''
    return str(value).strip()


def _number(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _parsed(value, column: str) -> list | dict:
    if isinstance(value, (list, dict)):
        return value
    text = _text(value)
    if not text:
        return []
    try:
        return json.loads(text)
    except (TypeError, ValueError) as exc:
        raise BiblioChartError(t('chart.biblio_bad_json', col=column)) from exc


def _base_graph_series(base: dict, title: str) -> None:
    base['tooltip']['trigger'] = 'item'
    base['tooltip']['formatter'] = '{b}: {c}'
    base['title']['text'] = title or base['title']['text']


def _node_rows(df: pd.DataFrame, *, require_coordinates: bool = False):
    columns = ('节点', '连接', '频次')
    if require_coordinates:
        columns = ('节点', 'x', 'y', '连接', '频次')
    _require(df, *columns)
    rows: dict[str, dict] = {}
    for _, row in df.iterrows():
        name = _text(row['节点'])
        if name and name not in rows:
            rows[name] = row
    names = list(rows)
    if not names:
        raise BiblioChartError(t('chart.biblio_no_nodes'))
    return rows, names


def _categories(rows: dict[str, dict], names: list[str], frame: pd.DataFrame):
    use_clusters = '聚类' in frame.columns and '聚类标签' in frame.columns
    category_names: list[str] = []
    category_index: dict[str, int] = {}
    if use_clusters:
        shown: set[str] = set()
        for name in names:
            cluster = _text(rows[name]['聚类'])
            label = _text(rows[name]['聚类标签']) or f'#{cluster}'
            key = f'#{cluster} {label}'
            if key not in category_index:
                # Two clusters whose truncated heads agree would merge into one legend entry,
                # so the tie keeps the full label. Colour is taken by index, never by name.
                short = _legend_name(key)
                entry = short if short not in shown else key
                shown.add(entry)
                category_index[key] = len(category_names)
                category_names.append(entry)
    else:
        category_names = [t('chart.biblio_single_category')]
        category_index = {category_names[0]: 0}
    return use_clusters, category_names, category_index


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


def _legend_name(key: str) -> str:
    """One cluster's legend entry: ``#k`` plus a head of the LLR label, never the whole line.

    A five-term label is wider than the scroll pager is tall, and the two boxes collided in a
    real browser. The full label is in the cluster table, the CSV and the tooltip.
    """
    return key if len(key) <= LEGEND_LABEL_WIDTH else f'{key[: LEGEND_LABEL_WIDTH - 1]}…'


def _legend(category_names: list[str]) -> dict:
    return {
        'data': category_names,
        # A plain legend has no page marker: the ``1/1`` it scrolls to used to sit on top of the
        # first cluster's text. Entries are short enough that the column never needs paging.
        'type': 'plain',
        'orient': 'vertical',
        'right': 8,
        'top': 40,
        'itemGap': 6,
        'textStyle': {'color': '#444', 'fontSize': 10, 'fontFamily': 'sans-serif'},
        'itemWidth': 10,
        'itemHeight': 10,
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


def _knowledge_graph(df: pd.DataFrame, base: dict) -> dict:
    _base_graph_series(base, base['title']['text'])
    return _graph_option(df, base, layout='none', require_coordinates=True)


def _circular(df: pd.DataFrame, base: dict) -> dict:
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


def _concentric(df: pd.DataFrame, base: dict) -> dict:
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


def _cluster_timeline(df: pd.DataFrame, base: dict) -> dict:
    _require(df, '节点', '聚类', '聚类标签', '首年', '末年', '频次')
    _base_graph_series(base, base['title']['text'])
    clusters: dict[str, dict] = {}
    for _, row in df.iterrows():
        name = _text(row['节点'])
        if not name:
            continue
        cluster = _text(row['聚类'])
        group = clusters.setdefault(cluster, {'label': _text(row['聚类标签']) or f'#{cluster}', 'nodes': []})
        group['nodes'].append(row)
    if not clusters:
        raise BiblioChartError(t('chart.biblio_no_nodes'))
    ordered = sorted(clusters.items(), key=lambda item: (-len(item[1]['nodes']), item[0]))[:12]
    categories = [f'#{cluster} {group["label"][:16]}' for cluster, group in ordered]
    years = [int(_number(row['首年'], 0)) for _, group in ordered for row in group['nodes']]
    years += [int(_number(row['末年'], 0)) for _, group in ordered for row in group['nodes']]
    years = [year for year in years if year]
    if not years:
        raise BiblioChartError(t('chart.biblio_no_years'))
    max_freq = max((_number(row['频次'], 0.0) for _, group in ordered for row in group['nodes']), default=1.0) or 1.0
    scatter = []
    spans = []
    for index, (cluster, group) in enumerate(ordered):
        color = base['color'][index % len(base['color'])]
        points = []
        group_rows = sorted(group['nodes'], key=lambda item: (-_number(item['频次'], 0.0), _text(item['节点'])))
        labelled = {id(row) for row in group_rows[:3]}
        for row in sorted(group['nodes'], key=lambda item: (_number(item['首年'], 0), _text(item['节点']))):
            first = int(_number(row['首年'], 0))
            last = int(_number(row['末年'], first))
            if not first:
                continue
            freq = _number(row['频次'], 0.0)
            burst = _number(row.get('突现强度'), 0.0) if '突现强度' in df.columns else 0.0
            points.append(
                {
                    'value': [first, index, freq, _text(row['节点'])],
                    'symbolSize': round(10.0 + 24.0 * math.sqrt(max(0.0, freq) / max_freq), 2),
                    'itemStyle': {
                        'color': color,
                        'borderColor': '#e74c3c' if burst > 0 else color,
                        'borderWidth': 2 if burst > 0 else 0,
                    },
                    'label': {'show': id(row) in labelled, 'position': 'right'},
                }
            )
            spans.extend([[first, index], [max(first, last), index], None])
        scatter.append(
            {
                'type': 'scatter',
                'name': f'#{cluster} {group["label"]}',
                'data': points,
                'label': {
                    'show': True,
                    'position': 'right',
                    'color': '#222',
                    'fontSize': 9,
                    'formatter': '{@[3]}',
                    'backgroundColor': 'rgba(255,255,255,0.8)',
                    'padding': [2, 3],
                },
                'labelLayout': {'hideOverlap': False, 'moveOverlap': 'shiftY', 'draggable': True},
            }
        )
    base['grid'] = {'left': '24%', 'right': '8%', 'top': '12%', 'bottom': '14%', 'containLabel': True}
    base['xAxis'] = {
        'type': 'value',
        'name': t('chart.biblio_year'),
        'minInterval': 1,
        'min': min(years) - 1,
        'max': max(years) + 1,
    }
    base['yAxis'] = {
        'type': 'category',
        'data': categories,
        'inverse': True,
        'name': t('chart.biblio_cluster'),
        'axisLabel': {'fontSize': 9, 'width': 260, 'overflow': 'truncate', 'interval': 0},
    }
    base['series'] = scatter + [
        {
            'type': 'line',
            'name': t('chart.biblio_span'),
            'data': spans,
            'connectNulls': False,
            'showSymbol': False,
            'silent': True,
            'lineStyle': {'width': 1.2, 'opacity': 0.45},
        }
    ]
    return base


def _burst(df: pd.DataFrame, base: dict) -> dict:
    _require(df, '节点', '突现起始', '突现结束', '突现强度')
    _base_graph_series(base, base['title']['text'])
    rows = []
    for _, row in df.iterrows():
        strength = _number(row['突现强度'], 0.0)
        start = int(_number(row['突现起始'], 0))
        end = int(_number(row['突现结束'], 0))
        name = _text(row['节点'])
        if strength > 0 and start and end >= start and name:
            rows.append((name, start, end, strength))
    rows.sort(key=lambda item: (-item[3], item[0]))
    if not rows:
        raise BiblioChartError(t('chart.biblio_no_bursts'))
    first_year = min(row[1] for row in rows)
    last_year = max(row[2] for row in rows)
    names = [row[0] for row in rows]
    base['grid'] = {'left': '28%', 'right': '10%', 'top': '12%', 'bottom': '14%', 'containLabel': True}
    base['yAxis'] = {
        'type': 'category',
        'data': names,
        'inverse': True,
        'axisLabel': {'fontSize': 9, 'width': 220, 'overflow': 'truncate', 'interval': 'auto'},
    }
    base['xAxis'] = {
        'type': 'value',
        'name': t('chart.biblio_year'),
        'minInterval': 1,
        'min': first_year - 1,
        'max': last_year + 1,
    }
    series = []
    markers = []
    for index, (name, start, end, strength) in enumerate(rows):
        color = base['color'][index % len(base['color'])]
        series.append(
            {
                'type': 'line',
                'name': t('chart.biblio_duration'),
                'data': [[start, index], [end, index]],
                'showSymbol': False,
                'silent': True,
                'lineStyle': {'width': 14, 'color': color, 'opacity': 0.9, 'cap': 'round'},
                'emphasis': {'disabled': True},
            }
        )
        for year in (start, end):
            markers.append(
                {
                    'value': [year, index, name, round(strength, 3)],
                    'symbolSize': 8,
                    'itemStyle': {'color': color},
                }
            )
    series.append(
        {
            'type': 'scatter',
            'name': t('chart.biblio_burst'),
            'data': markers,
            'symbolSize': 8,
            'itemStyle': {'color': base['color'][0]},
            'label': {'show': False},
        }
    )
    base['series'] = series
    return base


def _timezone(df: pd.DataFrame, base: dict) -> dict:
    _require(df, '节点', '年份序列', '频次')
    _base_graph_series(base, base['title']['text'])
    use_clusters = '聚类' in df.columns and '聚类标签' in df.columns
    rows = []
    for _, row in df.iterrows():
        name = _text(row['节点'])
        series = _parsed(row.get('年份序列'), '年份序列')
        if not name or not isinstance(series, dict) or not series:
            continue
        rows.append((name, {int(year): int(_number(count, 0)) for year, count in series.items()}, row))
    rows.sort(key=lambda item: (-_number(item[2]['频次'], 0.0), item[0]))
    rows = rows[:20]
    if not rows:
        raise BiblioChartError(t('chart.biblio_no_years'))
    years = [year for _, series, _ in rows for year in series]
    names = [name for name, _, _ in rows]
    max_count = max((count for _, series, _ in rows for count in series.values()), default=1) or 1
    data = []
    for index, (name, series, row) in enumerate(rows):
        color = base['color'][0]
        if use_clusters:
            try:
                cluster = int(float(_text(row['聚类'])))
            except ValueError:
                cluster = 0
            color = base['color'][cluster % len(base['color'])]
        burst = _number(row.get('突现强度'), 0.0) if '突现强度' in df.columns else 0.0
        for year, count in sorted(series.items()):
            data.append(
                {
                    'value': [year, index, count, name],
                    'symbolSize': round(8.0 + 18.0 * math.sqrt(max(0, count) / max_count), 2),
                    'itemStyle': {
                        'color': color,
                        'borderColor': '#e74c3c' if burst > 0 else color,
                        'borderWidth': 2 if burst > 0 else 0,
                    },
                }
            )
    base['grid'] = {'left': '24%', 'right': '8%', 'top': '12%', 'bottom': '14%', 'containLabel': True}
    base['xAxis'] = {
        'type': 'value',
        'name': t('chart.biblio_year'),
        'minInterval': 1,
        'min': min(years) - 1,
        'max': max(years) + 1,
    }
    base['yAxis'] = {
        'type': 'category',
        'data': names,
        'inverse': True,
        'axisLabel': {'fontSize': 9, 'width': 240, 'overflow': 'truncate', 'interval': 0},
    }
    base['series'] = [{'type': 'scatter', 'name': t('chart.biblio_activity'), 'data': data}]
    return base


def _landscape(df: pd.DataFrame, base: dict) -> dict:
    _require(df, '节点', '聚类', '聚类标签', '频次')
    _base_graph_series(base, base['title']['text'])
    clusters: dict[str, dict] = {}
    for _, row in df.iterrows():
        name = _text(row['节点'])
        cluster = _text(row['聚类'])
        if not cluster:
            continue
        group = clusters.setdefault(
            cluster,
            {
                'label': _text(row['聚类标签']) or f'#{cluster}',
                'nodes': [],
                'frequency': 0.0,
                'x': [],
                'y': [],
            },
        )
        group['nodes'].append(name)
        group['frequency'] += _number(row['频次'], 0.0)
        if 'x' in row and 'y' in row:
            group['x'].append(_number(row['x'], 0.0))
            group['y'].append(_number(row['y'], 0.0))
    if not clusters:
        raise BiblioChartError(t('chart.biblio_no_clusters'))
    ordered = sorted(clusters.items(), key=lambda item: (-item[1]['frequency'], item[0]))[:30]
    max_frequency = max((group['frequency'] for _, group in ordered), default=1.0) or 1.0
    data = []
    for index, (cluster, group) in enumerate(ordered):
        count = len(group['nodes'])
        x = sum(group['x']) / len(group['x']) if group['x'] else index * 18.0
        y = sum(group['y']) / len(group['y']) if group['y'] else index * 7.0
        size = round(
            24.0 + 42.0 * math.sqrt(max(0.0, group['frequency'] / max_frequency)) + min(18.0, 2.0 * math.sqrt(count)),
            2,
        )
        data.append(
            {
                'name': f'#{cluster} {group["label"]}',
                'value': round(group['frequency'], 4),
                'x': round(x, 3),
                'y': round(y, 3),
                'symbolSize': size,
                'itemStyle': {
                    'color': base['color'][index % len(base['color'])],
                    'opacity': 0.72,
                    'borderColor': '#fff',
                    'borderWidth': 2,
                },
                'label': {'show': True, 'fontSize': 11},
            }
        )
    base['tooltip']['formatter'] = None
    base['series'] = [
        {
            'type': 'graph',
            'layout': 'none',
            'roam': True,
            'draggable': True,
            'data': data,
            'links': [],
            'label': {
                'position': 'right',
                'color': '#222',
                'backgroundColor': 'rgba(255,255,255,0.84)',
                'padding': [3, 5],
                'borderRadius': 4,
            },
            'labelLayout': {'hideOverlap': False, 'moveOverlap': 'shiftY', 'draggable': True},
        }
    ]
    return base


def _biblio_heatmap(df: pd.DataFrame, base: dict) -> dict:
    _require(df, '节点', '聚类', '聚类标签', '年份序列', '频次')
    base['tooltip']['trigger'] = 'item'
    base['tooltip']['formatter'] = None
    clusters: dict[str, dict] = {}
    years: set[int] = set()
    for _, row in df.iterrows():
        cluster = _text(row['聚类'])
        label = _text(row['聚类标签']) or f'#{cluster}'
        name = f'#{cluster} {label}'
        counts = _parsed(row.get('年份序列'), '年份序列')
        if not cluster or not isinstance(counts, dict) or not counts:
            continue
        group = clusters.setdefault(name, {})
        for year, count in counts.items():
            try:
                year_int = int(float(year))
            except (TypeError, ValueError):
                continue
            group[year_int] = group.get(year_int, 0) + int(_number(count, 0))
            years.add(year_int)
    if not clusters or not years:
        raise BiblioChartError(t('chart.biblio_no_years'))
    ordered = sorted(clusters, key=lambda label: (-sum(clusters[label].values()), label))[:30]
    year_list = sorted(years)
    max_count = max((count for cluster in ordered for count in clusters[cluster].values()), default=1) or 1
    data = []
    for y, cluster in enumerate(ordered):
        for x, year in enumerate(year_list):
            count = clusters[cluster].get(year, 0)
            data.append([x, y, count])
    base['xAxis'] = {'type': 'category', 'data': [str(year) for year in year_list], 'name': t('chart.biblio_year')}
    base['yAxis'] = {'type': 'category', 'data': ordered, 'inverse': True}
    base['grid'] = {'left': '26%', 'right': '18%', 'top': '12%', 'bottom': '18%', 'containLabel': True}
    base['visualMap'] = {
        'min': 0,
        'max': max_count,
        'calculable': True,
        'orient': 'vertical',
        'right': 8,
        'top': 'middle',
        'text': [str(max_count), '0'],
        'textStyle': {'fontSize': 9},
    }
    base['series'] = [
        {
            'type': 'heatmap',
            'name': t('chart.biblio_activity'),
            'data': data,
            'label': {'show': max_count <= 60, 'fontSize': 8},
            'emphasis': {'itemStyle': {'shadowBlur': 8, 'shadowColor': 'rgba(0,0,0,0.3)'}},
        }
    ]
    return base


def _graph3d(df: pd.DataFrame, base: dict) -> dict:
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


def _side_slot(index: int, size: int) -> float:
    """One node's vertical slot in a dual-map column, centred when the column has one node."""
    return 500.0 if size < 2 else round(50 + index * (900 / (size - 1)), 2)


def _dual_map(df: pd.DataFrame, base: dict) -> dict:
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


def _variation(df: pd.DataFrame, base: dict) -> dict:
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


def _geo_map(df: pd.DataFrame, base: dict) -> dict:
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


# ─── sentiment / topic overlays ──────────────────────────────────


def _overlay_word(label: str) -> str:
    """A stored label as the word this run's language shows (正面 / Positive / 主题-1 …).

    The catalogue lives in ``visualizer`` beside every other chart-localisation token. The import
    is local because ``visualizer`` imports this module when it builds a bibliometric option —
    a module-level back-import would be a cycle in the direction the layering already avoids.
    """
    from services.visualizer import _localize_label

    return _localize_label(label)


def _overlay_counts(row, column: str) -> dict[str, int]:
    parsed = _parsed(row.get(column), column)
    if not isinstance(parsed, dict):
        return {}
    counts: dict[str, int] = {}
    for label, value in parsed.items():
        text = str(label).strip()
        number = int(_number(value, 0.0))
        if text and number > 0:
            counts[text] = number
    return counts


def _overlay_rows(df: pd.DataFrame, column: str, refusal: str):
    """Every node carrying a distribution, plus how many nodes carry none.

    A node with an empty distribution has no labelled document at all; drawing it as a row of
    zeros would read as "measured, and zero", so it is left off the figure and COUNTED in the
    note both overlay views print."""
    _require(df, '节点', column)
    rows: list[tuple[str, dict[str, int]]] = []
    unlabelled = 0
    for _, row in df.iterrows():
        name = _text(row['节点'])
        if not name:
            continue
        counts = _overlay_counts(row, column)
        if not counts:
            unlabelled += 1
            continue
        rows.append((name, counts))
    if not rows:
        raise BiblioChartError(t(refusal))
    return rows, unlabelled


def _overlay_subtext(base: dict, notes: list[str]) -> None:
    if not notes:
        return
    # Wrapped and inset like the choropleth's note: at the preview panel's 400 px a one-line
    # note runs past the canvas, which is the figure-wider-than-the-page defect again.
    base['title']['subtext'] = ' · '.join(notes)
    base['title']['subtextStyle'] = {'fontSize': 9, 'color': '#888', 'width': 330, 'overflow': 'break'}
    base['title']['left'] = 12
    base['title']['right'] = 12


def _sentiment_overlay(df: pd.DataFrame, base: dict) -> dict:
    """One 100 % stacked bar per node: how its mentioning documents split across the labels.

    The share is computed over DOCUMENTS carrying a label, so a node mentioned by five positive
    and five negative papers is 50 / 50 whatever the mention counts are. A polarity column
    (``POLARITY_LABELS``) is ordered negative → neutral → positive and coloured by meaning, the
    way a Likert figure reads; any other label set (emotion, tendency, a user's own names) keeps
    descending frequency order and the categorical palette, because those labels have no
    left-to-right polarity to impose.
    """
    rows, unlabelled = _overlay_rows(df, '情感分布', 'chart.biblio_no_sentiment')
    totals: dict[str, int] = {}
    for _name, counts in rows:
        for label, count in counts.items():
            totals[label] = totals.get(label, 0) + count
    labels = sorted(totals, key=lambda label: (-totals[label], label))
    polarity = set(labels) == set(POLARITY_LABELS)
    if polarity:
        labels = list(POLARITY_LABELS)
        # Positive first tells the reader at a glance which side of the figure leans that way.
        rows.sort(key=lambda item: (-item[1].get('positive', 0) / max(1, sum(item[1].values())), item[0]))
    else:
        rows.sort(key=lambda item: (-sum(item[1].values()), item[0]))
    shown = rows[:OVERLAY_ROW_LIMIT]
    names = [name for name, _counts in shown]
    colors = [
        POLARITY_COLORS.get(label) or base['color'][index % len(base['color'])] for index, label in enumerate(labels)
    ]
    series = []
    for label, color in zip(labels, colors, strict=True):
        data = []
        for _name, counts in shown:
            total = sum(counts.values())
            share = round(100.0 * counts.get(label, 0) / total, 2) if total else 0.0
            # The colour is stated per item: the theme patcher rewrites the SERIES label colour
            # for its own background, which would put dark text on a dark segment.
            data.append({'value': share, 'label': {'show': share >= 8, 'color': '#fff'}})
        series.append(
            {
                'name': _overlay_word(label),
                'type': 'bar',
                'stack': 'overlay',
                'barWidth': '62%',
                'data': data,
                'itemStyle': {'color': color, 'borderColor': '#fff', 'borderWidth': 0.5},
                'label': {'position': 'inside', 'fontSize': 9, 'color': '#fff', 'formatter': '{c}%'},
            }
        )
    # The title (6..26 px), the wrapped figure note (~2 lines) and the legend share the top band.
    # A percentage top would shrink that band on tall canvases and swallow it on short ones; 112 px
    # is the measured height of the three, and the legend at 44 sits below the note, not on it.
    base['grid'] = {'left': '26%', 'right': '6%', 'top': 112, 'bottom': '11%', 'containLabel': True}
    base['xAxis'] = {
        'type': 'value',
        'min': 0,
        'max': 100,
        'name': t('chart.biblio_share'),
        'axisLabel': {'formatter': '{value}%', 'fontSize': 9},
    }
    base['yAxis'] = {
        'type': 'category',
        'data': names,
        'inverse': True,
        # Horizontal, never auto-rotated: a CJK name turned vertical is as tall as it is long
        # (the lesson the variation view paid for in Chrome).
        'axisLabel': {
            'fontSize': 9,
            'rotate': 0,
            # 96 px, not the 200 the older views reserve: at the preview panel's 400 px a 200 px
            # label box started 46 px LEFT of the canvas and was cut away entirely (measured in
            # Chrome). 96 px holds ~10 CJK characters; the full name is in the tooltip and table.
            'width': 96,
            'overflow': 'truncate',
            'interval': 0,
            'hideOverlap': True,
        },
    }
    base['legend'] = {
        # A plain legend has no page marker: the ``1/1`` a scroll legend adds used to sit on top
        # of the first row's text (measured in Chrome on this very view).
        'type': 'plain',
        'top': 44,
        'left': 'center',
        'itemWidth': 12,
        'itemHeight': 8,
        'textStyle': {'fontSize': 10},
    }
    base['tooltip']['trigger'] = 'axis'
    base['tooltip']['axisPointer'] = {'type': 'shadow'}
    base['tooltip']['formatter'] = None
    base['series'] = series
    notes = []
    if unlabelled:
        notes.append(t('chart.biblio_overlay_unlabelled', n=unlabelled))
    if len(rows) > len(shown):
        notes.append(t('chart.biblio_overlay_truncated', shown=len(shown), total=len(rows)))
    _overlay_subtext(base, notes)
    return base


def _topic_overlay(df: pd.DataFrame, base: dict) -> dict:
    """Node × topic heatmap of each node's share of labelled documents per topic.

    The cell says share, not raw count, so a heavily mentioned node does not make every other
    row look empty. Both axes are capped (``OVERLAY_TOPIC_LIMIT`` / ``OVERLAY_ROW_LIMIT``) and the
    figure prints what it left out; the node table's distribution column keeps every label.
    """
    rows, unlabelled = _overlay_rows(df, '话题分布', 'chart.biblio_no_topics')
    topic_totals: dict[str, int] = {}
    for _name, counts in rows:
        for topic, count in counts.items():
            topic_totals[topic] = topic_totals.get(topic, 0) + count
    topics = sorted(topic_totals, key=lambda topic: (-topic_totals[topic], topic))
    shown_topics = topics[:OVERLAY_TOPIC_LIMIT]
    rows.sort(key=lambda item: (-sum(item[1].values()), item[0]))
    shown = rows[:OVERLAY_ROW_LIMIT]
    names = [name for name, _counts in shown]
    data = []
    for y, (_name, counts) in enumerate(shown):
        total = sum(counts.values())
        for x, topic in enumerate(shown_topics):
            share = round(100.0 * counts.get(topic, 0) / total, 2) if total else 0.0
            # Per-item colour, as in the sentiment view: the theme patcher rewrites the series
            # label colour, and a dark cell needs a white number whichever theme is active.
            data.append(
                {
                    'value': [x, y, share],
                    'label': {'show': share >= 4, 'color': '#fff' if share > 55 else '#222'},
                }
            )
    base['tooltip']['trigger'] = 'item'
    base['tooltip']['formatter'] = None
    base['xAxis'] = {
        'type': 'category',
        'data': [_overlay_word(topic) for topic in shown_topics],
        'name': t('chart.col.topic'),
        'axisLabel': {'fontSize': 9, 'interval': 0, 'rotate': 30 if len(shown_topics) > 6 else 0},
    }
    base['yAxis'] = {
        'type': 'category',
        'data': names,
        'inverse': True,
        'axisLabel': {
            'fontSize': 9,
            'rotate': 0,
            # Same 96 px as the sentiment view, for the same measured reason: a 200 px box hangs
            # off the left edge of the 400 px preview panel.
            'width': 96,
            'overflow': 'truncate',
            'interval': 0,
            'hideOverlap': True,
        },
    }
    base['grid'] = {'left': '26%', 'right': '12%', 'top': 84, 'bottom': '18%', 'containLabel': True}
    base['visualMap'] = {
        'min': 0,
        'max': 100,
        'dimension': 2,
        'calculable': True,
        'orient': 'vertical',
        'right': 8,
        'top': 'middle',
        'itemWidth': 12,
        'itemHeight': 100,
        'text': ['100%', '0'],
        'textStyle': {'fontSize': 9},
    }
    base['series'] = [
        {
            'type': 'heatmap',
            'name': t('chart.biblio_topic_share'),
            'data': data,
            'label': {'show': True, 'fontSize': 8},
            'emphasis': {'itemStyle': {'shadowBlur': 8, 'shadowColor': 'rgba(0,0,0,0.3)'}},
        }
    ]
    notes = []
    if unlabelled:
        notes.append(t('chart.biblio_overlay_unlabelled', n=unlabelled))
    if len(topics) > len(shown_topics):
        notes.append(t('chart.biblio_topics_truncated', shown=len(shown_topics), total=len(topics)))
    if len(rows) > len(shown):
        notes.append(t('chart.biblio_overlay_truncated', shown=len(shown), total=len(rows)))
    _overlay_subtext(base, notes)
    return base


BUILDERS = {
    'knowledge_graph': _knowledge_graph,
    'cluster_timeline': _cluster_timeline,
    'burst': _burst,
    'timezone': _timezone,
    'circular': _circular,
    'landscape': _landscape,
    'biblio_heatmap': _biblio_heatmap,
    'graph3d': _graph3d,
    'variation': _variation,
    'dual_map': _dual_map,
    'geo_map': _geo_map,
    'sentiment_overlay': _sentiment_overlay,
    'topic_overlay': _topic_overlay,
    'concentric': _concentric,
}


def build(df: pd.DataFrame, chart_type: str, base: dict) -> dict:
    builder = BUILDERS.get(chart_type)
    if builder is None:
        raise BiblioChartError(t('chart.biblio_unknown', type=chart_type))
    return builder(df, base)
