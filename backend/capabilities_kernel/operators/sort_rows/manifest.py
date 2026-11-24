"""Sort rows by one column."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMN

MANIFEST = operator_manifest(
    'sort_rows',
    title_key='op.sort_rows',
    category='clean',
    order=120,
    summary='按一列升序或降序重排行（行集合不变）。',
    when_to_use='图表 X 轴或分阶段分析要求按时间/热度排序时。',
    when_not_to_use=('要按分组聚合用 groupby_agg；要取子集用 sample_rows 或 filter_rows。',),
    handler='services.analysis.ops.sort_rows:sort_rows',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='ascending', type='boolean', default=True, widget='switch'),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='passthrough'),
    panel=(
        COLUMN,
        PanelField('ascending', 'ascending', 'settings.ascending', control='checkbox', default=True),
    ),
)
