"""Bibliometric knowledge graph: nodes, coordinates and weighted links."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'knowledge_graph',
    order=150,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.graph:knowledge_graph',
    summary='文献知识图谱：节点按共现坐标布局，连线宽度表示共现强度。',
    when_to_use='文献分析之后的主题/关键词共现图谱。',
    when_not_to_use=('普通评论语料的词共现用关系网络；没有 biblio 节点写出的列时无法绘制。',),
    reads=('节点', 'x', 'y', '连接', '频次'),
    hint_key='biblio.ui.chartHint',
)
