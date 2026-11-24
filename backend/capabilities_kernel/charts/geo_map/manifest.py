"""Choropleth of node counts over the committed basemap."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'geo_map',
    order=250,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.maps:geo_map',
    summary='文献地理分布图：把各节点的频次铺到内置底图的分区上。',
    when_to_use='文献数据带有地区维度时。',
    when_not_to_use=('普通语料的地区热度用地图图，它读的是你自己的地区列。',),
    reads=('节点', '频次'),
    hint_key='biblio.ui.chartHint',
)
