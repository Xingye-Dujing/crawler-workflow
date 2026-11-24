"""Sankey diagram: weighted flows between a source and a target column."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import VALUE_FIELD_AGG, X_SOURCE, Y_TARGET

MANIFEST = chart_manifest(
    'sankey',
    order=130,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.relations:build_sankey',
    summary='桑基图：来源到目标的带权流向，带宽表示流量。',
    when_to_use='主题流向、平台到情感的去向、阶段之间的转移。',
    when_not_to_use=('没有“从哪到哪”的两列时用柱状图或热力图。',),
    fields=(X_SOURCE, Y_TARGET, VALUE_FIELD_AGG),
    echarts_only=True,
)
