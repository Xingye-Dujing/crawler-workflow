"""Box plot: the distribution of a value per category."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import X_OPTIONAL, Y_VALUE

MANIFEST = chart_manifest(
    'box',
    order=100,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.distributions:build_box',
    summary='箱线图：按类别展示数值的中位数、四分位与离群值。',
    when_to_use='比较不同类别的分布形状，而不只是均值：各平台点赞分布。',
    when_not_to_use=('只需要均值或总量时用柱状图；样本极少时箱线图没有意义。',),
    fields=(X_OPTIONAL, Y_VALUE),
    any_of=(('x_field', 'y_field'),),
)
