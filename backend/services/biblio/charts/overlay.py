"""Sentiment and topic overlays on top of a graph.

Both views keep the same row limit and the same colour semantics as the console
charts: polarity is ordered negative → neutral → positive and coloured by meaning.
"""

import pandas as pd

from i18n import t
from services.charts.contracts import (
    OVERLAY_ROW_LIMIT,
    OVERLAY_TOPIC_LIMIT,
    POLARITY_COLORS,
    POLARITY_LABELS,
)

from .base import BiblioChartError, _number, _parsed, _require, _text

# ─── sentiment / topic overlays ──────────────────────────────────


def _overlay_word(label: str) -> str:
    """A stored label as the word this run's language shows (正面 / Positive / 主题-1 …).

    The catalogue lives in ``visualizer`` beside every other chart-localisation token. The import
    is local because ``visualizer`` imports this module when it builds a bibliometric option —
    a module-level back-import would be a cycle in the direction the layering already avoids.
    """
    from services.charts.visualizer import _localize_label

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


def sentiment_overlay(df: pd.DataFrame, base: dict) -> dict:
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


def topic_overlay(df: pd.DataFrame, base: dict) -> dict:
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
