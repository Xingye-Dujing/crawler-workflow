"""General-purpose visualization service.

Two rendering back-ends are supported so the "Visualize" node (and any
standalone caller) can pick whichever fits:

* ``engine="echarts"`` -> returns a JSON-serializable ECharts ``option``
  dict. Cheap, renders client-side, reuses the ECharts script already
  loaded by the frontend (see stats.js for the existing pie-chart usage
  this mirrors).
* ``engine="matplotlib"`` -> renders server-side with matplotlib and
  returns a base64 PNG data URI. Useful for chart types or styling that
  are easier to express in Python, or for headless/report generation.

This service is data-source agnostic: it only cares about a DataFrame and
a chart spec, so it works identically whether the data came from a
workflow's upstream node, an uploaded CSV/JSON file, or hand-typed JSON
pasted into the UI.
"""

import base64
import io
import logging
import math
import re
from collections import Counter

import jieba
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from i18n import t

matplotlib.use('Agg')  # headless backend, safe for a web server
plt.rcParams['font.sans-serif'] = [
    'SimHei',
    'Microsoft YaHei',
    'WenQuanYi Micro Hei',
    'DejaVu Sans',
    'Arial Unicode MS',
    'sans-serif',
]
plt.rcParams['axes.unicode_minus'] = False

logger = logging.getLogger(__name__)

CHART_TYPES = (
    'bar',
    'line',
    'dual_line',
    'stack_pct',
    'topic_map',
    'topic_terms',
    'pie',
    'scatter',
    'histogram',
    'box',
    'heatmap',
    'model_agreement',
    'sankey',
    'network',
    'wordcloud',
    'map',
)


def _json_safe(value):
    """Recursively make a chart spec JSON-safe.

    A mean over a group whose values are all missing is NaN, and JSON has no
    NaN: ``jsonify`` would emit a bare ``NaN`` token and the browser's
    ``JSON.parse`` would reject the *whole* response. numpy scalars are
    converted too — Flask cannot serialise them either.
    """
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _finite(values) -> list:
    """Only usable numbers, for min/max/visual-map bounds and link weights."""
    out = []
    for v in values:
        if isinstance(v, (np.floating, np.integer, np.bool_)):
            v = v.item()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out.append(float(v))
    return out


def _parse_annotations(text) -> list:
    """Event markers written as ``date=label`` pairs, into ``[(axis label, caption)]``.

    The whole reading of the study's curve hangs on dated events — 4 月 23 日的遗体打捞,
    5 月 19 日的通报 — and a curve without them is a shape nobody can interpret. ECharts draws
    one as a vertical ``markLine`` at a CATEGORY, which means the text has to match an axis
    label exactly; a date formatted differently (``4-23`` against ``04-23``) would therefore
    silently draw nothing, so an unknown label is refused here with the real ones listed.

    Events are separated by ``;`` (or a newline, which a pasted list gives). A chunk with no
    separator is a typo, and guessing which half is the date would put an invented line on
    someone's figure.
    """
    markers = []
    for chunk in re.split(r'[;；\n]+', str(text if text is not None else '')):
        item = chunk.strip()
        if not item:
            continue
        for separator in ('=', '：', ':'):
            if separator in item:
                when, _, caption = item.partition(separator)
                break
        else:
            raise ChartConfigError(
                f'annotation "{item}" is not a "date=label" pair: separate the event name from '
                'the axis label with = (events themselves are separated by ;)'
            )
        when = when.strip()
        if not when:
            raise ChartConfigError(f'annotation "{item}" has no axis label before the =')
        markers.append((when, caption.strip() or when))
    return markers


def _annotation_lines(markers, labels, field) -> dict:
    """One ECharts ``markLine`` for the markers, or a refusal naming what is not on the axis.

    ``labels`` is the axis' already-localised tick list; ``markers`` come from the user's raw
    ``annotations`` string. Localise each ``when`` before comparing and again in the emitted
    ``xAxis`` value, or an English token the run renders as Chinese would match nothing and the
    vertical line would refuse on an axis that in fact has that category.
    """
    available = [str(value) for value in labels]
    located = [(_localize_label(when), caption) for when, caption in markers]
    missing = [when for when, _ in located if when not in available]
    if missing:
        preview = '、'.join(available[:8]) + (' …' if len(available) > 8 else '')
        raise ChartConfigError(
            f'annotation {("、".join(missing))} is not a value of the x axis "{field}"; '
            f'this axis can mark only: {preview}'
        )
    return {
        'symbol': ['none', 'none'],
        # Silent, or a hovered point would fight the event line for the tooltip.
        'silent': True,
        'lineStyle': {'color': '#F59E0B', 'type': 'dashed', 'width': 1.5},
        'label': {'show': True, 'position': 'insideEndTop', 'color': '#F59E0B', 'fontSize': 10},
        'data': [{'xAxis': when, 'label': {'formatter': caption}} for when, caption in located],
    }


# ── Professional colour palette (Nature/Science journal inspired) ──
CATEGORY_COLORS = [
    '#3B82F9',
    '#EF4444',
    '#10B981',
    '#F59E0B',
    '#8B5CF6',
    '#EC4899',
    '#06B6D4',
    '#F97316',
    '#6366F1',
    '#14B8A6',
    '#E11D48',
    '#0EA5E9',
    '#84CC16',
    '#D946EF',
    '#0284C7',
]
# A figure in a humanities paper is read in print, often in grayscale, and cited for its numbers —
# so the palette is restrained and separated by lightness as much as by hue. The previous set was a
# UI accent palette (neon blue first, gradient area fills), which is why every chart looked like a
# dashboard rather than a 图.
CATEGORY_COLORS = [
    '#2C4E6B',
    '#A85442',
    '#4F7355',
    '#8A7132',
    '#5C5470',
    '#3E6B73',
    '#8B5E3C',
    '#6B7F5C',
    '#7A4A55',
    '#4A5A73',
]
DIVERGING_CMAP = ['#0571B0', '#92C5DE', '#F7F7F7', '#F4A582', '#CA0020']
SEQUENTIAL_CMAP = ['#F7FCF0', '#E0F3DB', '#CCEBC5', '#A8DDB5', '#7BCCC4', '#4EB3D3', '#2B8CBE', '#0868AC', '#084081']

