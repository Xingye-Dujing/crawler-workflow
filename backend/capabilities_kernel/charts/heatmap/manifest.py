"""Heatmap: two categories against one aggregated value per cell."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import VALUE_FIELD_AGG, X_CATEGORY2, Y_CATEGORY2

MANIFEST = chart_manifest(
    'heatmap',
    order=110,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.relations:build_heatmap',
    summary='热力图：两个类别轴交叉成单元格，颜色深浅表示聚合值。',
    when_to_use='两个维度交叉的强度：阶段 × 主题、平台 × 情感。',
    when_not_to_use=('只有一个维度时用柱状图或折线图。',),
    fields=(X_CATEGORY2, Y_CATEGORY2, VALUE_FIELD_AGG),
)
