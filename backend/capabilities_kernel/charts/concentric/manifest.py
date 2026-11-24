"""Concentric rings: each node's yearly series cut by its first year."""

from capabilities_kernel.chart import FAMILY_BIBLIO, chart_manifest

MANIFEST = chart_manifest(
    'concentric',
    order=280,
    family=FAMILY_BIBLIO,
    handler='services.biblio.charts.graph:concentric',
    summary='同心环图：按节点首次出现年份分环，环上扇区表示各年出现量。',
    when_to_use='要看“新词何时进入、老词何时退场”的首现结构。',
    when_not_to_use=('逐节点看年份用时间线/时区图更直接。',),
    reads=('节点', '年份序列', '频次'),
    hint_key='biblio.ui.chartHint',
)
