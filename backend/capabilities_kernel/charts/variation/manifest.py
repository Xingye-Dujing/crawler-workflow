"""Bibliometric variation map: each node's active year span."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'variation',
    order=230,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.maps:variation',
    summary='变化图：每个节点的起止年与结构变化，用颜色标记上升/下降。',
    when_to_use='看关键词在研究周期内是升温还是退场。',
    when_not_to_use=('要看突现强度与区间用突现词图。',),
    reads=('节点', '起始年', '结束年', '结构变化'),
    hint_key='biblio.ui.chartHint',
)
