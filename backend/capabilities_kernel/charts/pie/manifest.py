"""Pie chart: shares of one whole."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import X_CATEGORY, Y_VALUE

MANIFEST = chart_manifest(
    'pie',
    order=70,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.distributions:build_pie',
    summary='饼图：一个整体被分成几份，扇面角度表示占比。',
    when_to_use='少量类别（约 6 个以内）的份额构成，如情感分布。',
    when_not_to_use=('类别多或需要精确比较大小时用柱状图；份额为负无法画面积。',),
    fields=(X_CATEGORY, Y_VALUE),
    tokenize_compatible=True,
)
