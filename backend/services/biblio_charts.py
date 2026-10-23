"""ECharts options for the bibliometric views.

These builders read the fixed columns emitted by ``services.bibliometrics``.
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

from i18n import t

#: Node labels beyond this are hover-only. A 500-node knowledge graph with every
#: label painted is not a figure; it is a smudge. The bubbles stay drawn.
LABEL_LIMIT = 70
#: Approximate pixels represented by one graph coordinate unit. The collision
#: resolver places labels in coordinate space and hands ECharts a pixel offset.
GRAPH_SCALE = 1.5


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


def _categories(rows: dict[str, dict], names: list[str], base: dict, frame: pd.DataFrame):
    use_clusters = '聚类' in frame.columns and '聚类标签' in frame.columns
    category_names: list[str] = []
    category_index: dict[str, int] = {}
    if use_clusters:
        for name in names:
            cluster = _text(rows[name]['聚类'])
            label = _text(rows[name]['聚类标签']) or f'#{cluster}'
            key = f'#{cluster} {label}'
            if key not in category_index:
                category_index[key] = len(category_names)
                category_names.append(key)
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


def _legend(category_names: list[str]) -> dict:
    return {
        'data': category_names,
        'type': 'scroll',
        'orient': 'vertical',
        'right': 8,
        'top': 40,
        'textStyle': {'color': '#444', 'fontSize': 10, 'fontFamily': 'sans-serif'},
        'itemWidth': 10,
        'itemHeight': 10,
    }


def _graph_option(df: pd.DataFrame, base: dict, *, layout: str, require_coordinates: bool) -> dict:
    rows, names = _node_rows(df, require_coordinates=require_coordinates)
    categories = _categories(rows, names, base, df)
    data = _node_data(rows, names, base, layout=layout, categories=categories)
    links = _graph_links(rows, names)
    base['legend'] = _legend(categories[1])
    series = {
        'type': 'graph',
        'layout': layout,
        'roam': True,
        'draggable': True,
        'circular': {'rotateLabel': True} if layout == 'circular' else {},
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
        'axisLabel': {'fontSize': 9, 'width': 220, 'overflow': 'break', 'interval': 0},
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


BUILDERS = {
    'knowledge_graph': _knowledge_graph,
    'cluster_timeline': _cluster_timeline,
    'burst': _burst,
    'timezone': _timezone,
    'circular': _circular,
    'landscape': _landscape,
    'biblio_heatmap': _biblio_heatmap,
    'graph3d': _graph3d,
}


def build(df: pd.DataFrame, chart_type: str, base: dict) -> dict:
    builder = BUILDERS.get(chart_type)
    if builder is None:
        raise BiblioChartError(t('chart.biblio_unknown', type=chart_type))
    return builder(df, base)
