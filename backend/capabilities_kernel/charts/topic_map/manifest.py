"""Topic map: topics placed on a plane by distance, sized by prevalence."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import LABEL_FIELD, VALUE_FIELD, X_COORDINATE, Y_COORDINATE

MANIFEST = chart_manifest(
    'topic_map',
    order=50,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.topics:build_topic_map',
    summary='主题距离图：每个主题一个气泡，位置是主题间距离，大小是文档占比。',
    when_to_use='主题距离图：看哪些主题彼此接近、哪个主题占比最大。',
    when_not_to_use=('要看每个主题的词用显著词图；没有 pc1/pc2 列时先用分析节点生成。',),
    fields=(X_COORDINATE, Y_COORDINATE, LABEL_FIELD, VALUE_FIELD),
    defaults=(('x_field', 'pc1'), ('y_field', 'pc2'), ('label_field', 'topic'), ('value_field', 'prevalence_pct')),
    echarts_only=True,
)
