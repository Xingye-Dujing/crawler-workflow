"""Add a computed column from an arithmetic expression."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'column_calc',
    title_key='op.column_calc',
    category='clean',
    order=170,
    summary='用一列或多列的算式派生新列（如 点赞 / 评论）。',
    when_to_use='图表需要比率、差值或加权分，而表里只有原始计数时。',
    when_not_to_use=('要按时间/数值分箱用 bin_column；要按行条件筛选用 filter_rows。',),
    handler='services.analysis.ops.column_calc:column_calc',
    params=(
        ParamSpec(name='new_col', type='string', default='', widget='text'),
        ParamSpec(name='expr', type='string', default='', widget='text'),
    ),
    reads=Reads(nonblank=('new_col', 'expr')),
    writes=Writes(mode='add', add=(('new_col', ''),)),
    panel=(
        PanelField('new_col', 'new_col', 'settings.newCol'),
        PanelField('expr', 'expr', 'settings.expr'),
    ),
)
