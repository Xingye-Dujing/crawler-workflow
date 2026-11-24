"""Line chart: a curve over ordered categories or time."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import X_CATEGORY, Y_VALUE

MANIFEST = chart_manifest(
    'line',
    order=20,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.series:build_line',
    summary='折线图：按有序类别（通常是时间）连成趋势线。',
    when_to_use='看随时间或阶段的走势：每日发帖量、情感指数曲线。',
    when_not_to_use=(
        '类别之间没有顺序时用柱状图；两条量纲不同的曲线用双轴折线。',
        '只有一个时间点或类别时用柱状图。',
    ),
    fields=(X_CATEGORY, Y_VALUE),
    controls=('annotations',),
)
