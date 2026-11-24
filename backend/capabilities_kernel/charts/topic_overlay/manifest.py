"""Topic overlay on the bibliometric graph."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'topic_overlay',
    order=270,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.overlay:topic_overlay',
    summary='话题叠加图：节点按话题分布着色，看各研究板块的话题构成。',
    when_to_use='文献分析时填了话题映射，想在图谱上看话题归属。',
    when_not_to_use=('没有话题分布列时无法着色；话题模型结果用主题距离图。',),
    reads=('节点', '话题分布'),
    hint_key='biblio.ui.chartHint',
)
