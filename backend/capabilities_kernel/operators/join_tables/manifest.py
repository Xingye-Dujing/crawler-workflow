"""Join two incoming tables on a key."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'join_tables',
    title_key='op.join_tables',
    category='join',
    order=150,
    summary='把第二条输入的表格按连接键拼到第一条上（left/right/inner/outer/cross）。',
    when_to_use='把主题表、统计表或另一平台的结果按共同键合并成一张宽表。',
    when_not_to_use=('只想剔除已在另一张表里的行用 anti_join；同表内改列用 rename_columns。',),
    handler='services.analysis.ops.join_tables:join_tables',
    params=(
        ParamSpec(
            name='how',
            type='string',
            default='left',
            enum=('left', 'right', 'inner', 'outer', 'cross'),
            widget='select',
        ),
        ParamSpec(name='left_on', type='string', default='', widget='column'),
        ParamSpec(name='right_on', type='string', default='', widget='column'),
    ),
    reads=Reads(two_table_keys=('left_on', 'right_on')),
    writes=Writes(mode='unknown'),
    empty_by_design=True,
    labels=(('how', 'settings.joinHow'),),
)
