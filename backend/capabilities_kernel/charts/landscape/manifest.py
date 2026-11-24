"""Bibliometric landscape: clusters drawn as adjacent territories."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'landscape',
    order=200,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.timeline:landscape',
    summary='聚类景观图：把每个聚类画成一块区域，块内是它的成员节点。',
    when_to_use='用一页说明文献由哪几个研究板块构成。',
    when_not_to_use=('要看板块随年代的变化用聚类时间线或热力图。',),
    reads=('节点', '聚类', '聚类标签', '频次'),
    hint_key='biblio.ui.chartHint',
)
