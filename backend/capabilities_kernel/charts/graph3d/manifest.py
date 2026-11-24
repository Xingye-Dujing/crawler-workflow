"""3-D bibliometric graph."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'graph3d',
    order=220,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.graph:graph3d',
    summary='三维共现图：在三个坐标上展开节点，用深度缓解平面拥挤。',
    when_to_use='共现关系密集、二维图互相遮挡时。',
    when_not_to_use=('要印刷或静态截图时用二维知识图谱，三维在纸上无法阅读。',),
    reads=('节点', 'x', 'y', '连接', '频次'),
    hint_key='biblio.ui.chartHint',
)
