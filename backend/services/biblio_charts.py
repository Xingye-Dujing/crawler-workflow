"""ECharts options for the four bibliometric views.

These builders read the fixed columns emitted by ``services.bibliometrics``.
A missing required column is a named refusal, never an empty frame. Options
are plain JSON: no ``renderItem`` callbacks, so a preview, a saved chart and a
fullscreen render all draw the same figure.
"""

import json
import math

import pandas as pd

from i18n import t


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
    base['tooltip']['formatter'] = None
    base['title']['text'] = title or base['title']['text']


def _knowledge_graph(df: pd.DataFrame, base: dict) -> dict:
    _require(df, '节点', 'x', 'y', '连接', '频次')
    _base_graph_series(base, base['title']['text'])
    names: list[str] = []
    rows: dict[str, dict] = {}
    for _, row in df.iterrows():
        name = _text(row['节点'])
        if not name or name in rows:
            continue
        names.append(name)
        rows[name] = row
    if not names:
        raise BiblioChartError(t('chart.biblio_no_nodes'))

    use_clusters = '聚类' in df.columns and '聚类标签' in df.columns
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

    max_freq = max((_number(rows[name]['频次'], 0.0) for name in names), default=1.0) or 1.0
    data = []
    for name in names:
        row = rows[name]
        burst = _number(row.get('突现强度'), 0.0) if '突现强度' in df.columns else 0.0
        item_style = {'color': base['color'][0]}
        if use_clusters:
            cluster = _text(row['聚类'])
            label = _text(row['聚类标签']) or f'#{cluster}'
            item_style['color'] = base['color'][category_index[f'#{cluster} {label}'] % len(base['color'])]
        if burst > 0:
            item_style['borderColor'] = '#e74c3c'
            item_style['borderWidth'] = 2
        data.append(
            {
                'name': name,
                'x': _number(row['x'], 0.0),
                'y': _number(row['y'], 0.0),
                'value': round(_number(row['频次'], 0.0), 4),
                'symbolSize': round(10.0 + 34.0 * math.sqrt(max(0.0, _number(row['频次'], 0.0)) / max_freq), 2),
                'category': category_index[
                    (
                        f'#{_text(row["聚类"])} {_text(row["聚类标签"]) or "#" + _text(row["聚类"])}'
                        if use_clusters
                        else category_names[0]
                    )
                ],
                'itemStyle': item_style,
            }
        )

    links: dict[tuple[str, str], dict] = {}
    for name in names:
        row = rows[name]
        for item in _parsed(row.get('连接'), '连接'):
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
    link_data = [
        {
            **link,
            'lineStyle': {'width': round(1.0 + 4.0 * math.sqrt(max(0.0, link['value']) / biggest), 2)},
        }
        for link in sorted(links.values(), key=lambda item: (-item['value'], item['source'], item['target']))
    ]

    base['legend'] = {
        'data': category_names,
        'type': 'scroll',
        'orient': 'vertical',
        'right': 8,
        'top': 40,
        'textStyle': {'color': '#444', 'fontSize': 10, 'fontFamily': 'sans-serif'},
        'itemWidth': 10,
        'itemHeight': 10,
    }
    base['series'] = [
        {
            'type': 'graph',
            'layout': 'none',
            'roam': True,
            'draggable': True,
            'categories': [{'name': name} for name in category_names],
            'data': data,
            'links': link_data,
            'label': {
                'show': True,
                'position': 'right',
                'color': '#333',
                'fontSize': 9,
                'fontFamily': 'sans-serif',
                'formatter': '{b}',
            },
            'labelLayout': {'hideOverlap': True},
            'lineStyle': {'color': 'source', 'curveness': 0.12, 'opacity': 0.4},
            'emphasis': {'focus': 'adjacency', 'lineStyle': {'width': 4}},
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
                }
            )
            spans.extend([[first, index], [max(first, last), index], None])
        scatter.append(
            {
                'type': 'scatter',
                'name': f'#{cluster} {group["label"]}',
                'data': points,
                'label': {'show': len(points) <= 12, 'position': 'right', 'fontSize': 9, 'formatter': '{b}'},
                'labelLayout': {'hideOverlap': True},
            }
        )
    base['xAxis'] = {
        'type': 'value',
        'name': t('chart.biblio_year'),
        'minInterval': 1,
        'min': min(years) - 1,
        'max': max(years) + 1,
    }
    base['yAxis'] = {'type': 'category', 'data': categories, 'inverse': True, 'name': t('chart.biblio_cluster')}
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
    base['tooltip']['trigger'] = 'item'
    base['tooltip']['formatter'] = None
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
    base['xAxis'] = {
        'type': 'value',
        'name': t('chart.biblio_year'),
        'minInterval': 1,
        'min': first_year - 1,
        'max': last_year + 1,
    }
    base['yAxis'] = {'type': 'category', 'data': names, 'inverse': True}
    # A bar series with a value x axis did not paint (measured in Chrome); a
    # thick line segment from start to end is the same interval, is plain JSON,
    # and reads as a burst bar. The markers keep a one-year burst visible.
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
    base['tooltip']['trigger'] = 'item'
    base['tooltip']['formatter'] = None
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
    base['xAxis'] = {
        'type': 'value',
        'name': t('chart.biblio_year'),
        'minInterval': 1,
        'min': min(years) - 1,
        'max': max(years) + 1,
    }
    base['yAxis'] = {'type': 'category', 'data': names, 'inverse': True}
    base['series'] = [{'type': 'scatter', 'name': t('chart.biblio_activity'), 'data': data}]
    base['tooltip']['trigger'] = 'item'
    base['tooltip']['formatter'] = None
    return base


BUILDERS = {
    'knowledge_graph': _knowledge_graph,
    'cluster_timeline': _cluster_timeline,
    'burst': _burst,
    'timezone': _timezone,
}


def build(df: pd.DataFrame, chart_type: str, base: dict) -> dict:
    builder = BUILDERS.get(chart_type)
    if builder is None:
        raise BiblioChartError(t('chart.biblio_unknown', type=chart_type))
    return builder(df, base)
