"""Flag secondary outbreaks on a period/value curve."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'alert',
    title_key='op.alert',
    category='time',
    order=370,
    summary='按连续涨跌、摆动幅度、升温与量能规则，在曲线上标出二次爆发预警点。',
    when_to_use='要在情感/热度曲线上自动指出“需要人工复核的时刻”。',
    when_not_to_use=('预警是规则给出的候选，不是因果结论；要看趋势用 forecast。',),
    handler='services.analysis.ops.alert:alert',
    params=(
        ParamSpec(name='column', type='string', default='period', widget='column'),
        ParamSpec(name='index_col', type='string', default='sentiment_index', widget='column'),
        ParamSpec(name='intensity_col', type='string', default='', widget='column'),
        ParamSpec(name='volume_col', type='string', default='', widget='column'),
        ParamSpec(name='streak', type='integer', default=2, minimum=1),
        ParamSpec(name='swing', type='number', default=0.2, minimum=0),
        ParamSpec(name='heating', type='number', default=0.15, minimum=0),
        ParamSpec(name='volume_floor', type='number', default=0.6, minimum=0, maximum=1),
    ),
    reads=Reads(one=('column', 'index_col')),
    writes=Writes(mode='replace', columns=('period', 'signal', 'value', 'threshold', 'reason')),
    labels=(('index_col', 'settings.alertIndexColumn'),),
)
