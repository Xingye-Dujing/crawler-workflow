"""Histogram: the distribution of one numeric column."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import X_VALUE

MANIFEST = chart_manifest(
    'histogram',
    order=90,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.distributions:build_histogram',
    summary='直方图：把一个数值列分箱，画出每个区间的数量分布。',
    when_to_use='看一个数值的分布形状：点赞数的长尾、长度的集中区间。',
    when_not_to_use=('要看两个数值的关系用散点图；要按类别比较用柱状图。',),
    fields=(X_VALUE,),
)
