"""Word cloud: term size follows its value."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import VALUE_FIELD, X_TEXT

MANIFEST = chart_manifest(
    'wordcloud',
    order=290,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.distributions:build_wordcloud',
    summary='词云：词语按权重放大排布，一眼看出高频词。',
    when_to_use='分词结果的直观展示，尤其是报告首页的“关键词印象”。',
    when_not_to_use=('要精确比较词频用柱状图或表格；词太多时词云会看不清。',),
    fields=(X_TEXT, VALUE_FIELD),
    controls=('tokenize', 'wordcloud_style'),
    tokenize_compatible=True,
    echarts_only=True,
)
