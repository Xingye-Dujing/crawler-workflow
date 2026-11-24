"""Bar chart: one bar per category, length = the aggregated value."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import X_CATEGORY, Y_VALUE

MANIFEST = chart_manifest(
    'bar',
    order=10,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.series:build_bar',
    summary='柱状图：每个类别一根柱子，柱长表示聚合后的数值。',
    when_to_use='类别之间比大小：各平台发帖量、高频词、各主题文档数。',
    when_not_to_use=(
        '类别多到看不清（十几类以上）时改用表格或折线；看份额用饼图/百分比堆叠。',
        '时间连续且点多时用折线图。',
    ),
    fields=(X_CATEGORY, Y_VALUE),
    controls=('annotations',),
    tokenize_compatible=True,
)
