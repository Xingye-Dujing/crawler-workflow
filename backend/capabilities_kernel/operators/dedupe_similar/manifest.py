"""Drop near-duplicate rows by SimHash over one text column."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMN

MANIFEST = operator_manifest(
    'dedupe_similar',
    title_key='op.dedupe_similar',
    category='clean',
    order=40,
    summary='按一列文本的 SimHash 距离删除近似重复行（改写、加表情、换标点）。',
    when_to_use='评论/转发里同一句话被改写多次时，保留一条代表。',
    when_not_to_use=('需要语义相似（同义改写）时用 semantic_dedupe；逐字重复用 drop_duplicates。',),
    handler='services.analysis.ops.dedupe_similar:dedupe_similar',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='max_distance', type='integer', default=8, minimum=0, maximum=10),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='passthrough'),
    panel=(
        COLUMN,
        PanelField(
            'max_distance',
            'max_distance',
            'settings.dedupeDistance',
            control='number',
            default=8,
            hint_key='settings.dedupeSimilarHint',
        ),
    ),
)
