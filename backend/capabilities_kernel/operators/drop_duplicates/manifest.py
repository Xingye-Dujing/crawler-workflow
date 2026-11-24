"""Drop duplicate rows by exact text or by normalised text."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMNS

MANIFEST = operator_manifest(
    'drop_duplicates',
    title_key='op.drop_duplicates',
    category='clean',
    order=30,
    summary='按所选列删除重复行；exact 逐字比较，normalized 先做全半角/空白归一。',
    when_to_use='同一行被采集了两次（翻页重叠、导出合并）时去重。',
    when_not_to_use=('两段文字意思相同但写法不同时用 dedupe_similar 或 semantic_dedupe。',),
    handler='services.analysis.ops.drop_duplicates:drop_duplicates',
    params=(
        ParamSpec(name='columns', type='array', default=[], widget='column'),
        ParamSpec(name='keep', type='string', default='first', widget='select'),
        ParamSpec(
            name='mode',
            type='string',
            default='exact',
            enum=('exact', 'normalized'),
            widget='select',
        ),
    ),
    reads=Reads(some=('columns',)),
    writes=Writes(mode='passthrough'),
    panel=(
        COLUMNS,
        PanelField(
            'mode',
            'mode',
            'settings.dedupeMode',
            control='select',
            default='exact',
            options=(('exact', 'settings.dedupeModeExact'), ('normalized', 'settings.dedupeModeNormalized')),
        ),
    ),
    labels=(('mode', 'settings.dedupeMode'),),
)
