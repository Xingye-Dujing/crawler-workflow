"""Cut a numeric column into equal-width or explicit bins."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMN

MANIFEST = operator_manifest(
    'bin_column',
    title_key='op.bin_column',
    category='clean',
    order=180,
    summary='把数值列分成若干区间或给定边界，并写成一列分箱标签。',
    when_to_use='把连续的热度/时长变成可做分组统计的类别。',
    when_not_to_use=('按时间分阶段用 bin_time；要写算式列用 column_calc。',),
    handler='services.analysis.ops.bin_column:bin_column',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='bins', type='array', default=[]),
        ParamSpec(name='labels', type='array', default=[]),
        ParamSpec(name='new_col', type='string', default='', widget='text'),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='add', add=(('new_col', ''),), add_from_column=True),
    panel=(
        COLUMN,
        PanelField('bin_new_col', 'new_col', 'settings.binNewCol'),
        PanelField('bins', 'bins', 'settings.binEdges', placeholder='4 或 0, 60, 80, 100'),
        PanelField('bin_labels', 'labels', 'settings.binLabels', placeholder='low, mid, high'),
    ),
)
