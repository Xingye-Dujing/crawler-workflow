"""Keep only the rows whose key is absent from the other table."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'anti_join',
    title_key='op.anti_join',
    category='join',
    order=160,
    summary='按连接键排除已出现在第二张表里的行（内容去重），可只保留交集。',
    when_to_use='新一轮采集前先剔掉上一轮已抓过的链接/内容。',
    when_not_to_use=('要合并两张表的列用 join_tables；同一张表内去重用 drop_duplicates。',),
    handler='services.analysis.ops.anti_join:anti_join',
    params=(
        ParamSpec(name='left_on', type='string', default='', widget='column'),
        ParamSpec(name='right_on', type='string', default='', widget='column'),
        ParamSpec(
            name='mode',
            type='string',
            default='trim',
            enum=('exact', 'trim', 'url', 'text', 'similar'),
            widget='select',
        ),
        ParamSpec(name='keep', type='string', default='exclude', enum=('exclude', 'keep'), widget='select'),
        ParamSpec(name='ignore_case', type='boolean', default=False, widget='switch'),
        ParamSpec(name='max_distance', type='integer', default=8, minimum=0, maximum=10),
        ParamSpec(name='swap_tables', type='boolean', default=False, widget='switch'),
    ),
    reads=Reads(two_table_keys=('left_on', 'right_on')),
    writes=Writes(mode='unknown'),
    empty_by_design=True,
    labels=(('mode', 'settings.matchMode'),),
)
