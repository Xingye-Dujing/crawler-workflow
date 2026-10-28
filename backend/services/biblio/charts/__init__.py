"""ECharts options for the bibliometric views.

One builder per view, in the family module that owns it; ``BUILDERS`` is the single
place a view is registered, so a new figure is one function and one line here.
"""

import pandas as pd

from i18n import t

from . import graph, maps, overlay, timeline
from .base import BiblioChartError

BUILDERS = {
    'knowledge_graph': graph.knowledge_graph,
    'cluster_timeline': timeline.cluster_timeline,
    'burst': timeline.burst,
    'timezone': timeline.timezone,
    'circular': graph.circular,
    'landscape': timeline.landscape,
    'biblio_heatmap': timeline.biblio_heatmap,
    'graph3d': graph.graph3d,
    'variation': maps.variation,
    'dual_map': maps.dual_map,
    'geo_map': maps.geo_map,
    'sentiment_overlay': overlay.sentiment_overlay,
    'topic_overlay': overlay.topic_overlay,
    'concentric': graph.concentric,
}


def build(df: pd.DataFrame, chart_type: str, base: dict) -> dict:
    builder = BUILDERS.get(chart_type)
    if builder is None:
        raise BiblioChartError(t('chart.biblio_unknown', type=chart_type))
    return builder(df, base)
