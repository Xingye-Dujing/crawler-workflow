"""Bibliometric cluster timeline: clusters over time."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'cluster_timeline',
    order=160,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.timeline:cluster_timeline',
    summary='聚类时间线：每条聚类一行，横轴是首年到末年。',
    when_to_use='看各主题簇的活跃年代与延续长度。',
    when_not_to_use=('需要单节点的突现年份用突现图。',),
    reads=('节点', '聚类', '聚类标签', '首年', '末年', '频次'),
    hint_key='biblio.ui.chartHint',
)