#: A paper figure is set in a serif face (and 宋体 for Chinese labels), not in the UI's sans.
PRINT_FONT = "'Times New Roman', 'SimSun', 'Songti SC', serif"
_TEXT_STYLE = {'color': '#222', 'fontSize': 11, 'fontFamily': PRINT_FONT}
_AXIS_STYLE = {
    'axisLine': {'lineStyle': {'color': '#666'}},
    'axisTick': {'lineStyle': {'color': '#666'}},
    'axisLabel': {'color': '#333', 'fontSize': 10, 'fontFamily': PRINT_FONT},
    'splitLine': {'lineStyle': {'color': '#d9d9d9', 'type': 'dashed'}},
}
# The room is generous on purpose and `containLabel` adds the tick text on top of it: every figure
# whose x axis carried ISO dates had its labels cut in half at the panel edge, and a figure that
# hides its own scale is not readable in a paper.
_GRID = {'left': 72, 'right': 72, 'top': 56, 'bottom': 96, 'containLabel': True}

# ── Chart display localisation ──────────────────────────────────
# Stored column names and analyzer label VALUES stay English in the data and the run ledger;
# only the rendered text is translated, so a Chinese run shows 发帖量 / 正面 while an English run
# shows Total / Positive (t() reads the run's thread-local language). Unknown values pass through
# unchanged — a number, a date, an already-Chinese phase, or the user's own column name must not
# be touched, and category values are unbounded, so a miss is a no-op, never a refusal.
_CHART_COL_TOKENS = {
    'total': 'chart.col.total',
    'sentiment_index': 'chart.col.sentiment_index',
    'sentiment': 'chart.col.sentiment',
    'positive_pct': 'chart.col.positive_pct',
    'neutral_pct': 'chart.col.neutral_pct',
    'negative_pct': 'chart.col.negative_pct',
    'emotion': 'chart.col.emotion',
    'tendency': 'chart.col.tendency',
    'confidence': 'chart.col.confidence',
    'tendency_confidence': 'chart.col.tendency_confidence',
    'aggression_score': 'chart.col.aggression_score',
    'prevalence_pct': 'chart.col.prevalence_pct',
    'doc_n': 'chart.col.doc_n',
    'feature_words': 'chart.col.feature_words',
    'topic': 'chart.col.topic',
    'score': 'chart.col.score',
    'weights': 'chart.col.weights',
    'period': 'chart.col.period',
    'intensity': 'chart.col.intensity',
    'term': 'chart.col.term',
    'overall_freq': 'chart.col.overall_freq',
    'within_freq': 'chart.col.within_freq',
    'sample_texts': 'chart.col.sample_texts',
}
_CHART_VALUE_TOKENS = {
    'positive': 'chart.value.positive',
    'negative': 'chart.value.negative',
    'neutral': 'chart.value.neutral',
    # The emotion node's six SMP2020-EWECT classes (stored as these exact strings).
    'Anger': 'chart.value.anger',
    'Fear': 'chart.value.fear',
    'Joy': 'chart.value.joy',
    'Sadness': 'chart.value.sadness',
    'Surprise': 'chart.value.surprise',
    'Neutral': 'chart.value.neutral',
    # The tendency node's six stance classes (stored as these exact strings).
    'Objective Statement': 'chart.value.tendency_objective',
    'Praise/Affirmation': 'chart.value.tendency_praise',
    'Criticism/Questioning': 'chart.value.tendency_criticism',
    'Controversy/Reflection': 'chart.value.tendency_controversy',
    'Advocacy/Call-to-action': 'chart.value.tendency_advocacy',
    'Satire/Mockery': 'chart.value.tendency_satire',
}


def _localize_label(value) -> str:
    """Translate a chart *display* string — a column-name-as-label or a category value.

    Only controlled tokens change; a number, a date, an already-Chinese phase or a 主题概括 is
    returned as its own string. A ``Topic…`` label (the model's numbering) keeps its suffix but
    swaps the English word, so ``Topic-1`` / ``TopicⅠ-1`` read 主题-1 / 主题Ⅰ-1.
    """
    text = str(value)
    key = _CHART_COL_TOKENS.get(text) or _CHART_VALUE_TOKENS.get(text)
    if key:
        return t(key)
    if text.startswith('Topic'):
        return t('chart.col.topic') + text[len('Topic') :]
    return text


# ── Word cloud style presets ──
# Each preset defines textStyle options for the echarts-wordcloud extension.
# The 'color' field accepts a single string or an array (extension picks randomly).
WORDCLOUD_STYLES = {
    'vibrant': {
        'labelKey': 'wordcloudStyle.vibrant',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': [
                '#3B82F9',
                '#EF4444',
                '#10B981',
                '#F59E0B',
                '#8B5CF6',
                '#EC4899',
                '#06B6D4',
                '#F97316',
                '#6366F1',
                '#14B8A6',
                '#E11D48',
                '#0EA5E9',
                '#84CC16',
                '#D946EF',
                '#0284C7',
            ],
        },
    },
    'monoBlue': {
        'labelKey': 'wordcloudStyle.monoBlue',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': [
                '#03045E',
                '#023E8A',
                '#0077B6',
                '#0096C7',
                '#00B4D8',
                '#48CAE4',
                '#90E0EF',
                '#ADE8F4',
                '#CAF0F8',
            ],
        },
    },
    'monoOrange': {
        'labelKey': 'wordcloudStyle.monoOrange',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': ['#7B241C', '#A93226', '#CB4335', '#E74C3C', '#F1948A', '#F5B7B1', '#FADBD8', '#FDEDEC'],
        },
    },
    'pastel': {
        'labelKey': 'wordcloudStyle.pastel',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'normal',
            'color': [
                '#A8E6CF',
                '#DCEDC1',
                '#FFD3B6',
                '#FFAAA5',
                '#FF8B94',
                '#D4A5A5',
                '#9B9B9B',
                '#E8D5B7',
                '#F3E0F2',
            ],
        },
    },
    'ocean': {
        'labelKey': 'wordcloudStyle.ocean',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': [
                '#0A1F3F',
                '#1B4F72',
                '#21618C',
                '#2E86C1',
                '#3498DB',
                '#5DADE2',
                '#85C1E9',
                '#AED6F1',
                '#D4E6F1',
                '#EBF5FB',
            ],
        },
    },
    'sunset': {
        'labelKey': 'wordcloudStyle.sunset',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': ['#4A0E4E', '#801C5C', '#B83D65', '#E66A5D', '#F59E5C', '#FDD87A', '#FFF2B2', '#FFF8E1'],
        },
    },
    'forest': {
        'labelKey': 'wordcloudStyle.forest',
        'textStyle': {
            'fontFamily': 'sans-serif',
            'fontWeight': 'bold',
            'color': [
                '#003F1C',
                '#006B2D',
                '#238B45',
                '#41AB5D',
                '#74C476',
                '#A1D99B',
                '#C7E9C0',
                '#E2F3DA',
                '#F4FBF1',
            ],
        },
    },
}

