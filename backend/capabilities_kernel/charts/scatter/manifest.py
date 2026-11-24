"""Scatter plot: two numeric columns against each other."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import X_VALUE, Y_VALUE_REQUIRED

MANIFEST = chart_manifest(
    'scatter',
    order=80,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.relations:build_scatter',
    summary='散点图：两个数值列做坐标，看相关关系与离群点。',
    when_to_use='两个数值的关系：点赞与评论、两个模型的得分、热度与情感指数。',
    when_not_to_use=('只有一个数值列时看分布用直方图。',),
    fields=(X_VALUE, Y_VALUE_REQUIRED),
)
