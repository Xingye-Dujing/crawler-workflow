"""Cut a timestamp column into named phases at explicit boundaries."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'bin_time',
    title_key='op.bin_time',
    category='time',
    order=200,
    summary='按给定时间边界把行切成阶段，并写入阶段名与可选的阶段序号。',
    when_to_use='要做分阶段 LDA、主题演化或情感演化，先把时间轴切成“发酵/爆发/衰退”。',
    when_not_to_use=('不知道边界时先用 suggest_stages 提议；只取日期用 extract_time。',),
    handler='services.analysis.ops.bin_time:bin_time',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='edges', type='array', default=[]),
        ParamSpec(name='labels', type='array', default=[]),
        ParamSpec(name='new_col', type='string', default='阶段', widget='text'),
        ParamSpec(name='order_new_col', type='string', default='', widget='text'),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='add', add=(('new_col', '阶段'),), add_maybe=(('order_new_col', ''),)),
    checks=('services.analysis.step_checks:bin_time_shape',),
    labels=(('edges', 'settings.phaseEdges'), ('labels', 'settings.phaseLabels')),
    template_values={'edges': ['2022-01-01', '2022-02-01'], 'labels': ['发酵']},
)
