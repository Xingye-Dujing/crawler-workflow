"""Network: nodes and weighted edges drawn as a graph."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import VALUE_FIELD_AGG, X_SOURCE, Y_TARGET

MANIFEST = chart_manifest(
    'network',
    order=140,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.relations:build_network',
    summary='关系网络：来源/目标/权重三列画成节点与连线，可居中一个关键节点。',
    when_to_use='回复网络、词语共现、作者互动。',
    when_not_to_use=('只要看两两流向的带宽用桑基图；边太多时网络会变成毛线球。',),
    fields=(X_SOURCE, Y_TARGET, VALUE_FIELD_AGG),
    controls=('center_node',),
    echarts_only=True,
)
