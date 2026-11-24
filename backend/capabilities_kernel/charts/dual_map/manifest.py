"""Dual map: two overlays linked by weighted flows."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'dual_map',
    order=240,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.maps:dual_map',
    summary='双层图：左右两层各自成簇，中间用流量连线表示跨层对应。',
    when_to_use='把“施引/被引”或“方法/主题”两层结构放在一张图里。',
    when_not_to_use=('只有一层结构时用知识图谱。',),
    reads=('map', 'source', 'target', 'weight'),
    hint_key='biblio.ui.chartHint',
)
