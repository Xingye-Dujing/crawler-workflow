"""Salient terms: each topic's distinguishing words with their frequencies."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import X_CATEGORY, Y2_VALUE, Y_VALUE_REQUIRED

MANIFEST = chart_manifest(
    'topic_terms',
    order=60,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.topics:build_topic_terms',
    summary='显著词图：每个主题里最有区分度的词，及其总体频率与主题内频率。',
    when_to_use='显著词图：说明每个主题真正独特的词，而不是全语料高频词。',
    when_not_to_use=('要看主题在平面上的位置用主题距离图。',),
    fields=(X_CATEGORY, Y_VALUE_REQUIRED, Y2_VALUE),
    defaults=(('x_field', 'term'), ('y_field', 'overall_freq'), ('y2_field', 'within_freq')),
    echarts_only=True,
)
