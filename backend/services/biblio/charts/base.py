"""Shared constants and readers for the bibliometric chart builders.

Every builder here reads the fixed columns ``services.biblio.metrics`` emits, and a
missing column is a named refusal rather than an empty frame. The helpers that more
than one view family needs live here so a figure cannot disagree with its neighbour
about what a row means.
"""

import json
import math

import pandas as pd

from i18n import t

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


def bbox_anchors() -> list[dict]:
    """Two invisible corner nodes that pin a free-layout graph's box to 50..950.

    ECharts fits a ``layout:'none'`` graph's data bounding box into the series rect with a
    separate scale per axis. A spring layout is isotropic, so a box that is wider than it is
    tall would be stretched horizontally on screen; these anchors make the box square (the
    browser keeps the rect square too), so one scale serves both axes. They draw nothing,
    answer no pointer and own no label.
    """
    return [
        {
            'name': name,
            'x': x,
            'y': y,
            'symbolSize': 0,
            'value': 0,
            'category': 0,
            'itemStyle': {'opacity': 0},
            'label': {'show': False},
            'emphasis': {'disabled': True},
            'silent': True,
        }
        for name, (x, y) in (('_bbox_min_', (50.0, 50.0)), ('_bbox_max_', (950.0, 950.0)))
    ]


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
