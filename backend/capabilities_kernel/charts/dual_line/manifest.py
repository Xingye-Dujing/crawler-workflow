"""Dual-axis line chart: two curves with different scales on one figure."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import X_CATEGORY, Y2_VALUE, Y_VALUE

MANIFEST = chart_manifest(
    'dual_line',
    order=30,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.series:build_dual_line',
    summary='双轴折线图：左右两条 Y 轴各画一条曲线，量纲不同也能同图比较。',
    when_to_use='同时看“热度（条数）”与“情感指数（-1~1）”这类量纲不同的两条曲线。',
    when_not_to_use=('两条曲线量纲相同时用普通折线，双轴容易被误读成同一刻度。',),
    fields=(X_CATEGORY, Y_VALUE, Y2_VALUE),
    controls=('annotations',),
    hint_key='hint.dualLine',
    echarts_only=True,
)
