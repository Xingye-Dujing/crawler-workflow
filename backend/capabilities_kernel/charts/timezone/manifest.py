"""Bibliometric timezone view: each node's yearly counts as a strip."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'timezone',
    order=180,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.timeline:timezone',
    summary='时区图：每个节点按年份序列铺开，颜色表示该年的出现量。',
    when_to_use='看单个关键词在每一年是否出现、出现多少。',
    when_not_to_use=('要按簇汇总用聚类时间线。',),
    reads=('节点', '年份序列', '频次'),
    hint_key='biblio.ui.chartHint',
)
