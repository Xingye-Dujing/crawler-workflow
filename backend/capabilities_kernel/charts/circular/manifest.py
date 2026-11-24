"""Circular layout of the bibliometric graph."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'circular',
    order=190,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.graph:circular',
    summary='环形共现图：节点沿圆周排布，连线表示共现关系。',
    when_to_use='共现关系多、力导向布局容易挤成一团时。',
    when_not_to_use=('要看聚类分组用知识图谱或聚类景观图。',),
    reads=('节点', '连接', '频次'),
    hint_key='biblio.ui.chartHint',
)
