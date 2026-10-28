"""Fonts, paper palette and the small value helpers the chart options share.

Every Matplotlib figure and every ECharts option reads its colours, font stack and label
localisation here, so a recolour or a new CJK family is one edit rather than two.

The font stack holds each OS's own names, not just this box's: since matplotlib 3.6 the list
falls through PER GLYPH, so a family that carries Chinese may sit behind DejaVu Sans and still
do its job. Missing those names is not a cosmetic gap: matplotlib resolves to DejaVu, every Han
character draws as a box, and the figure goes into a paper looking finished.
"""

import logging
import math
import re
from functools import lru_cache

import numpy as np
import pandas as pd
from core import machine

from i18n import t
from services.charts.contracts import ChartConfigError

logger = logging.getLogger(__name__)


#: The font stack every Matplotlib figure is drawn with. Order is not a ranking here: since 3.6
#: matplotlib falls through the list PER GLYPH, so a family that carries Chinese may sit behind
#: DejaVu Sans and still do its job. ``sans-serif`` is matplotlib's own last resort.
#:
#: The list has to hold each OS's own names, not just this box's: the Windows families are what a
#: desktop has, while a Linux server's Chinese fonts come from the distro package (Noto Sans CJK SC,
#: WenQuanYi Zen Hei — what ``fonts-noto-cjk`` / ``fonts-wqy-zenhei`` register) and a Mac's from the
#: system (PingFang SC). Missing those names is not a cosmetic gap: matplotlib resolves to DejaVu,
#: every Han character draws as a box, and the figure goes into a paper looking finished.
FONT_STACK = [
    'SimHei',
    'Microsoft YaHei',
    'Noto Sans CJK SC',
    'Source Han Sans SC',
    'WenQuanYi Zen Hei',
    'WenQuanYi Micro Hei',
    'PingFang SC',
    'Hiragino Sans GB',
    'DejaVu Sans',
    'Arial Unicode MS',
    'sans-serif',
]

#: Entries above that hold no Chinese glyphs at all, so resolving one of them would answer the
#: question below with a wrong yes.
_NO_CHINESE = frozenset({'DejaVu Sans', 'sans-serif'})

#: The CJK families this app asks for, in the order it asks.
_CJK_CANDIDATES = [family for family in FONT_STACK if family not in _NO_CHINESE]


@lru_cache(maxsize=1)
def cjk_font() -> str:
    """The first family in :data:`FONT_STACK` that is installed and carries Chinese, or ''.

    Cached, and caching is the correct semantics rather than a shortcut: matplotlib builds its font
    manager once per process, so a font installed after that point is invisible until a restart —
    re-asking would just print the same sentence again on a machine that cannot act on it yet.

    '' is a fact about the machine, not a failure: the figure still renders, its digits and Latin are
    right, and every Han character is a box. That is why this is a printed warning instead of a
    refusal — a 30-figure canvas must not die over a font, and silent boxes get typed into a paper.
    """
    from matplotlib import font_manager

    for family in _CJK_CANDIDATES:
        try:
            font_manager.fontManager.findfont(family, fallback_to_default=False)
        except ValueError:
            continue
        return family
    return ''


@lru_cache(maxsize=4)
def _warn_missing_cjk_font(message: str) -> None:
    """Print the missing-font line once per wording.

    Cached on the message, not on a flag, because the console language is per thread: a Chinese run
    and an English run each deserve their own single line, and a plain boolean would let the second
    one say nothing at all. The run console forwards ``logger.warning``, so this is the user-visible
    channel — thirty figures in one canvas must not print the sentence thirty times.
    """
    logger.warning(message)


def _pyplot():
    """Import matplotlib and return ``pyplot`` with this app's headless CJK setup applied.

    The three statements are one function and must stay that way: ``matplotlib.use('Agg')`` has
    to run before ``pyplot`` is imported, and the CJK font list has to be set before any figure
    is drawn. Importing them apart is how a server gains a window or a figure full of boxes
    instead of Chinese labels. matplotlib costs about a second to import, and a canvas that only
    renders ECharts never pays it — so nothing here is imported at module level.
    """
    import matplotlib

    matplotlib.use('Agg')  # headless backend, safe for a web server
    from matplotlib import pyplot as plt

    plt.rcParams['font.sans-serif'] = list(FONT_STACK)
    plt.rcParams['axes.unicode_minus'] = False
    if not cjk_font():
        _warn_missing_cjk_font(
            t(
                'chart.noCjkFont',
                checked='、'.join(_CJK_CANDIDATES),
                remedy=machine.remedy('deps.systemFont'),
            )
        )
    return plt


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


# ── Category palette (Nature/Science journal inspired) ──
# A figure in a humanities paper is read in print, often in grayscale, and cited for its numbers —
# so the palette is restrained and separated by lightness as much as by hue. The set this replaced was
# a UI accent palette (neon blue first, gradient area fills), which is why every chart looked like a
# dashboard rather than a 图; it is not kept as a second name, because on-screen charts draw through
# this one binding too and a second list would be a second answer nobody asks for.
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

#: Chart types that can carry dated event markers (a vertical line at one category). Any other
#: type that is handed the box is refused rather than ignored: an annotation the figure does not
#: show is worse than no annotation, because the user believes it is there.
ANNOTATED_TYPES = ('bar', 'line', 'dual_line')


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


def print_style(option: dict) -> dict:
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
                if axis_key == 'yAxis':
                    # A y category axis already has the whole left margin for its width and
                    # one row per label; rotating turns each name into a vertical column as
                    # tall as the label is long, which is precisely how the names start
                    # printing over each other (measured on the variation view, and the same
                    # crowding the burst/heatmap views reach at 13+ rows). Drop what cannot
                    # fit instead — the row and its marker stay, and the CSV plus the
                    # three-line table still carry every entry.
                    label['rotate'] = 0
                    label['hideOverlap'] = True
                else:
                    # Rotated and never dropped: the alternative is a figure whose axis lies
                    # about its own granularity.
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

        def _floor_margin(key: str, minimum: int) -> None:
            raw = grid.get(key)
            # A percentage margin is a chart's own responsive room for a long
            # axis label. Replacing it with the numeric floor can clip 突现词
            # or cluster names, so only pixel margins are floored.
            if isinstance(raw, str) and raw.strip().endswith('%'):
                return
            try:
                grid[key] = max(int(float(raw or 0)), minimum)
            except (TypeError, ValueError):
                grid[key] = minimum

        _floor_margin('bottom', 96)
        _floor_margin('right', 72)
        _floor_margin('left', 64)

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
