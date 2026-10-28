"""Time-shaped bibliometric views: cluster timeline, burst, timezone, landscape.

Each view draws a quantity over a year axis; the shared reading is in
``services.biblio.charts.base``.
"""

import math

import pandas as pd

from i18n import t

from .base import (
    BiblioChartError,
    _base_graph_series,
    _number,
    _parsed,
    _require,
    _text,
)


def cluster_timeline(df: pd.DataFrame, base: dict) -> dict:
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
            burst_strength = _number(row.get('突现强度'), 0.0) if '突现强度' in df.columns else 0.0
            points.append(
                {
                    'value': [first, index, freq, _text(row['节点'])],
                    'symbolSize': round(10.0 + 24.0 * math.sqrt(max(0.0, freq) / max_freq), 2),
                    'itemStyle': {
                        'color': color,
                        'borderColor': '#e74c3c' if burst_strength > 0 else color,
                        'borderWidth': 2 if burst_strength > 0 else 0,
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


def burst(df: pd.DataFrame, base: dict) -> dict:
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


def timezone(df: pd.DataFrame, base: dict) -> dict:
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
        burst_strength = _number(row.get('突现强度'), 0.0) if '突现强度' in df.columns else 0.0
        for year, count in sorted(series.items()):
            data.append(
                {
                    'value': [year, index, count, name],
                    'symbolSize': round(8.0 + 18.0 * math.sqrt(max(0, count) / max_count), 2),
                    'itemStyle': {
                        'color': color,
                        'borderColor': '#e74c3c' if burst_strength > 0 else color,
                        'borderWidth': 2 if burst_strength > 0 else 0,
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


def landscape(df: pd.DataFrame, base: dict) -> dict:
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


def biblio_heatmap(df: pd.DataFrame, base: dict) -> dict:
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
