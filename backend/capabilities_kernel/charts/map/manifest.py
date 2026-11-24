"""Map: a region column against a value, over the built-in basemap."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import VALUE_FIELD, X_GEO

MANIFEST = chart_manifest(
    'map',
    order=300,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.distributions:build_map',
    summary='地图图：按地区名称把数值铺到地图上，颜色深浅表示大小。',
    when_to_use='语料带地区维度（IP 归属、用户城市）时。',
    when_not_to_use=('地区名与内置底图不一致时会落空；没有地区列时用柱状图。',),
    fields=(X_GEO, VALUE_FIELD),
    hint_key='hint.mapRegionNames',
    echarts_only=True,
)
