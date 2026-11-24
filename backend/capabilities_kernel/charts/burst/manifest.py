"""Burst detection: the years a node's frequency surged."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'burst',
    order=170,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.timeline:burst',
    summary='突现词图：每个节点标出突现的起止年份与强度。',
    when_to_use='找出某一时期突然升温的关键词。',
    when_not_to_use=('看整体聚类年代跨度的聚簇时间线更合适。',),
    reads=('节点', '突现起始', '突现结束', '突现强度'),
    hint_key='biblio.ui.chartHint',
)
