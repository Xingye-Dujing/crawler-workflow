"""Bibliometric heatmap: clusters against years."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'biblio_heatmap',
    order=210,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.timeline:biblio_heatmap',
    summary='文献热力图：聚类 × 年份的单元格热度，看各板块何时活跃。',
    when_to_use='比较多个聚类在不同年份的强度。',
    when_not_to_use=('只看单个节点逐年出现用时区图。',),
    reads=('节点', '聚类', '聚类标签', '年份序列', '频次'),
    hint_key='biblio.ui.chartHint',
)
