"""Build a word co-occurrence edge list from one text column."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'cooccur',
    title_key='op.cooccur',
    category='topic',
    order=340,
    summary='统计同一文本窗口内共同出现的词对，输出 source/target/value 边表。',
    when_to_use='要画词语共现网络，看概念如何绑定在一起。',
    when_not_to_use=('要主题的特征词用 topic_model 或 topic_salience。',),
    handler='services.analysis.ops.cooccur:cooccur',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='topn', type='integer', default=30, minimum=2),
        ParamSpec(name='min_count', type='integer', default=2, minimum=1),
        ParamSpec(name='window', type='integer', default=0, minimum=0),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='replace', columns=('source', 'target', 'value')),
)