# These have no sane matplotlib equivalent without extra heavy dependencies
# (echarts-wordcloud, a sankey layout engine, GeoJSON map data) — they are
# ECharts-only. render_image() raises a clear ChartConfigError for these.
# ``dual_line`` joins them for a different reason: a second axis is drawable with
# ``twinx()``, but the right-hand scale, legend and shared tooltip are the parts that make
# 热度 and 强度 readable on one figure, and re-implementing them per engine is how the two
# engines start telling the same data differently.
ECHARTS_ONLY_TYPES = (
    'wordcloud',
    'sankey',
    'map',
    'dual_line',
    'topic_map',
    'topic_terms',
    'network',
    'model_agreement',
)

#: Chart types that can carry dated event markers (a vertical line at one category). Any other
#: type that is handed the box is refused rather than ignored: an annotation the figure does not
#: show is worse than no annotation, because the user believes it is there.
ANNOTATED_TYPES = ('bar', 'line', 'dual_line')


class ChartConfigError(ValueError):
    """Raised when the chart spec is missing required fields for the chosen type."""


class VisualizationService:
    """Builds chart specs from a DataFrame. Stateless / reusable."""

    # ── Shared data prep ────────────────────────────────────────

    @staticmethod
    def _require_columns(df: pd.DataFrame, *names):
        """Every builder indexes the frame by user-configured field names.

        A renamed or mistyped column must say so: a bare ``KeyError: 'nope'``
        reaches the user as an opaque node failure, and a missing *y* used to
        silently degrade a sum chart into a row count.
        """
        for name in names:
            if name and name not in df.columns:
                raise ChartConfigError(f'Field not found in the data: {name}')

    @staticmethod
    def _aggregate(df: pd.DataFrame, x: str, y: str = None, agg: str = 'sum'):
        """Group by *x* and aggregate *y* (or count rows if y is None).

        The category order is the TABLE's, not an alphabetical one. This step is the last chance to
        lose a lifecycle: 表 2 arrives sorted by 阶段序号, and `sort_index()` here put 一次爆发期 in
        the first bar of 图 3 — a figure that reads the event backwards while looking complete. A
        group that appears again later keeps its first position (`sort=False`), because "where the
        user put it" is the only ordering this layer is allowed to trust.
        """
        VisualizationService._require_columns(df, x, y)
        if y:
            numeric = pd.to_numeric(df[y], errors='coerce')
            grouped = numeric.groupby(df[x], sort=False).agg(agg)
        else:
            grouped = df.groupby(x, sort=False).size()
        return [_localize_label(value) for value in grouped.index.astype(str)], grouped.values.tolist()

    # ── ECharts option builder ───────────────────────────────────

    @classmethod
    def to_echarts_option(cls, df: pd.DataFrame, chart_type: str, **kwargs) -> dict:
        """Build a chart spec for *chart_type*.

        The spec is always JSON-safe: non-finite numbers survive some
        aggregations (a mean over an all-missing group is NaN) and a single
        ``NaN`` token would make the browser reject the entire response.
        """
        return _json_safe(cls._print_style(cls._build_option(df, chart_type, **kwargs)))

    @classmethod
    def _print_style(cls, option: dict) -> dict:
        """One pass that turns a dashboard drawing into a figure for a paper.

        Three separate branches used to carry the same three complaints, so the fixes live together
        where a missing one is visible:

        * **Nothing is clipped.** Dense category axes are rotated and asked for every tick
          (``interval: 0``) — ECharts' default drops labels to avoid crowding, which is how 图 2
          lost days of its own x axis; and a cartesian grid gets ``containLabel`` plus real margins
          so the rotated text and the axis names (PC1/PC2 were cut at the frame edge) are inside it.
        * **The ink is print-safe.** A smoothed line over a gradient area fill is a UI affordance:
          it invents shape between two measured days and shades the space under it. Lines are drawn
          straight, thin, with small markers and no area.
        * **A force graph is laid out before it is shown.** ``force.animate`` iterates the solver on
          screen, so 图 16 drifted for tens of seconds before it balanced. With the animation off
          and a circular seed, the first paint is the settled figure and it stays put.
        """
        for axis_key in ('xAxis', 'yAxis'):
            axes = option.get(axis_key)
            if not axes:
                continue
            for axis in axes if isinstance(axes, list) else [axes]:
                if not isinstance(axis, dict):
                    continue
                label = axis.setdefault('axisLabel', {})
                label['fontFamily'] = PRINT_FONT
                label.setdefault('fontSize', 10)
                if axis.get('type') == 'category' and len(label.get('data') or axis.get('data') or []) > 12:
                    # Rotated and never dropped: the alternative is a figure whose axis lies about
                    # its own granularity.
                    label['rotate'] = 45
                    label['interval'] = 0
                    label['hideOverlap'] = False
                if axis.get('name'):
                    axis['nameLocation'] = axis.get('nameLocation') or 'middle'
                    axis['nameGap'] = axis.get('nameGap') or (28 if axis_key == 'yAxis' else 34)
                    axis['nameTextStyle'] = {**(axis.get('nameTextStyle') or {}), 'fontFamily': PRINT_FONT}
                # A paper figure has no graph paper and no floating box: gridlines off, and the
                # axis lines that stay are the two the reader measures against, in dark ink. The
                # per-type builders still carry the old dark-theme UI defaults (light labels,
                # dashed splitLine); this pass is what makes every figure read as a 图, not a board.
                axis.setdefault('splitLine', {})['show'] = False
                axis.setdefault('axisLine', {})['show'] = True
                axis['axisLine'].setdefault('lineStyle', {})['color'] = '#666'
                axis.setdefault('axisTick', {})['show'] = True
                axis['axisTick'].setdefault('lineStyle', {})['color'] = '#666'
                label['color'] = '#333'

        grid = option.get('grid')
        if isinstance(grid, dict):
            grid['containLabel'] = True
            grid['bottom'] = max(int(grid.get('bottom') or 0), 96)
            grid['right'] = max(int(grid.get('right') or 0), 72)
            grid['left'] = max(int(grid.get('left') or 0), 64)

        title = option.get('title')
        if isinstance(title, dict):
            title['textStyle'] = {
                **(title.get('textStyle') or {}),
                'fontFamily': PRINT_FONT,
                'fontWeight': 'normal',
                'fontSize': 15,
            }
        legend = option.get('legend')
        if isinstance(legend, dict):
            legend['textStyle'] = {**(legend.get('textStyle') or {}), 'fontFamily': PRINT_FONT}

        for series in option.get('series') or []:
            if not isinstance(series, dict):
                continue
            kind = series.get('type')
            if kind == 'line':
                series['smooth'] = False
                series['symbol'] = series.get('symbol') or 'circle'
                series['symbolSize'] = series.get('symbolSize') or 4
                series['showSymbol'] = True
                series['lineStyle'] = {**(series.get('lineStyle') or {}), 'width': 1.4}
                # A gradient under a line reads as "this area means something"; between two measured
                # days it means nothing, so the paper figure drops it.
                series.pop('areaStyle', None)
            elif kind == 'bar':
                series['itemStyle'] = {**(series.get('itemStyle') or {}), 'borderRadius': 0}
                series.setdefault('barMaxWidth', 42)
            elif kind == 'graph':
                series['force'] = {**(series.get('force') or {}), 'animate': False}
                series['layoutAnimation'] = False
            if series.get('label'):
                series['label'] = {**series['label'], 'fontFamily': PRINT_FONT}
        return option

    @classmethod
    def _build_option(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        x: str = None,
        y: str = None,
        value_field: str = None,
        _series: str = None,
        agg: str = 'sum',
        y2: str = None,
        agg2: str = None,
        label_field: str = 'topic',
        annotations: str = '',
        title: str = '',
        **kwargs,
    ) -> dict:
        if chart_type not in CHART_TYPES:
            raise ChartConfigError(f'Unsupported chart type: {chart_type}')
        if annotations and chart_type not in ANNOTATED_TYPES:
            # Checked before anything is built, so the message is about the box, not about a
            # half-drawn figure.
            raise ChartConfigError(
                f'the {chart_type} figure cannot carry event markers: only {", ".join(ANNOTATED_TYPES)} draw a '
                'vertical line at one category. Clear the box rather than trusting a figure '
                'that quietly dropped it.'
            )

        color = CATEGORY_COLORS[:]

        base = {
            'backgroundColor': 'transparent',
            'color': color,
            'title': {
                'text': title,
                'textStyle': {'color': '#e8e8e8', 'fontSize': 14, 'fontWeight': 500, 'fontFamily': 'sans-serif'},
                'left': 'center',
                'top': 6,
            },
            'tooltip': {
                'trigger': 'item' if chart_type in ('pie', 'wordcloud', 'map', 'sankey', 'network') else 'axis',
                'backgroundColor': 'rgba(30,30,40,0.9)',
                'borderColor': '#444',
                'borderWidth': 1,
                'textStyle': {'color': '#eee', 'fontSize': 12, 'fontFamily': 'sans-serif'},
                'formatter': '{b}: {c}' if chart_type not in ('pie', 'sankey', 'network') else None,
            },
            'animationDuration': 800,
            'animationEasing': 'cubicOut',
        }

        # ── Pie ──
        if chart_type == 'pie':
            if not x:
                raise ChartConfigError('Pie chart requires a category field (x)')
            labels, values = cls._aggregate(df, x, y, agg)
            base['tooltip']['formatter'] = '{b}: {c} ({d}%)'
            base['legend'] = {
                'data': labels,
                'orient': 'vertical',
                'right': 10,
                'top': 36,
                'textStyle': _TEXT_STYLE,
                'icon': 'circle',
                'itemWidth': 10,
                'itemHeight': 10,
            }
            base['series'] = [
                {
                    'type': 'pie',
                    'radius': ['30%', '62%'],
                    'center': ['40%', '52%'],
                    'avoidLabelOverlap': True,
                    'padAngle': 1.5,
                    'itemStyle': {
                        'borderColor': 'rgba(20,20,30,0.6)',
                        'borderWidth': 2,
                    },
                    'label': {
                        'formatter': '{b}\n{d}%',
                        'color': '#ccc',
                        'fontSize': 11,
                        'fontFamily': 'sans-serif',
                    },
                    'labelLine': {'lineStyle': {'color': '#555'}},
                    'emphasis': {
                        'itemStyle': {
                            'shadowBlur': 12,
                            'shadowColor': 'rgba(0,0,0,0.4)',
                        },
                        'label': {'fontSize': 13, 'fontWeight': 'bold'},
                    },
                    'data': [{'name': n, 'value': v} for n, v in zip(labels, values, strict=True)],
                }
            ]
            return base

        # ── Scatter ──
        if chart_type == 'scatter':
            if not x or not y:
                raise ChartConfigError('Scatter chart requires both x and y fields')
            cls._require_columns(df, x, y)
            xs = pd.to_numeric(df[x], errors='coerce')
            ys = pd.to_numeric(df[y], errors='coerce')
            base['grid'] = dict(_GRID)
            base['xAxis'] = {
                'type': 'value',
                'name': _localize_label(x),
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['yAxis'] = {
                'type': 'value',
                'name': _localize_label(y),
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['tooltip']['formatter'] = (
                f'<b>{{@[0]}}</b><br/>{_localize_label(x)}: {{@[0]}}<br/>{_localize_label(y)}: {{@[1]}}'
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

        # ── Histogram ──
        if chart_type == 'histogram':
            if not x:
                raise ChartConfigError('Histogram requires a numeric field (x)')
            cls._require_columns(df, x)
            values = pd.to_numeric(df[x], errors='coerce').dropna()
            counts, edges = _histogram_bins(values)
            labels_bin = [f'{e:.1f}' for e in edges[:-1]]
            base['grid'] = dict(_GRID)
            base['xAxis'] = {
                'type': 'category',
                'data': labels_bin,
                'name': _localize_label(x),
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['yAxis'] = {
                'type': 'value',
                'name': t('chart.count'),
                'nameTextStyle': _TEXT_STYLE,
                **_AXIS_STYLE,
            }
            base['series'] = [
                {
                    'type': 'bar',
                    'data': counts,
                    'barWidth': '98%',
                    'itemStyle': {
                        'color': color[0],
                        'borderRadius': [1, 1, 0, 0],
                    },
                    'emphasis': {'itemStyle': {'color': color[1]}},
                }
            ]
            return base

        # ── Box ──
        if chart_type == 'box':
            if y and y in df.columns:
                # Grouped box plot: x = category, y = numeric value
                if not x:
                    raise ChartConfigError('Box plot requires a category field (x) for grouping')
                groups = [
                    (_localize_label(name), pd.to_numeric(group[y], errors='coerce').dropna())
                    for name, group in df.groupby(x)
                ]
                labels = [g[0] for g in groups]
                data = [_box_stats(g[1]) for g in groups]
                scatter_data = []
                for i, (_, vals) in enumerate(groups):
                    for v in vals.tolist():
                        scatter_data.append([i, v])
            elif x and x in df.columns:
                # Single box plot: x = numeric value (backward compat)
                values = pd.to_numeric(df[x], errors='coerce').dropna()
                stats = _box_stats(values)
                labels = [_localize_label(x)]
                data = [stats]
                scatter_data = [[0, v] for v in values.tolist()]
            else:
                raise ChartConfigError(
                    'Box plot requires a category field (x) and a numeric field (y), or a single numeric field (x)'
                )
            base['grid'] = dict(_GRID)
            base['xAxis'] = {
                'type': 'category',
                'data': labels,
                **_AXIS_STYLE,
            }
            base['yAxis'] = {
                'type': 'value',
                **_AXIS_STYLE,
            }
            base['series'] = [
                {
                    'type': 'boxplot',
                    'data': data,
                    'itemStyle': {'color': color[0], 'borderColor': color[0]},
                    'boxWidth': [20, 60],
                }
            ]
            if scatter_data:
                base['series'].append(
                    {
                        'type': 'scatter',
                        'data': scatter_data,
                        'symbolSize': 4,
                        'itemStyle': {'color': 'rgba(59,130,249,0.3)'},
                        'tooltip': {'formatter': '{c}'},
                    }
                )
            return base

        # ── Heatmap ──
        if chart_type == 'heatmap':
            if not x or not y:
                raise ChartConfigError('Heatmap requires two category fields (x and y)')
            xcats, ycats, matrix = cls._pivot(df, x, y, value_field, agg)
            # Bounds come from the usable numbers only: an all-missing cell makes
            # the aggregate NaN, and NaN bounds would leave the colour scale blank.
            vals = _finite(v for row in matrix for v in row)
            return cls._apply_heatmap_option(
                base, xcats, ycats, matrix, min(vals) if vals else 0, max(vals) if vals else 1
            )

        # 模型一致率: pairwise label-agreement (percentage of the shared rows on which two
        # models chose the SAME label) drawn as the same square heatmap. It reads the tidy
        # multi-model table by its 模型 / 标签 / 原行 columns, so a renamed analysis output
        # refuses by name rather than rendering a matrix of the wrong thing.
        if chart_type == 'model_agreement':
            cats, matrix = cls._agreement_matrix(
                df,
                kwargs.get('model_field') or '模型',
                kwargs.get('agreement_label_field'),
                kwargs.get('id_field') or '原行',
            )
            return cls._apply_heatmap_option(base, cats, cats, matrix, 0, 100)

        # ── Sankey ──
        if chart_type == 'sankey':
            if not x or not y:
                raise ChartConfigError('Sankey diagram requires a source field (x) and a target field (y)')
            nodes, links = cls._sankey_links(df, x, y, value_field, agg)
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

        # ── Force-directed network: the co-occurrence and flow graphs ──
        if chart_type == 'network':
            if not x or not y:
                raise ChartConfigError('Network graph requires a source field (x) and a target field (y)')
            nodes, links = cls._sankey_links(df, x, y, value_field, agg)
            if not links:
                # The sankey would draw an empty frame and look like a finished figure; a graph
                # with no edge is not "a sparse relationship network", it is nothing measured.
                raise ChartConfigError(
                    f'network graph has no edges: every {x}/{y} pair was blank, zero-weighted or unvalued'
                )
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

        # ── Word cloud ──
        if chart_type == 'wordcloud':
            if not x:
                raise ChartConfigError('Word cloud requires a text/category field (x)')
            if kwargs.get('tokenize'):
                labels, values = cls.tokenize_frequency(df, x)
            else:
                labels, values = cls._aggregate(df, x, value_field, agg)
            style_name = kwargs.get('wordcloud_style', 'vibrant')
            # Deliberate fallback, unlike the parameters that choose *data* or *cost*:
            # a word cloud's palette is decoration, and an unknown name (a preset this
            # build no longer ships, a caller that guessed one) must still produce the
            # chart the rest of the request asked for. The node's own refusal rule
            # applies wherever a silent default would change what the user got — the
            # crawl board, the file format, the algorithm, the renderer.
            style = WORDCLOUD_STYLES.get(style_name, WORDCLOUD_STYLES['vibrant'])
            palette = style['textStyle'].get('color', '#ccc')
            if isinstance(palette, list):
                data = [
                    {'name': n, 'value': v, 'textStyle': {'color': palette[i % len(palette)]}}
                    for i, (n, v) in enumerate(zip(labels, values, strict=True))
                ]
            else:
                data = [{'name': n, 'value': v} for n, v in zip(labels, values, strict=True)]
            series_style = {
                'fontFamily': style['textStyle'].get('fontFamily', 'sans-serif'),
                'fontWeight': style['textStyle'].get('fontWeight', 'bold'),
            }
            if not isinstance(palette, list):
                series_style['color'] = palette
            base['series'] = [
                {
                    'type': 'wordCloud',
                    'shape': 'circle',
                    'sizeRange': [14, 64],
                    'rotationRange': [-45, 45],
                    'rotationStep': 30,
                    'gridSize': 6,
                    'drawOutOfBound': False,
                    'textStyle': series_style,
                    'data': data,
                }
            ]
            return base

        # ── Map ──
        if chart_type == 'map':
            if not x:
                raise ChartConfigError('Map chart requires a region-name field (x)')
            labels, values = cls._aggregate(df, x, value_field, agg)
            # NaN would poison the colour scale's upper bound.
            max_val = max(_finite(values) or [1]) or 1
            base['tooltip']['formatter'] = '<b>{b}</b><br/>{c}'
            base['visualMap'] = {
                'min': 0,
                'max': max_val,
                'left': 10,
                'bottom': 10,
                'text': [t('chart.range.high'), t('chart.range.low')],
                'textStyle': {'color': '#aaa', 'fontSize': 10},
                'inRange': {'color': ['#ffffff', '#fef0d9', '#fdcc8a', '#fc8d59', '#e34a33', '#b30000']},
            }
            base['series'] = [
                {
                    'type': 'map',
                    'map': 'china',
                    'roam': True,
                    'selectedMode': 'multiple',
                    'label': {'show': True, 'color': '#555', 'fontSize': 9, 'fontWeight': 400},
                    'emphasis': {
                        'label': {'show': True, 'color': '#fff', 'fontSize': 12, 'fontWeight': 'bold'},
                        'itemStyle': {
                            'areaColor': '#f46d43',
                            'shadowBlur': 10,
                            'shadowColor': 'rgba(0,0,0,0.15)',
                        },
                    },
                    'itemStyle': {
                        'borderColor': 'rgba(0,0,0,0.12)',
                        'borderWidth': 0.8,
                    },
                    'data': [{'name': n, 'value': v} for n, v in zip(labels, values, strict=True)],
                }
            ]
            return base

        # ── Intertopic distance map (the pyLDAvis left panel) ──
        if chart_type == 'topic_map':
            if not x or not y:
                raise ChartConfigError('Intertopic map needs both coordinate fields (x = PC1, y = PC2)')
            VisualizationService._require_columns(df, x, y)
            has_label = bool(label_field) and label_field in df.columns
            has_size = bool(value_field) and value_field in df.columns
            first = pd.to_numeric(df[x], errors='coerce').tolist()
            second = pd.to_numeric(df[y], errors='coerce').tolist()
            labels = [_localize_label(name) for name in (df[label_field].tolist() if has_label else [''] * len(df))]
            sizes = pd.to_numeric(df[value_field], errors='coerce').tolist() if has_size else [None] * len(df)
            biggest = max((float(size) for size in sizes if size == size and size is not None), default=0.0)
            points = []
            for position, name in enumerate(labels):
                size = sizes[position]
                # AREA, not radius, carries the prevalence — a bubble drawn twice as wide for
                # twice the share reads as four times the share, which is the mistake the
                # original figure's square root is there to avoid. The floor is what keeps a
                # zero-share (or unsized) topic visible rather than absent from the map.
                radius = (
                    10.0
                    if not biggest or size != size or size is None
                    else max(10.0, 70.0 * (float(size) / biggest) ** 0.5)
                )
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

        # ── Salient terms of one topic (the pyLDAvis right panel) ──
        if chart_type == 'topic_terms':
            if not x:
                raise ChartConfigError('Salient terms chart requires a term field (x)')
            if not y or not y2:
                raise ChartConfigError(
                    'Salient terms chart needs BOTH frequency fields (y = corpus-wide, y2 = within the topic)'
                )
            VisualizationService._require_columns(df, x, y, y2)
            terms = [str(name) for name in df[x].tolist()]
            overall = pd.to_numeric(df[y], errors='coerce').tolist()
            within = pd.to_numeric(df[y2], errors='coerce').tolist()
            y_disp, y2_disp = _localize_label(y), _localize_label(y2)
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

        # ── Dual-axis line: two magnitudes on one time axis ──
        if chart_type == 'dual_line':
            if not x:
                raise ChartConfigError('Dual-axis line chart requires a category field (x)')
            if not y2:
                raise ChartConfigError('Dual-axis line chart requires a second value field (y2) — the right axis')
            # Display names only; the grouping below still reads the raw columns.
            left_name = _localize_label(y) if y else f'{t("chart.count")}（{_localize_label(x)}）'
            y2_name = _localize_label(y2)
            labels, left = cls._aggregate(df, x, y, agg)
            # Both series group by the SAME x, so they share the category axis by
            # construction; only the second series' values are wanted here.
            _, right = cls._aggregate(df, x, y2, agg2 or agg)
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
            # A LIST is what makes ECharts draw two scales; each series then says which one
            # it belongs to. The right axis carries no grid lines, or the plot area becomes a
            # second graph paper laid over the first.
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
            if annotations:
                # On the LEFT series, whose values the shared category axis is built from: the
                # marker belongs to the time axis, not to either curve.
                base['series'][0]['markLine'] = _annotation_lines(_parse_annotations(annotations), labels, x)
            return base

        # ── 100% stacked share (any independent distribution over a category axis) ──
        if chart_type == 'stack_pct':
            stack_fields = [
                s.strip() for s in str(kwargs.get('stack_fields') or '').replace('，', ',').split(',') if s.strip()
            ]
            if not x:
                raise ChartConfigError('stack_pct chart requires a category field (x)')
            if not stack_fields:
                raise ChartConfigError('stack_pct chart requires stacked fields (stack_fields)')
            # One message shape for a missing column across every chart type, so a wrong field
            # name reads the same whether it is the axis or one of the stacked shares.
            cls._require_columns(df, x, *stack_fields)
            grouped = df.groupby(x, sort=False)
            keys = list(grouped.groups.keys())
            labels = [str(k) for k in keys]
            cols = {f: grouped[f].sum().reindex(keys).fillna(0).tolist() for f in stack_fields}
            # Each period is normalised to 100%, so the figure reads as shares whether the
            # source columns are already percentages or raw counts.
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

        # ── Bar / Line ──
        if not x:
            raise ChartConfigError(f'{chart_type} chart requires a category field (x)')
        labels, values = cls._aggregate(df, x, y, agg)
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

        if chart_type == 'bar':
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
        elif chart_type == 'line':
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

        if annotations:
            base['series'][0]['markLine'] = _annotation_lines(_parse_annotations(annotations), labels, x)

        return base

    @staticmethod
    def tokenize_frequency(df: pd.DataFrame, column: str, top_n: int = 120):
        """Tokenize a free-text column into word frequencies for a word
        cloud. Uses jieba for Chinese segmentation (this app's crawler
        content is primarily Chinese); falls back to whitespace splitting
        for non-Chinese text if jieba isn't installed.

        The stop-word rule is the shared one (:mod:`analyzers.stopwords`), not the small local set
        this used to carry: a cloud drawn from a different vocabulary than 表 1's 特征词 is two
        measurements of the same corpus that a reader cannot put side by side.
        """
        VisualizationService._require_columns(df, column)
        from analyzers.stopwords import is_meaningful

        texts = df[column].dropna().astype(str).tolist()
        counter = Counter()
        try:
            for text in texts:
                for token in jieba.lcut(text):
                    if not is_meaningful(token):
                        continue
                    counter[token] += 1
        except ImportError:
            for text in texts:
                for token in text.split():
                    word = token.strip().lower()
                    if word and is_meaningful(word):
                        counter[word] += 1

        top = counter.most_common(top_n)
        if not top:
            return [], []
        labels, values = zip(*top, strict=True)
        return list(labels), list(values)

    @staticmethod
    def _apply_heatmap_option(base, xcats, ycats, matrix, min_val, max_val):
        """Turn an (xcats × ycats) numeric matrix into the shared ECharts heatmap spec.

        Both the data heatmap and the 模型一致率 matrix draw identically, so the colour ramp,
        axes and visualMap live in ONE place — a tweak to the figure reaches both, and the two
        can never drift apart. Bounds are supplied by the caller (counts vs a fixed 0–100 %).
        """
        data = [[xi, yi, matrix[yi][xi]] for yi in range(len(ycats)) for xi in range(len(xcats))]
        base['grid'] = {'left': 80, 'right': 60, 'top': 10, 'bottom': 60}
        base['xAxis'] = {
            'type': 'category',
            'data': xcats,
            'splitArea': {'show': True, 'areaStyle': {'color': ['rgba(0,0,0,0)']}},
            'axisLabel': {'rotate': 30, 'color': '#aaa', 'fontSize': 10},
            'axisLine': {'show': False},
        }
        base['yAxis'] = {
            'type': 'category',
            'data': ycats,
            'splitArea': {'show': True, 'areaStyle': {'color': ['rgba(0,0,0,0)']}},
            'axisLabel': {'color': '#aaa', 'fontSize': 10},
            'axisLine': {'show': False},
        }
        base['visualMap'] = {
            'min': min_val,
            'max': max_val,
            'calculable': True,
            'orient': 'horizontal',
            'left': 'center',
            'bottom': 8,
            'inRange': {
                'color': [
                    '#313695',
                    '#4575B4',
                    '#74ADD1',
                    '#ABD9E9',
                    '#E0F3F8',
                    '#FFFFBF',
                    '#FEE090',
                    '#FDAE61',
                    '#F46D43',
                    '#D73027',
                    '#A50026',
                ]
            },
            'textStyle': {'color': '#aaa', 'fontSize': 10},
        }
        base['series'] = [
            {
                'type': 'heatmap',
                'data': data,
                'label': {'show': True, 'color': '#ccc', 'fontSize': 10, 'fontFamily': 'sans-serif'},
                'emphasis': {'itemStyle': {'shadowBlur': 8, 'shadowColor': 'rgba(0,0,0,0.4)'}},
            }
        ]
        return base

    @classmethod
    def _agreement_matrix(cls, df, model_col, label_col, id_col):
        """Pairwise label-agreement (percent of the rows two models both answered where they
        chose the same label), aligned by ``id_col`` across the tidy multi-model table.

        The model order is the TABLE's first-appearance order (never alphabetical), for the
        same reason `_aggregate`/`_pivot` keep it: the canvas put the models somewhere, and
        an off-diagonal cell is read against that axis. A pair is scored only over rows where
        BOTH models answered (a row one model left blank cannot be an agreement or a
        disagreement); the diagonal is 100 by definition. Fewer than two models refuses — a
        1×1 square is not a comparison and would hide that the node ran one model.
        """
        cls._require_columns(df, model_col, id_col)
        if not label_col:
            raise ChartConfigError('model_agreement needs the label column (agreement_label_field)')
        cls._require_columns(df, label_col)
        order = []
        for value in df[model_col].astype(str):
            if value not in order:
                order.append(value)
        if len(order) < 2:
            raise ChartConfigError(f'model_agreement needs at least 2 models in {model_col!r}; found {len(order)}')
        # One Series per model, indexed by the row id, so a pair aligns on 原行 not on position.
        per_model = {name: g.set_index(id_col)[label_col] for name, g in df.groupby(df[model_col].astype(str))}
        matrix = []
        for a in order:
            row = []
            for b in order:
                if a == b:
                    row.append(100.0)
                    continue
                sa, sb = per_model[a], per_model[b]
                joined = pd.concat([sa, sb], axis=1, join='inner', keys=['a', 'b'])
                n = len(joined)
                if n == 0:
                    row.append(0.0)
                    continue
                agree = (joined['a'].astype(str) == joined['b'].astype(str)).sum() / n * 100.0
                row.append(round(float(agree), 2))
            matrix.append(row)
        cats = [_localize_label(name) for name in order]
        return cats, matrix

    @staticmethod
    def _pivot(df: pd.DataFrame, x: str, y: str, value_field: str = None, agg: str = 'count'):
        """Build a y-by-x matrix for a heatmap: counts co-occurrences of
        (x, y) pairs, or aggregates value_field over each pair if given.

        Both axes keep the table's order, for the same reason `_aggregate` does — `pivot_table`
        sorts its index and columns, which would put a heatmap's phases in code-point order and
        make the picture disagree with the 表 it was built from.
        """
        VisualizationService._require_columns(df, x, y)
        work = df[[x, y]].copy()
        xcats = [str(value) for value in pd.unique(df[x].astype(str))]
        ycats = [str(value) for value in pd.unique(df[y].astype(str))]
        work['_xc'] = work[x].astype(str)
        work['_yc'] = work[y].astype(str)
        if value_field and value_field in df.columns:
            work['_v'] = pd.to_numeric(df[value_field], errors='coerce')
            grouped = work.groupby(['_yc', '_xc'], sort=False)['_v'].agg(agg)
        else:
            grouped = work.groupby(['_yc', '_xc'], sort=False).size()
        cells = {
            (str(ykey), str(xkey)): (value if np.isfinite(value) else 0) for (ykey, xkey), value in grouped.items()
        }
        matrix = [[cells.get((yy, xx), 0) for xx in xcats] for yy in ycats]
        # The matrix is addressed by the RAW strings above; localise only what reaches the screen.
        return [_localize_label(value) for value in xcats], [_localize_label(value) for value in ycats], matrix

    @staticmethod
    def _sankey_links(df: pd.DataFrame, source: str, target: str, value_field: str = None, agg: str = 'count'):
        """Build ECharts sankey nodes+links from a source/target column pair
        (e.g. platform -> emotion), weighted by row count or value_field."""
        VisualizationService._require_columns(df, source, target)
        work = df[[source, target]].copy()
        work.columns = ['_s', '_t']
        if value_field and value_field in df.columns:
            work['_v'] = pd.to_numeric(df[value_field], errors='coerce')
            grouped = work.groupby(['_s', '_t'])['_v'].agg(agg).reset_index()
        else:
            grouped = work.groupby(['_s', '_t']).size().reset_index(name='_v')

        # Sankey requires distinct node names; if a value appears on both
        # sides (e.g. same label used as both source and target) ECharts
        # can still render it as one shared node, so no renaming is needed.
        # A zero-weight link renders as nothing in ECharts and a NaN weight is
        # not valid JSON, so neither one is emitted.
        links = []
        for _, row in grouped.iterrows():
            weights = _finite([row['_v']])
            if weights and weights[0]:
                links.append(
                    {
                        'source': _localize_label(row['_s']),
                        'target': _localize_label(row['_t']),
                        'value': weights[0],
                    }
                )
        nodes = sorted(
            set(_localize_label(v) for v in grouped['_s'].astype(str))
            | set(_localize_label(v) for v in grouped['_t'].astype(str))
        )
        return nodes, links

    # ── Matplotlib renderer (server-side PNG) ───────────────────

    @classmethod
    def render_image(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        x: str = None,
        y: str = None,
        value_field: str = None,
        agg: str = 'sum',
        title: str = '',
        annotations: str = '',
        stack_fields: str = '',
    ) -> str:
        """Render the chart with matplotlib and return a base64 PNG data URI."""

        if chart_type not in CHART_TYPES:
            raise ChartConfigError(f'Unsupported chart type: {chart_type}')
        if annotations:
            # The markers exist as an ECharts ``markLine`` on a category axis; a PNG without
            # them would be a figure whose dates vanished with no word said.
            raise ChartConfigError(
                'event markers (annotations) are only drawn with engine=echarts — the matplotlib '
                'renderer has no marker layer, so switch engine or clear the box'
            )
        if chart_type in ECHARTS_ONLY_TYPES:
            raise ChartConfigError(
                f'"{chart_type}" is only available with engine=echarts '
                f'(no matplotlib equivalent without extra dependencies)'
            )
        # Same field requirements as the ECharts builder, so both engines fail
        # the same readable way — groupby(None) is a bare pandas TypeError.
        if chart_type in ('scatter', 'heatmap'):
            if not x or not y:
                raise ChartConfigError(f'{chart_type} chart requires both x and y fields')
        elif chart_type in ('pie', 'histogram', 'box', 'line', 'bar', 'stack_pct') and not x:
            raise ChartConfigError(f'{chart_type} chart requires a field (x)')
        # Every branch below indexes the frame by the configured field names.
        cls._require_columns(df, x, y)

        fig, ax = plt.subplots(figsize=(7, 4.2), dpi=130)
        try:
            if chart_type == 'pie':
                labels, values = cls._aggregate(df, x, y, agg)
                ax.pie(values, labels=labels, autopct='%1.1f%%', textprops={'fontsize': 8})
            elif chart_type == 'scatter':
                ax.scatter(pd.to_numeric(df[x], errors='coerce'), pd.to_numeric(df[y], errors='coerce'), s=18)
                ax.set_xlabel(_localize_label(x))
                ax.set_ylabel(_localize_label(y))
            elif chart_type == 'histogram':
                ax.hist(pd.to_numeric(df[x], errors='coerce').dropna(), bins=20)
                ax.set_xlabel(_localize_label(x))
                ax.set_ylabel(t('chart.count'))
            elif chart_type == 'box':
                if y:
                    groups = [pd.to_numeric(group[y], errors='coerce').dropna().values for _, group in df.groupby(x)]
                    grp_labels = [_localize_label(str(name)) for name in df.groupby(x).groups]
                    _boxplot(ax, groups, grp_labels)
                    ax.set_xlabel(_localize_label(x))
                else:
                    _boxplot(ax, pd.to_numeric(df[x], errors='coerce').dropna(), [x])
            elif chart_type == 'heatmap':
                xcats, ycats, matrix = cls._pivot(df, x, y, value_field, agg if value_field else 'count')
                im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
                ax.set_xticks(range(len(xcats)))
                ax.set_xticklabels(xcats, rotation=45, ha='right', fontsize=8)
                ax.set_yticks(range(len(ycats)))
                ax.set_yticklabels(ycats, fontsize=8)
                fig.colorbar(im, ax=ax)
            elif chart_type == 'line':
                labels, values = cls._aggregate(df, x, y, agg)
                ax.plot(labels, values, marker='o')
                ax.tick_params(axis='x', rotation=45)
            elif chart_type == 'stack_pct':
                fields = [s.strip() for s in str(stack_fields or '').replace('，', ',').split(',') if s.strip()]
                if not fields:
                    raise ChartConfigError('stack_pct chart requires stacked fields (stack_fields)')
                cls._require_columns(df, *fields)
                grouped = df.groupby(x, sort=False)
                keys = list(grouped.groups.keys())
                cats = [str(k) for k in keys]
                cols = {f: grouped[f].sum().reindex(keys).fillna(0).tolist() for f in fields}
                totals = [sum(cols[f][i] for f in fields) for i in range(len(cats))]
                bottoms = [0.0] * len(cats)
                for idx, f in enumerate(fields):
                    shares = [cols[f][i] / totals[i] * 100 if totals[i] else 0.0 for i in range(len(cats))]
                    ax.bar(
                        cats,
                        shares,
                        bottom=bottoms,
                        label=_localize_label(f),
                        color=CATEGORY_COLORS[idx % len(CATEGORY_COLORS)],
                    )
                    bottoms = [b + s for b, s in zip(bottoms, shares, strict=True)]
                ax.set_ylabel(t('chart.col.share'))
                ax.set_ylim(0, 100)
                ax.legend(frameon=False, fontsize=8, ncol=len(fields))
                ax.tick_params(axis='x', rotation=45)
            else:  # bar
                labels, values = cls._aggregate(df, x, y, agg)
                ax.bar(labels, values)
                ax.tick_params(axis='x', rotation=45)

            if chart_type not in ('pie', 'heatmap'):
                # A paper figure keeps the two axes the reader measures against and drops the
                # box: no top/right spine, dark left/bottom, no gridlines.
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                for _spine in ('left', 'bottom'):
                    ax.spines[_spine].set_color('#666')

            if title:
                ax.set_title(title)
            fig.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True)
        finally:
            # Nearly every step above can raise — a pie of negative values, a
            # groupby over all-null data, matplotlib refusing to lay out a tick.
            # Closing only on the success path leaked one open figure per failed
            # render into matplotlib's registry, and the UI retries charts.
            plt.close(fig)
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode('ascii')
        return f'data:image/png;base64,{encoded}'


def _boxplot(ax, data, labels):
    """matplotlib ≥ 3.9 renamed ``boxplot(labels=…)`` to ``tick_labels=…``.

    Called through a helper so the app still runs on an older matplotlib
    instead of dying with "unexpected keyword argument 'labels'".
    """
    try:
        return ax.boxplot(data, tick_labels=labels)
    except TypeError:
        return ax.boxplot(data, labels=labels)


def _histogram_bins(values: pd.Series, bins: int = 10):
    if values.empty:
        return [], [0, 1]
    counts, edges = pd.cut(values, bins=bins, retbins=True, duplicates='drop')
    hist = counts.value_counts().sort_index()
    return hist.tolist(), edges.tolist()


def _box_stats(values: pd.Series) -> list:
    if values.empty:
        return [0, 0, 0, 0, 0]
    q1, q2, q3 = values.quantile([0.25, 0.5, 0.75])
    iqr = q3 - q1
    lower = max(values.min(), q1 - 1.5 * iqr)
    upper = min(values.max(), q3 + 1.5 * iqr)
    return [float(lower), float(q1), float(q2), float(q3), float(upper)]
