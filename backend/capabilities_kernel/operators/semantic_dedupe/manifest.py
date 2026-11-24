"""Drop semantically duplicate rows using a local sentence encoder."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMN, MODEL

MANIFEST = operator_manifest(
    'semantic_dedupe',
    title_key='op.semantic_dedupe',
    category='clean',
    order=50,
    summary='用本地句向量比较一列文本，删掉语义重复的行（同义改写也算）。',
    when_to_use='同一观点被换词重写多次，需要按意思去重时。',
    when_not_to_use=('只是字面相近用 dedupe_similar；要按关键词找相似行用 similar_to。',),
    handler='services.analysis.ops.semantic_dedupe:semantic_dedupe',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='model', type='string', default='BAAI/bge-small-zh-v1.5', widget='text'),
        ParamSpec(name='threshold', type='number', default=0.92, minimum=0, maximum=1),
        ParamSpec(name='batch_size', type='integer', default=64, minimum=1),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='passthrough'),
    panel=(
        COLUMN,
        MODEL,
        PanelField('threshold', 'threshold', 'settings.semanticThreshold', control='number', default=0.92),
    ),
)
