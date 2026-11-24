"""Sentiment overlay on the bibliometric graph."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'sentiment_overlay',
    order=260,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.overlay:sentiment_overlay',
    summary='情感叠加图：节点按情感分布着色，看研究板块的情绪倾向。',
    when_to_use='文献分析时填了情感映射，想在图谱上区分正负。',
    when_not_to_use=('没有情感分布列时无法着色；普通情感演化用折线图。',),
    reads=('节点', '情感分布'),
    hint_key='biblio.ui.chartHint',
)
