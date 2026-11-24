"""Keep or drop rows by comparing one column with a value."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMN

MANIFEST = operator_manifest(
    'filter_rows',
    title_key='op.filter_rows',
    category='clean',
    order=70,
    summary='按一列与给定值的比较（等于/包含/大于/为空…）保留或删除行。',
    when_to_use='把分析限定在一个子集：某平台、某时间段、包含某个词。',
    when_not_to_use=('要按另一张表的键去重/剔除用 anti_join；只挑列用 select_columns。',),
    handler='services.analysis.ops.filter_rows:filter_rows',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(
            name='op',
            type='string',
            default='',
            required=True,
            enum=(
                'eq',
                'ne',
                'gt',
                'gte',
                'lt',
                'lte',
                'contains',
                'not_contains',
                'in',
                'not_in',
                'is_null',
                'not_null',
            ),
            widget='select',
        ),
        ParamSpec(name='value', type='string', default='', widget='text'),
        ParamSpec(name='keep', type='string', default='keep', enum=('keep', 'exclude'), widget='select'),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='passthrough'),
    empty_by_design=True,
    template_values={'value': '示例'},
    labels=(('op', 'settings.filterOp'),),
    panel=(
        COLUMN,
        PanelField(
            'op',
            'op',
            'settings.filterOp',
            control='select',
            default='eq',
            options_param='op',
            option_label_prefix='settings.filterOp.',
        ),
        PanelField('value', 'value', 'settings.value', hide_when=('op', ('is_null', 'not_null'))),
        PanelField(
            'filter_keep',
            'keep',
            'settings.filterKeep',
            control='select',
            default='keep',
            options=(('keep', 'settings.filterKeepKeep'), ('exclude', 'settings.filterKeepExclude')),
            hint_key='settings.filterRowsHint',
        ),
    ),
)
